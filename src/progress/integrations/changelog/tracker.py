"""Changelog integration business logic (spec 06 / spec changelog).

The tracker fetches each changelog source, parses it into version sections,
selects the new versions using the four-state ``check`` algorithm (spec
changelog §5), persists an aggregated :class:`Report` via the reports
pipeline (one ``changelog`` row per tracker that produced new versions), and
dispatches a :class:`ChangelogEvent` per tracker carrying the latest version.

Feature 6 generalizes parsing: :class:`UniversalChangelogParser` runs a
deterministic-first chain (learned rule → built-in strategies), and only
falls back to an AI structure analysis when all deterministic paths fail.
When the AI can emit a reusable :class:`ChangelogRule`, it is persisted to
``ChangelogTracker.learned_rule`` so subsequent parses skip the AI entirely.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from opentelemetry import trace
from pydantic import BaseModel

from progress.cli.ai import build_model_string, get_agent, run_extraction
from progress.cli.notifications.events import ChangelogEvent, NotificationEvent
from progress.cli.reports.prompts import render_prompt
from progress.config.root import AnalysisConfig, CoreConfig
from progress.db import get_config
from progress.errors import ExternalServiceException, ProgressException
from progress.integrations.base import (
    Components,
    ReportSection,
    RunResult,
    SyncResult,
    strip_unknown_config_keys,
)
from progress.integrations.changelog.config import ChangelogIntegrationConfig
from progress.integrations.changelog.models import ChangelogTracker
from progress.integrations.changelog.parsers import (
    _BUILTIN_STRATEGIES,
    ChangelogRule,
    ChangelogVersion,
    apply_rule,
)
from progress.integrations.registry import register
from progress.observability import record_business_event, report_severe
from progress.utils.http import retry_async
from progress.utils.timezone import now_utc

if TYPE_CHECKING:
    from progress.cli.reports.pipeline import IntegrationReport

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS: float = 300.0
FETCH_USER_AGENT: str = "progress"


@dataclass
class ChangelogCheckResult:
    """Outcome of one tracker check (spec changelog §5.1).

    Four terminal states:
    - ``skipped``: tracker disabled (no field updates).
    - ``success``: parsed AND new versions found (advance watermark + stamp).
    - ``no_new_version``: parsed but no new versions (stamp only).
    - ``failed``: fetch / parse / unknown parser (stamp only).
    """

    status: str
    new_entries: list[ChangelogVersion] | None = None
    latest_version: str | None = None
    error: str | None = None


class ChangelogStructureAnalysis(BaseModel):
    """AI structure-analysis output: a reusable rule + fallback versions."""

    deterministic_rule: ChangelogRule | None = None
    versions: list[dict[str, Any]] = []


class UniversalChangelogParser:
    """Deterministic-first changelog parser with AI fallback that learns rules.

    Flow per ``parse(text, url, tracker)``:
    1. If ``tracker.learned_rule`` is set → deserialize ``ChangelogRule`` →
       :func:`apply_rule`. Success → increment ``rule_success_count`` → return (no AI).
    2. Try built-in strategies filtered by ``parser_type`` (auto = all):
       ``markdown_heading`` → ``html_generic``.
    3. All fail → AI fallback: analyze structure, prefer ``deterministic_rule``.
       If the rule produced → apply it this run, persist ``learned_rule`` → return.
       Else → return the AI's ``versions`` directly (no rule persisted).
    Every decision point is recorded as span attributes/events for debuggability.
    """

    def __init__(self, cfg: CoreConfig | None) -> None:
        self._cfg = cfg

    async def parse(self, text: str, url: str, tracker: ChangelogTracker) -> list[ChangelogVersion]:
        tracer = trace.get_tracer("progress")
        with tracer.start_as_current_span("progress.changelog.parse") as span:
            span.set_attribute("changelog.url", url)
            span.set_attribute("changelog.tracker", tracker.name or url)
            span.set_attribute("changelog.has_learned_rule", tracker.learned_rule is not None)

            # 1. learned rule
            if tracker.learned_rule:
                try:
                    rule = ChangelogRule.model_validate_json(tracker.learned_rule)
                    span.add_event("trying_learned_rule", {"rule": (tracker.learned_rule or "")[:500]})
                    record_business_event(
                        "progress.changelog.strategy_attempted",
                        attributes={"strategy": "learned_rule"},
                    )
                    versions = apply_rule(text, rule)
                    if versions:
                        span.set_attribute("changelog.path", "learned_rule")
                        span.set_attribute("changelog.versions_found", len(versions))
                        tracker.rule_success_count += 1
                        await tracker.save()
                        record_business_event(
                            "progress.changelog.parsed",
                            attributes={"path": "learned_rule", "url": url},
                        )
                        return versions
                    span.add_event("learned_rule_failed", {"reason": "no versions matched"})
                    record_business_event(
                        "progress.changelog.strategy_failed",
                        attributes={"strategy": "learned_rule", "reason": "no_versions_matched"},
                    )
                except Exception as e:
                    span.add_event("learned_rule_failed", {"reason": str(e)[:200]})
                    report_severe(e)
                    record_business_event(
                        "progress.changelog.strategy_failed",
                        attributes={"strategy": "learned_rule", "reason": "error"},
                    )

            # 2. built-in strategies
            hint = tracker.parser_type or "auto"
            order = ["markdown_heading", "html_generic"] if hint == "auto" else [hint]
            for strategy_name in order:
                strategy = _BUILTIN_STRATEGIES.get(strategy_name)
                if strategy is None:
                    continue
                span.add_event("trying_strategy", {"strategy": strategy_name})
                record_business_event(
                    "progress.changelog.strategy_attempted",
                    attributes={"strategy": strategy_name},
                )
                try:
                    versions = strategy(text)
                    if versions:
                        span.set_attribute("changelog.path", strategy_name)
                        span.set_attribute("changelog.versions_found", len(versions))
                        span.add_event(
                            "strategy_matched",
                            {"strategy": strategy_name, "first_version": versions[0].version},
                        )
                        record_business_event(
                            "progress.changelog.parsed",
                            attributes={"path": strategy_name, "url": url},
                        )
                        return versions
                    span.add_event("strategy_no_match", {"strategy": strategy_name})
                    record_business_event(
                        "progress.changelog.strategy_failed",
                        attributes={"strategy": strategy_name, "reason": "no_match"},
                    )
                except Exception as e:
                    span.add_event("strategy_error", {"strategy": strategy_name, "error": str(e)[:200]})
                    report_severe(e)
                    record_business_event(
                        "progress.changelog.strategy_failed",
                        attributes={"strategy": strategy_name, "reason": "error"},
                    )

            # 3. AI fallback
            span.set_attribute("changelog.path", "ai_fallback")
            record_business_event("progress.changelog.ai_fallback", attributes={"url": url})
            ai_result = await self._ai_analyze(text, url)
            if ai_result.deterministic_rule is not None:
                span.add_event(
                    "ai_result",
                    {
                        "has_rule": True,
                        "versions_count": len(ai_result.versions),
                        "raw_rule": ai_result.deterministic_rule.model_dump_json()[:500],
                    },
                )
                try:
                    versions = apply_rule(text, ai_result.deterministic_rule)
                    if versions:
                        tracker.learned_rule = ai_result.deterministic_rule.model_dump_json()
                        tracker.rule_success_count = 1
                        await tracker.save()
                        span.add_event("learned_rule_persisted", {"rule": (tracker.learned_rule or "")[:500]})
                        record_business_event(
                            "progress.changelog.parsed",
                            attributes={"path": "ai_learned_rule", "url": url},
                        )
                        return versions
                except Exception as e:
                    span.add_event("ai_rule_apply_failed", {"error": str(e)[:200]})
                    report_severe(e)
            # last resort: use the AI-supplied versions directly
            result = [
                ChangelogVersion(version=v.get("version", ""), description=v.get("description", ""))
                for v in ai_result.versions
                if v.get("version")
            ]
            span.set_attribute("changelog.versions_found", len(result))
            record_business_event(
                "progress.changelog.parsed",
                attributes={"path": "ai_versions", "url": url},
            )
            return result

    async def _ai_analyze(self, text: str, url: str) -> ChangelogStructureAnalysis:
        cfg = self._cfg.analysis if self._cfg else AnalysisConfig()
        model_string = build_model_string(cfg)
        if not model_string:
            # AI unavailable → empty result; the caller surfaces no versions.
            return ChangelogStructureAnalysis()
        prompt = render_prompt(
            "structure_analysis.j2",
            content=text[:8000],
            url=url,
        )
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        agent = get_agent(
            ChangelogStructureAnalysis,
            model=model_string,
            api_key=api_key,
            base_url=cfg.base_url or None,
        )
        try:
            result = await run_extraction(agent, prompt)
        except Exception as e:
            logger.warning("changelog AI structure analysis failed: %s", e)
            report_severe(e)
            return ChangelogStructureAnalysis()
        if isinstance(result, ChangelogStructureAnalysis):
            return result
        try:
            return ChangelogStructureAnalysis.model_validate(result)
        except Exception as e:
            logger.warning("changelog AI structure analysis parse failed: %s", e)
            report_severe(e)
            return ChangelogStructureAnalysis()


@register("changelog")
class ChangelogIntegration:
    """Fetch and parse changelog sources; emit reports + events."""

    name = "changelog"
    config_schema = ChangelogIntegrationConfig
    models_module = "progress.integrations.changelog.models"

    def __init__(self) -> None:
        self._ctx: Components | None = None
        self._cfg: CoreConfig | None = None
        self._plugin_cfg: ChangelogIntegrationConfig = ChangelogIntegrationConfig()

    async def setup(self, ctx: Components) -> None:
        self._ctx = ctx
        self._cfg = ctx.cfg
        self._plugin_cfg = await self._load_plugin_config()

    async def sync(self) -> SyncResult:
        result = SyncResult()
        plugin_cfg = self._plugin_cfg

        desired_urls = {item.url for item in plugin_cfg.trackers}
        existing = {t.url: t async for t in ChangelogTracker.all()}

        for cfg_item in plugin_cfg.trackers:
            row = existing.get(cfg_item.url)
            if row is None:
                await ChangelogTracker.create(
                    name=cfg_item.name,
                    url=cfg_item.url,
                    parser_type=cfg_item.parser_type,
                    enabled=cfg_item.enabled,
                    proxy=cfg_item.proxy,
                )
                result.created += 1
            else:
                changed = False
                if row.name != cfg_item.name:
                    row.name = cfg_item.name
                    changed = True
                if row.parser_type != cfg_item.parser_type:
                    row.parser_type = cfg_item.parser_type
                    changed = True
                if row.enabled != cfg_item.enabled:
                    row.enabled = cfg_item.enabled
                    changed = True
                if row.proxy != cfg_item.proxy:
                    row.proxy = cfg_item.proxy
                    changed = True
                if changed:
                    await row.save()
                    result.updated += 1

        for url, row in existing.items():
            if url not in desired_urls:
                await row.delete()
                result.deleted += 1

        record_business_event(
            "progress.changelog.sync",
            attributes={
                "created": str(result.created),
                "updated": str(result.updated),
                "deleted": str(result.deleted),
            },
        )
        return result

    async def run(self, *, concurrency: int = 1) -> RunResult:
        result = RunResult(name="changelog")
        if self._ctx is None or not isinstance(self._ctx.session, aiohttp.ClientSession):
            logger.warning("changelog run skipped: no aiohttp session")
            return result

        session = self._ctx.session
        rows = [row async for row in ChangelogTracker.all()]
        config_index = {item.url: item for item in self._plugin_cfg.trackers}

        tasks = [asyncio.create_task(self._run_one(row, config_index, session, result)) for row in rows]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                if isinstance(outcome, ProgressException):
                    logger.warning("changelog tracker failed: %s", outcome)
                    result.errors.append(outcome)
                else:
                    logger.error("changelog tracker crashed")
                    wrapped = ProgressException(f"unexpected error in changelog tracker: {outcome}")
                    result.errors.append(wrapped)
                result.status = "partial"

        if result.errors and not result.reports and not result.events:
            result.status = "failed"
        elif result.errors:
            result.status = "partial"
        return result

    async def _run_one(
        self,
        tracker_row: ChangelogTracker,
        config_index: dict[str, Any],
        session: aiohttp.ClientSession,
        result: RunResult,
    ) -> None:
        check = await self._check(tracker_row, session)
        if check.status == "success" and check.new_entries:
            logger.info(
                "changelog %s: %d new version(s), latest=%s",
                tracker_row.name,
                len(check.new_entries),
                check.new_entries[0].version,
            )
            tracker_row.last_seen_version = check.new_entries[0].version
            tracker_row.last_check_time = now_utc()
            await tracker_row.save()
            section = ReportSection(
                title=tracker_row.name,
                content="",
                payload={
                    "name": tracker_row.name,
                    "url": tracker_row.url,
                    "new_entries": [
                        {"version": entry.version, "description": entry.description} for entry in check.new_entries
                    ],
                },
            )
            result.reports.append(section)
            latest = check.new_entries[0]
            result.events.append(
                ChangelogEvent(
                    name=tracker_row.name,
                    version=latest.version,
                    url=tracker_row.url,
                    body=latest.description,
                    description=latest.description,
                )
            )
            return

        if check.status in {"no_new_version", "failed"}:
            tracker_row.last_check_time = now_utc()
            await tracker_row.save()

        if check.status == "failed":
            raise ProgressException(
                f"changelog check failed for {tracker_row.name}: {check.error or 'unknown error (no exception detail captured)'}"
            )

    async def _check(
        self,
        tracker_row: ChangelogTracker,
        session: aiohttp.ClientSession,
    ) -> ChangelogCheckResult:
        """Run the four-state check algorithm (spec changelog §5)."""
        if not tracker_row.enabled:
            return ChangelogCheckResult(status="skipped")

        proxy = tracker_row.proxy or None

        try:
            text = await self._fetch_text(session, tracker_row.url, proxy=proxy)
        except Exception as e:
            report_severe(e)
            return ChangelogCheckResult(status="failed", error=str(e) or f"{type(e).__name__} (no message)")

        try:
            parser = UniversalChangelogParser(self._cfg)
            versions = await parser.parse(text, tracker_row.url, tracker_row)
        except Exception as e:
            report_severe(e)
            return ChangelogCheckResult(status="failed", error=str(e) or f"{type(e).__name__} (no message)")

        if not versions:
            return ChangelogCheckResult(
                status="failed",
                error="No version entries found",
            )

        new_entries, warning = detect_new_entries(versions, tracker_row.last_seen_version)
        if not new_entries:
            return ChangelogCheckResult(
                status="no_new_version",
                latest_version=versions[0].version if versions else None,
            )

        return ChangelogCheckResult(
            status="success",
            new_entries=new_entries,
            latest_version=new_entries[0].version,
            error=warning,
        )

    async def _fetch_text(self, session: aiohttp.ClientSession, url: str, *, proxy: str | None = None) -> str:
        """Fetch the changelog page (spec changelog §9).

        User-Agent: ``progress``. Total timeout 300s. 4xx/5xx → ExternalServiceException.
        ``aiohttp.ClientError`` wrapped as ExternalServiceException. Retried via
        :func:`retry_async` on transient errors (5xx / network) so a single
        hiccup no longer fails the whole tracker. 4xx is not retried — a 404
        changelog URL is a config error, not a transient blip.
        Character-set decoding is delegated to aiohttp's automatic detection
        with a mojibake-fallback chain (spec §9 allows minor adjustments).
        ``proxy`` is the tracker's own configured proxy URL, threaded per
        request (the shared session is ``trust_env=False`` and never proxies
        on its own); ``None`` fetches directly. Independent of
        ``core.github.proxy``.
        """

        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_SECONDS)
        headers = {"User-Agent": FETCH_USER_AGENT}

        async def _do_get() -> str:
            try:
                async with session.get(url, timeout=timeout, headers=headers, proxy=proxy) as resp:
                    if resp.status >= 500:
                        raise ExternalServiceException(f"changelog fetch {url} failed: HTTP {resp.status}")
                    if resp.status >= 400:
                        raise ProgressException(f"changelog fetch {url} failed: HTTP {resp.status}")
                    return await _decode_response(resp)
            except aiohttp.ClientError as e:
                raise ExternalServiceException(f"changelog fetch {url} network error: {e}") from e
            except TimeoutError as e:
                raise ExternalServiceException(f"changelog fetch {url} timed out after {FETCH_TIMEOUT_SECONDS}s") from e

        return await retry_async(
            _do_get,
            retries=2,
            retry_on=(ExternalServiceException, aiohttp.ClientError, asyncio.TimeoutError),
        )

    async def _load_plugin_config(self) -> ChangelogIntegrationConfig:
        raw = await get_config("changelog")
        if not raw:
            return ChangelogIntegrationConfig()

        raw, _ = strip_unknown_config_keys(raw, ChangelogIntegrationConfig)
        try:
            return ChangelogIntegrationConfig.model_validate(raw)
        except Exception as e:
            logger.warning("invalid changelog plugin config; using defaults: %s", e)
            report_severe(e)
            return ChangelogIntegrationConfig()

    async def build_notification(
        self,
        *,
        result: RunResult,
        reports: list[IntegrationReport],
    ) -> list[NotificationEvent]:
        """Author the aggregated changelog notification (spec 10).

        One notification per run covering every tracker that produced new
        versions. Each tracker contributes its latest version (matching the
        legacy behavior where the notification listed one entry per tracker).
        The AI title/summary/markpost URL come from the pipeline's
        :class:`IntegrationReport`.
        """
        if not reports:
            return []
        entries: list[dict[str, str]] = []
        for section in result.reports:
            new_entries = section.payload.get("new_entries") or []
            if not new_entries:
                continue
            latest = new_entries[0]
            version = latest.get("version", "")
            entries.append(
                {
                    "name": section.payload.get("name", ""),
                    "version": version,
                    "url": section.payload.get("url", ""),
                    "level": version_level(version),
                }
            )
        if not entries:
            return []
        integration_report = reports[0]
        return [
            NotificationEvent(
                kind="changelog",
                title=integration_report.title,
                summary=integration_report.summary,
                markpost_url=integration_report.markpost_url,
                total_batches=integration_report.total_batches,
                data={"entries": entries},
            )
        ]

    async def teardown(self) -> None:
        self._ctx = None
        self._cfg = None


def detect_new_entries(
    versions: list[ChangelogVersion],
    last_seen: str | None,
) -> tuple[list[ChangelogVersion], str | None]:
    """Identify new versions (spec changelog §5.3).

    Four branches, evaluated in order:

    1. Empty list → return ``([], None)`` (defensive; caller usually guards).
    2. First run (``last_seen`` is None) → return ``([versions[0]], None)``
       (only the latest single version).
    3. Watermark hit (``last_seen`` is found in the list) → return the slice
       *before* the watermark (everything newer than it).
    4. Watermark miss (``last_seen`` not in list — log was rewritten) →
       return ``([versions[0]], warning)`` with a warning string that callers
       surface via ``ChangelogCheckResult.error``.

    No sorting is performed — relies on the parser producing the list in
    document order (newest-first convention).
    """
    if not versions:
        return [], None
    if last_seen is None:
        return [versions[0]], None
    for idx, version in enumerate(versions):
        if version.version == last_seen:
            return versions[:idx], None
    warning = "Stored last_seen_version was not found in changelog; notified latest only"
    return [versions[0]], warning


async def _decode_response(resp: aiohttp.ClientResponse) -> str:
    """Decode an HTTP response body using the spec changelog §9 strategy.

    Spec mandates: try HTTP header charset first, UTF-8 as last fallback,
    skip mojibake-detected candidates, and finally fall back to UTF-8 with
    replacement characters if all candidates fail.

    The user accepted a minor adjustment: use aiohttp's built-in detection
    (``resp.charset``) when available, then UTF-8 with replacement as the
    ultimate fallback. aiohttp already attempts the header charset first and
    degrades gracefully.
    """
    raw = await resp.read()
    if not raw:
        return ""
    candidates: list[str] = []
    if resp.charset:
        candidates.append(resp.charset)
    candidates.append("utf-8")
    for candidate in candidates:
        try:
            decoded = raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
        if _looks_like_mojibake(candidate, decoded):
            continue
        return decoded
    return raw.decode("utf-8", errors="replace")


def _looks_like_mojibake(charset: str, text: str) -> bool:
    """Detect mojibake on iso-8859-1 / latin-1 / windows-1252 decodes (spec §9).

    Returns True when the candidate charset is one of the suspect ones AND the
    decoded text exhibits characteristic UTF-8-as-Latin-1 garbling:
    - Explicit U+FFFD replacement chars (defensive; should not occur on a
      successful decode but included for robustness).
    - A run of >= 3 consecutive bytes in the 0x80-0xFF range. UTF-8 multi-byte
      sequences decode to high-bit Latin-1 chars (lead bytes 0xC2-0xF4,
      continuation bytes 0x80-0xBF); genuine Latin-1 text rarely has 3+ such
      bytes in a row.
    """
    if charset.lower() not in {"iso-8859-1", "latin-1", "windows-1252"}:
        return False
    if "\ufffd" in text:
        return True
    consecutive_high = 0
    max_run = 0
    for ch in text:
        if ord(ch) >= 0x80:
            consecutive_high += 1
            max_run = max(max_run, consecutive_high)
        else:
            consecutive_high = 0
    return max_run >= 3


_SEMVER_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)")


def version_level(version: str) -> str:
    """Classify a version string as MAJOR / MINOR / PATCH (semver-ish).

    Reads only the leading ``X.Y.Z`` triple. ``X.0.0`` is MAJOR, ``X.Y.0`` (Y>0)
    is MINOR, and ``X.Y.Z`` (Z>0) is PATCH. Returns an empty string when the
    version cannot be parsed as ``X.Y.Z`` so callers can omit the badge rather
    than guess for non-semver schemes (dates, build numbers, arbitrary tags).
    """
    m = _SEMVER_RE.match(version or "")
    if not m:
        return ""
    _major, minor, patch = (int(g) for g in m.groups())
    if minor == 0 and patch == 0:
        return "MAJOR"
    if patch == 0:
        return "MINOR"
    return "PATCH"


__all__ = ["ChangelogIntegration", "UniversalChangelogParser", "detect_new_entries", "version_level"]
