"""V2EX integration business logic (spec 06 / spec v2ex).

The tracker owns the five lifecycle hooks. Per spec v2ex:

- :meth:`setup` loads ``V2exIntegrationConfig`` from the DB config table and
  builds a :class:`V2exClient` when ``base_url`` + ``interest_profile`` are both
  non-empty AND the AI is configured (``build_model_string`` non-None) AND a
  shared aiohttp session is present. v2ex's core is AI interest filtering, so
  unlike feed (where AI is an accessory) an unconfigured AI disables the
  integration rather than running noisy partials.
- :meth:`sync` reconciles :class:`V2exTracker` rows with the configured
  ``tabs`` (config-driven, like changelog).
- :meth:`run` scrapes each tab (HTML), dedups new topics by monotonic topic id,
  classifies the union in one AI call, picks a global top-K, fetches only those
  bodies, summarizes them in one AI call, and emits one ``ReportSection`` per
  tab that has selected posts.
- :meth:`build_notification` authors one aggregated ``v2ex``
  :class:`NotificationEvent` from the pipeline's :class:`IntegrationReport`.
- :meth:`teardown` drops references (the shared session is owned by the
  lifespan).

This is the codebase's first content-relevance filter: every prior filter
(proposal ``should_notify``, feed/changelog water marks) is state-driven or
deterministic and never reads content semantically.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any, TypeVar

import aiohttp
from pydantic import BaseModel, Field

from progress.cli.ai import build_model_string, get_agent, run_extraction
from progress.cli.notifications.events import NotificationEvent
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
from progress.integrations.registry import register
from progress.integrations.v2ex.client import (
    V2EX_REQUEST_MAX_DELAY,
    V2EX_REQUEST_MIN_DELAY,
    V2exClient,
)
from progress.integrations.v2ex.config import V2exIntegrationConfig, tab_display
from progress.integrations.v2ex.fetcher import (
    ClassifiedPost,
    filter_new_topics,
    max_topic_id,
    select_top_k,
    source_key,
)
from progress.integrations.v2ex.models import V2exTracker
from progress.integrations.v2ex.parser import RawTopic, parse_tab_page
from progress.observability import observe_span, record_business_event
from progress.utils.markdown import downgrade_headings
from progress.utils.timezone import now_utc

if TYPE_CHECKING:
    from progress.cli.reports.pipeline import IntegrationReport

logger = logging.getLogger(__name__)

#: Max characters of a topic body fed to the summarize AI (spec v2ex §7.1).
#: The topic's gist lives in its opening; truncation bounds context + cost.
V2EX_SUMMARY_BODY_LIMIT: int = 4000

#: Max topics per classify AI call (spec v2ex §7.1 batch-sharding extension).
#: The classify batch is sharded so each call's *output* stays small. A reasoning
#: model reasoning over ~100 topics at once produces a multi-minute generation,
#: and upstream gateways intermittently drop/garble such long streams (returning a
#: truncated body that fails to parse). ~20 keeps every generation well under the
#: instability threshold while bounding the call count (≤5 for 100 topics). The
#: merge key stays ``topic_id`` (never the per-batch ``post_index``), and any
#: shard failure fails the whole round so the water mark is not advanced over
#: unclassified topics (spec v2ex §4 invariant).
V2EX_CLASSIFY_BATCH_SIZE: int = 20

T = TypeVar("T", bound=BaseModel)


class V2exPostClassification(BaseModel):
    """AI verdict for one topic in the classify batch (spec v2ex §6)."""

    post_index: int
    interested: bool = False
    score: int = Field(default=0, ge=0, le=10)
    reason: str = ""


class V2exClassificationResult(BaseModel):
    """AI output for the classify call: one entry per input topic."""

    posts: list[V2exPostClassification] = []


class V2exPostSummary(BaseModel):
    """AI takeaway for one topic in the summarize batch (spec v2ex §7)."""

    post_index: int
    takeaway: str = ""


class V2exSummaryResult(BaseModel):
    """AI output for the summarize call: one entry per input topic."""

    posts: list[V2exPostSummary] = []


@register("v2ex")
class V2exIntegration:
    """Track V2EX tabs: scrape → AI interest-filter → summarize → report."""

    name = "v2ex"
    config_schema = V2exIntegrationConfig
    models_module = "progress.integrations.v2ex.models"

    def __init__(self) -> None:
        self._ctx: Components | None = None
        self._cfg: CoreConfig | None = None
        self._plugin_cfg: V2exIntegrationConfig = V2exIntegrationConfig()
        self._client: V2exClient | None = None

    async def setup(self, ctx: Components) -> None:
        self._ctx = ctx
        self._cfg = ctx.cfg
        self._plugin_cfg = await self._load_plugin_config()
        base_url = self._plugin_cfg.base_url.strip()
        profile = self._plugin_cfg.interest_profile.strip()
        analysis = self._cfg.analysis if self._cfg else AnalysisConfig()
        if not base_url:
            logger.warning("v2ex integration disabled: base_url empty")
            self._client = None
            return
        if not profile:
            logger.warning("v2ex integration disabled: interest_profile empty")
            self._client = None
            return
        if not isinstance(ctx.session, aiohttp.ClientSession):
            logger.warning("v2ex integration disabled: no shared aiohttp session")
            self._client = None
            return
        if not build_model_string(analysis):
            logger.warning("v2ex integration disabled: AI not configured ([core.analysis])")
            self._client = None
            return
        proxy = (self._cfg.github.proxy if self._cfg else None) or None
        self._client = V2exClient(ctx.session, base_url, proxy)
        logger.info(
            "v2ex integration enabled: tabs=%s base_url=%s proxy=%s",
            self._plugin_cfg.tabs,
            base_url,
            "on" if proxy else "off",
        )

    async def sync(self) -> SyncResult:
        result = SyncResult()
        desired = {source_key(tab) for tab in self._plugin_cfg.tabs}
        existing = {row.source: row async for row in V2exTracker.all()}

        for tab in self._plugin_cfg.tabs:
            src = source_key(tab)
            if src not in existing:
                await V2exTracker.create(source=src)
                result.created += 1
                logger.info("v2ex sync: created tracker for %s", src)
        for src, row in existing.items():
            if src not in desired:
                await row.delete()
                result.deleted += 1
                logger.info("v2ex sync: removed tracker for %s (no longer configured)", src)

        record_business_event(
            "progress.v2ex.sync",
            attributes={"created": str(result.created), "deleted": str(result.deleted)},
        )
        return result

    async def run(self, *, concurrency: int = 1) -> RunResult:
        del concurrency  # v2ex scrapes serially with jitter; concurrency is intentionally ignored
        result = RunResult(name="v2ex")
        client = self._client
        if client is None:
            logger.warning("v2ex integration disabled: not configured")
            return result
        analysis = self._cfg.analysis if self._cfg else AnalysisConfig()
        base_url = self._plugin_cfg.base_url

        new_by_source: dict[str, list[RawTopic]] = {}
        for tab in self._plugin_cfg.tabs:
            src = source_key(tab)
            try:
                html = await client.fetch_tab(tab)
            except (ExternalServiceException, ProgressException) as e:
                if self._is_forbidden(e):
                    logger.error("v2ex fetch forbidden for tab %s (possible ban): %s", tab, e)
                else:
                    logger.warning("v2ex fetch failed for tab %s: %s", tab, e)
                result.errors.append(e)
                continue
            topics = parse_tab_page(html, source=src, base_url=base_url)
            water_mark = await self._load_water_mark(src)
            new_by_source[src] = filter_new_topics(topics, last_topic_id=water_mark)
            logger.info(
                "v2ex tab %s: parsed %d topics, %d new after dedup (water_mark=%s)",
                tab,
                len(topics),
                len(new_by_source[src]),
                water_mark,
            )

        all_new = [topic for topics in new_by_source.values() for topic in topics]
        if not all_new:
            logger.info("v2ex: no new topics across %d source(s); skipping AI", len(new_by_source))
            await self._stamp_check_times(new_by_source)
            self._finalize_status(result)
            return result

        n_batches = max(1, (len(all_new) + V2EX_CLASSIFY_BATCH_SIZE - 1) // V2EX_CLASSIFY_BATCH_SIZE)
        logger.info(
            "v2ex: classifying %d new topic(s) across %d source(s) in %d batch(es) of <= %d",
            len(all_new),
            len(new_by_source),
            n_batches,
            V2EX_CLASSIFY_BATCH_SIZE,
        )
        classification = await self._classify(all_new, self._plugin_cfg.interest_profile, analysis)
        if classification is None:
            # Classify failed (AI error / unconfigured) → skip this round and do
            # NOT advance water marks so the same batch is retried next run.
            result.errors.append(ProgressException("v2ex classify failed"))
            result.status = "partial"
            return result

        classified: list[ClassifiedPost] = []
        for topic in all_new:
            verdict = classification.get(topic.topic_id)
            classified.append(
                ClassifiedPost(
                    topic=topic,
                    interested=bool(verdict and verdict.interested),
                    score=int(verdict.score) if verdict else 0,
                    reason=verdict.reason if verdict else "(unclassified)",
                )
            )

        winners = select_top_k(classified, self._plugin_cfg.max_summaries)
        interested_count = sum(1 for c in classified if c.interested)
        logger.info(
            "v2ex: %d/%d topic(s) interested; selected top-%d (cap=%d)",
            interested_count,
            len(classified),
            len(winners),
            self._plugin_cfg.max_summaries,
        )
        bodies: dict[int, str] = {}
        if winners:
            logger.info("v2ex: fetching %d topic body(ies) serially with jitter", len(winners))
        for winner in winners:
            await asyncio.sleep(random.uniform(V2EX_REQUEST_MIN_DELAY, V2EX_REQUEST_MAX_DELAY))
            try:
                bodies[winner.topic.topic_id] = await client.fetch_topic_body(winner.topic.topic_id)
                logger.info("v2ex: fetched topic body %d", winner.topic.topic_id)
            except (ExternalServiceException, ProgressException) as e:
                result.errors.append(e)
                logger.warning("v2ex: body fetch failed for topic %d: %s", winner.topic.topic_id, e)

        summarize_input = [w for w in winners if w.topic.topic_id in bodies]
        if summarize_input:
            logger.info("v2ex: summarizing %d topic body(ies)", len(summarize_input))
        takeaways = await self._summarize(summarize_input, bodies, analysis)
        for winner in winners:
            winner.takeaway = takeaways.get(winner.topic.topic_id) or winner.reason

        winners_by_source: dict[str, list[ClassifiedPost]] = {}
        for winner in winners:
            winners_by_source.setdefault(winner.topic.source, []).append(winner)
        for tab in self._plugin_cfg.tabs:
            src = source_key(tab)
            section_winners = winners_by_source.get(src, [])
            if not section_winners:
                continue
            result.reports.append(self._build_section(tab, section_winners, new_by_source.get(src, [])))

        await self._advance_water_marks(new_by_source)
        await self._stamp_check_times(new_by_source)

        if result.reports:
            digest_attrs: dict[str, str] = {}
            for src, topics in new_by_source.items():
                digest_attrs[f"{src}.new"] = str(len(topics))
            for src, section_winners in winners_by_source.items():
                digest_attrs[f"{src}.selected"] = str(len(section_winners))
            record_business_event(
                "progress.v2ex.digest",
                value=float(len(winners)),
                attributes=digest_attrs,
            )
        self._finalize_status(result)
        return result

    async def build_notification(
        self,
        *,
        result: RunResult,
        reports: list[IntegrationReport],
    ) -> list[NotificationEvent]:
        if not reports:
            return []
        groups: list[dict[str, Any]] = []
        selected_count = 0
        for section in result.reports:
            posts = section.payload.get("posts") or []
            if not posts:
                continue
            selected_count += len(posts)
            groups.append(
                {
                    "tab_title": section.payload.get("tab_title") or "",
                    "icon": section.payload.get("tab_icon") or "",
                    "posts": [
                        {
                            "title": p["title"],
                            "url": p["url"],
                            "score": p["score"],
                            "takeaway": p["takeaway"],
                        }
                        for p in posts
                    ],
                }
            )
        if not groups:
            return []
        integration_report = reports[0]
        return [
            NotificationEvent(
                kind="v2ex",
                title=integration_report.title,
                summary=integration_report.summary,
                markpost_url=integration_report.markpost_url,
                batch_index=integration_report.batch_index,
                total_batches=integration_report.total_batches,
                data={"groups": groups, "selected_count": selected_count},
            )
        ]

    async def teardown(self) -> None:
        self._client = None
        self._ctx = None
        self._cfg = None

    async def _classify(
        self,
        topics: list[RawTopic],
        profile: str,
        cfg: AnalysisConfig,
    ) -> dict[int, V2exPostClassification] | None:
        model_string = build_model_string(cfg)
        if not model_string:
            return None
        chunks = [topics[i : i + V2EX_CLASSIFY_BATCH_SIZE] for i in range(0, len(topics), V2EX_CLASSIFY_BATCH_SIZE)]
        mapping: dict[int, V2exPostClassification] = {}
        batch_no = 0
        try:
            async with observe_span(
                "v2ex.classify",
                attributes={
                    "topics": str(len(topics)),
                    "batches": str(len(chunks)),
                    "model": model_string or "",
                },
            ):
                for batch_no, chunk in enumerate(chunks, start=1):
                    prompt = render_prompt(
                        "v2ex_classify_prompt.j2",
                        interest_profile=profile,
                        posts=[
                            {
                                "index": i,
                                "title": t.title,
                                "node": t.node_name,
                                "author": t.author,
                                "replies": t.replies,
                                "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            for i, t in enumerate(chunk)
                        ],
                        language=cfg.language,
                    )
                    raw = await self._invoke(prompt, V2exClassificationResult, cfg)
                    if raw is None:
                        return None
                    self._merge_classification(raw, chunk, mapping)
                    logger.info(
                        "v2ex: classified batch %d/%d (%d topics)",
                        batch_no,
                        len(chunks),
                        len(chunk),
                    )
        except Exception as e:
            logger.warning("v2ex classify failed (batch %d/%d): %s", batch_no, len(chunks), e)
            return None
        return mapping

    @staticmethod
    def _merge_classification(
        raw: V2exClassificationResult,
        chunk: list[RawTopic],
        mapping: dict[int, V2exPostClassification],
    ) -> None:
        """Fold one shard's AI verdicts into the global ``topic_id → verdict`` map.

        ``post_index`` is local to this shard (0-based over ``chunk``); the merge
        key is always ``topic_id`` so sharding is invisible to callers. A topic
        the AI omitted is recorded as unmatched and treated as not interested.
        """
        by_index = {p.post_index: p for p in raw.posts}
        for i, topic in enumerate(chunk):
            verdict = by_index.get(i)
            if verdict is None:
                record_business_event(
                    "progress.v2ex.post_unmatched",
                    attributes={"topic_id": str(topic.topic_id), "stage": "classify"},
                )
                mapping[topic.topic_id] = V2exPostClassification(
                    post_index=i, interested=False, score=0, reason="(unclassified)"
                )
            else:
                mapping[topic.topic_id] = verdict

    async def _summarize(
        self,
        winners: list[ClassifiedPost],
        bodies: dict[int, str],
        cfg: AnalysisConfig,
    ) -> dict[int, str]:
        if not winners:
            return {}
        model_string = build_model_string(cfg)
        prompt = render_prompt(
            "v2ex_summarize_prompt.j2",
            posts=[
                {
                    "index": i,
                    "title": w.topic.title,
                    "body": (bodies.get(w.topic.topic_id, "") or "")[:V2EX_SUMMARY_BODY_LIMIT],
                }
                for i, w in enumerate(winners)
            ],
            language=cfg.language,
        )
        try:
            async with observe_span(
                "v2ex.summarize",
                attributes={"posts": str(len(winners)), "model": model_string or ""},
            ):
                raw = await self._invoke(prompt, V2exSummaryResult, cfg)
        except Exception as e:
            logger.warning("v2ex summarize failed: %s", e)
            return {}
        if raw is None:
            return {}
        by_index = {p.post_index: p for p in raw.posts}
        out: dict[int, str] = {}
        for i, winner in enumerate(winners):
            summary = by_index.get(i)
            if summary is None:
                record_business_event(
                    "progress.v2ex.post_unmatched",
                    attributes={"topic_id": str(winner.topic.topic_id), "stage": "summarize"},
                )
            else:
                out[winner.topic.topic_id] = summary.takeaway
        return out

    async def _invoke(
        self,
        prompt: str,
        result_type: type[T],
        cfg: AnalysisConfig,
    ) -> T | None:
        model_string = build_model_string(cfg)
        if not model_string:
            return None
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        agent = get_agent(result_type, model=model_string, api_key=api_key, base_url=cfg.base_url or None)
        out = await run_extraction(agent, prompt)
        return out if isinstance(out, result_type) else result_type.model_validate(out)

    def _build_section(
        self,
        tab: str,
        winners: list[ClassifiedPost],
        new_topics: list[RawTopic],
    ) -> ReportSection:
        display, icon = tab_display(tab)
        ordered = sorted(winners, key=lambda p: (-p.score, -p.topic.replies, -p.topic.topic_id))
        posts_payload = [
            {
                "title": w.topic.title,
                "url": w.topic.url,
                "node": w.topic.node_name,
                "author": w.topic.author,
                "replies": w.topic.replies,
                "score": w.score,
                "reason": downgrade_headings(w.reason),
                "takeaway": downgrade_headings(w.takeaway),
                "created_at": w.topic.created_at.isoformat(),
            }
            for w in ordered
        ]
        return ReportSection(
            title=f"V2EX {display}",
            content="",
            payload={
                "tab": tab,
                "tab_title": display,
                "tab_icon": icon,
                "tab_url": f"{self._plugin_cfg.base_url}/?tab={tab}",
                "scanned": len(new_topics),
                "posts": posts_payload,
            },
        )

    async def _load_water_mark(self, source: str) -> int | None:
        row = await V2exTracker.get_or_none(source=source)
        return row.last_topic_id if row else None

    async def _advance_water_marks(self, new_by_source: dict[str, list[RawTopic]]) -> None:
        now = now_utc()
        for source, topics in new_by_source.items():
            peak = max_topic_id(topics)
            if peak is None:
                continue
            await V2exTracker.update_or_create(source=source, defaults={"last_topic_id": peak, "last_check_time": now})
            logger.info("v2ex: advanced water mark %s -> %d", source, peak)

    async def _stamp_check_times(self, new_by_source: dict[str, list[RawTopic]]) -> None:
        now = now_utc()
        for source, topics in new_by_source.items():
            if topics:
                continue
            await V2exTracker.update_or_create(source=source, defaults={"last_check_time": now})

    async def _load_plugin_config(self) -> V2exIntegrationConfig:
        raw = await get_config("v2ex")
        if not raw:
            return V2exIntegrationConfig()
        raw, _ = strip_unknown_config_keys(raw, V2exIntegrationConfig)
        try:
            return V2exIntegrationConfig.model_validate(raw)
        except Exception as e:
            logger.warning("invalid v2ex plugin config; using defaults: %s", e)
            return V2exIntegrationConfig()

    @staticmethod
    def _is_forbidden(error: Exception) -> bool:
        message = str(error)
        return "HTTP 403" in message

    @staticmethod
    def _finalize_status(result: RunResult) -> None:
        if result.errors and not result.reports:
            result.status = "failed"
        elif result.errors:
            result.status = "partial"


__all__ = [
    "V2EX_CLASSIFY_BATCH_SIZE",
    "V2EX_SUMMARY_BODY_LIMIT",
    "V2exClassificationResult",
    "V2exIntegration",
    "V2exPostClassification",
    "V2exPostSummary",
    "V2exSummaryResult",
]
