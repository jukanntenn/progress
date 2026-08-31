"""Feed integration business logic (spec 06 / spec feed).

The tracker owns the five lifecycle hooks. Per spec feed:

- :meth:`setup` reads ``FeedIntegrationConfig`` from the DB config table and
  builds a :class:`MinifluxClient` when ``base_url`` + ``api_key`` are both
  non-empty; otherwise it degrades (``self._client = None``).
- :meth:`sync` is a no-op (spec feed §4.1): which feeds to track is decided by
  Miniflux, not by config. :class:`FeedTracker` rows are created / updated /
  GC'd inside :meth:`run`.
- :meth:`run` pulls unread entries, filters by per-feed water mark, runs a
  per-feed AI analysis (degraded on failure), builds one
  :class:`~progress.integrations.base.ReportSection` per feed with new
  entries, advances the water marks, and returns the :class:`RunResult`.
- :meth:`build_notification` authors one aggregated ``feed``
  :class:`NotificationEvent` per run from the pipeline's
  :class:`IntegrationReport`.
- :meth:`teardown` drops the client reference (the shared aiohttp session is
  owned by the lifespan).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

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
from progress.integrations.feed.client import MinifluxClient, RawEntry
from progress.integrations.feed.config import FeedIntegrationConfig
from progress.integrations.feed.fetcher import (
    Feed,
    filter_new_entries,
    first_entry_meta,
    format_published_at,
    max_entry_id,
)
from progress.integrations.feed.models import FeedTracker
from progress.integrations.registry import register
from progress.observability import record_business_event, report_severe
from progress.utils.i18n import gettext as _
from progress.utils.markdown import downgrade_headings
from progress.utils.timezone import now_utc

if TYPE_CHECKING:
    from progress.cli.reports.pipeline import IntegrationReport

logger = logging.getLogger(__name__)


class EntryAnalysis(BaseModel):
    """AI analysis for a single entry (spec feed §6.2)."""

    entry_index: int
    analysis: str


class FeedAnalysis(BaseModel):
    """AI analysis for one feed: feed-level summary + per-entry analysis.

    Used as the Pydantic AI agent's output type (spec feed §6.2).
    """

    summary: str
    entries: list[EntryAnalysis] = []


@register("feed")
class FeedIntegration:
    """Track RSS feeds via Miniflux unread entries + per-feed AI analysis."""

    name = "feed"
    config_schema = FeedIntegrationConfig
    models_module = "progress.integrations.feed.models"

    def __init__(self) -> None:
        self._ctx: Components | None = None
        self._cfg: CoreConfig | None = None
        self._client: MinifluxClient | None = None
        self._plugin_cfg: FeedIntegrationConfig = FeedIntegrationConfig()

    async def setup(self, ctx: Components) -> None:
        self._ctx = ctx
        self._cfg = ctx.cfg
        self._plugin_cfg = await self._load_plugin_config()
        base_url = self._plugin_cfg.base_url.strip()
        api_key = self._plugin_cfg.api_key.get_secret_value()
        if base_url and api_key:
            self._client = MinifluxClient(base_url, api_key)
        else:
            if base_url and not api_key:
                logger.warning("feed integration disabled: base_url set but api_key empty")
            self._client = None

    async def sync(self) -> SyncResult:
        return SyncResult()

    async def run(self, *, concurrency: int = 1) -> RunResult:
        del concurrency  # feed pulls all unread in one bulk call; effectively serial
        result = RunResult(name="feed")
        if self._client is None:
            logger.warning("feed integration disabled: client not configured")
            return result

        try:
            raw_entries = await self._client.get_unread_entries()
        except ExternalServiceException as e:
            logger.warning("feed integration: miniflux fetch failed: %s", e)
            report_severe(e)
            result.errors.append(e)
            result.status = "failed"
            return result
        except Exception as e:
            logger.exception("feed integration: unexpected error fetching entries")
            wrapped = ProgressException(f"feed fetch failed: {e}")
            result.errors.append(wrapped)
            result.status = "failed"
            return result

        water_marks = await self._load_water_marks(raw_entries)
        grouped = filter_new_entries(raw_entries, water_marks=water_marks)
        await self._maintain_trackers(grouped)

        active_feeds: list[Feed] = []
        for feed_id, entries in grouped.items():
            if not entries:
                continue
            try:
                title, site_url = await self._feed_display_meta(feed_id, entries)
            except ValueError:
                continue
            active_feeds.append(Feed(feed_id=feed_id, title=title, site_url=site_url, entries=entries))

        if not active_feeds:
            logger.info("feed integration: no new entries; skipping report")
            await self._stamp_check_times(grouped)
            return result

        for feed in active_feeds:
            section = await self._build_feed_section(feed)
            result.reports.append(section)

        await self._advance_water_marks(active_feeds)
        await self._stamp_check_times(grouped)

        if result.errors and not result.reports:
            result.status = "failed"
        elif result.errors:
            result.status = "partial"
        return result

    async def _build_feed_section(self, feed: Feed) -> ReportSection:
        analysis = await self._analyze_feed(feed)
        return ReportSection(
            title=feed.title,
            content="",
            payload={
                "feed_id": feed.feed_id,
                "feed_title": feed.title,
                "site_url": feed.site_url,
                "summary": downgrade_headings(analysis.summary),
                "entries": [
                    {
                        "title": e.title,
                        "url": e.url,
                        "published_at": format_published_at(e.published_at),
                        "analysis": downgrade_headings(_entry_analysis(analysis, e, idx)),
                    }
                    for idx, e in enumerate(feed.entries)
                ],
            },
        )

    async def _analyze_feed(self, feed: Feed) -> FeedAnalysis:
        cfg = self._cfg.analysis if self._cfg else AnalysisConfig()
        model_string = build_model_string(cfg)
        if not model_string:
            return _degraded_analysis(feed, reason=_("AI analysis unavailable"))
        prompt = render_prompt(
            "feed_analysis_prompt.j2",
            feed_title=feed.title,
            site_url=feed.site_url,
            entries=[
                {
                    "title": e.title,
                    "url": e.url,
                    "content": e.content,
                    "published_at": format_published_at(e.published_at),
                }
                for e in feed.entries
            ],
            language=cfg.language,
        )
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        agent = get_agent(FeedAnalysis, model=model_string, api_key=api_key, base_url=cfg.base_url or None)
        try:
            result = await run_extraction(agent, prompt)
        except (ProgressException, Exception) as e:
            logger.warning("feed AI analysis failed for %s: %s", feed.title, e)
            report_severe(e)
            return _degraded_analysis(feed, reason=_("AI analysis unavailable"))
        if isinstance(result, FeedAnalysis):
            return result
        try:
            return FeedAnalysis.model_validate(result)
        except Exception as e:
            logger.warning("feed AI analysis parse failed for %s: %s", feed.title, e)
            report_severe(e)
            return _degraded_analysis(feed, reason=_("AI analysis unavailable"))

    async def _maintain_trackers(self, grouped: dict[int, list[RawEntry]]) -> None:
        """Upsert FeedTracker metadata for every feed Miniflux returned (§4.2).

        GC happens via :meth:`_gc_trackers` after we know the live feed set.
        """
        now = now_utc()
        for feed_id, entries in grouped.items():
            try:
                title, site_url = await self._feed_display_meta(feed_id, entries, allow_empty=True)
            except ValueError:
                continue
            defaults = {"title": title, "last_check_time": now}
            if site_url:
                defaults["site_url"] = site_url
            tracker, created = await FeedTracker.update_or_create(
                feed_id=feed_id,
                defaults=defaults,
            )
            if created:
                logger.info("feed integration: tracking new feed %s (%s)", feed_id, title)
            del tracker
        await self._gc_trackers(set(grouped.keys()))

    async def _gc_trackers(self, live_feed_ids: set[int]) -> None:
        """Delete FeedTracker rows whose feed is no longer in Miniflux (§4.2)."""
        live_ids_param = list(live_feed_ids)
        existing = [t async for t in FeedTracker.all()]
        for tracker in existing:
            if tracker.feed_id not in live_ids_param:
                logger.info("feed integration: GC untracked feed %s (%s)", tracker.feed_id, tracker.title)
                await tracker.delete()

    async def _advance_water_marks(self, feeds: list[Feed]) -> None:
        now = now_utc()
        for feed in feeds:
            new_water_mark = max_entry_id(feed.entries)
            if new_water_mark is None:
                continue
            await FeedTracker.filter(feed_id=feed.feed_id).update(
                last_entry_id=new_water_mark,
                last_check_time=now,
            )

    async def _stamp_check_times(self, grouped: dict[int, list[RawEntry]]) -> None:
        now = now_utc()
        for feed_id, entries in grouped.items():
            if entries:
                continue
            await FeedTracker.filter(feed_id=feed_id).update(last_check_time=now)

    async def _load_water_marks(self, raw_entries: list[RawEntry]) -> dict[int, int | None]:
        feed_ids = {e.feed_id for e in raw_entries}
        if not feed_ids:
            return {}
        water_marks: dict[int, int | None] = {}
        async for tracker in FeedTracker.filter(feed_id__in=list(feed_ids)):
            water_marks[tracker.feed_id] = tracker.last_entry_id
        return water_marks

    async def _feed_display_meta(
        self,
        feed_id: int,
        entries: list[RawEntry],
        *,
        allow_empty: bool = False,
    ) -> tuple[str, str]:
        """Resolve ``(title, site_url)`` to display for a feed (§4.2 upsert).

        Miniflux's live metadata (carried on each entry's ``feed`` object) wins
        — the tracker row is the projection of Miniflux's current state, so a
        title change in Miniflux overwrites the stored value. When Miniflux
        gives us no entries for this feed we fall back to the stored tracker
        metadata (used only by the ``allow_empty`` maintenance path).
        """
        if entries:
            _, live_title, live_site_url = first_entry_meta(entries, fallback_title=f"feed-{feed_id}")
            return live_title, live_site_url
        tracker = await FeedTracker.filter(feed_id=feed_id).first()
        if tracker is not None and tracker.title:
            return tracker.title, tracker.site_url or ""
        if allow_empty:
            return f"feed-{feed_id}", ""
        raise ValueError(f"no metadata for unknown feed {feed_id}")

    async def _load_plugin_config(self) -> FeedIntegrationConfig:
        raw = await get_config("feed")
        if not raw:
            return FeedIntegrationConfig()

        raw, _ = strip_unknown_config_keys(raw, FeedIntegrationConfig)
        try:
            return FeedIntegrationConfig.model_validate(raw)
        except Exception as e:
            logger.warning("invalid feed plugin config; using defaults: %s", e)
            report_severe(e)
            return FeedIntegrationConfig()

    async def build_notification(
        self,
        *,
        result: RunResult,
        reports: list[IntegrationReport],
    ) -> list[NotificationEvent]:
        """Author the single aggregated ``feed`` notification (spec feed §8)."""
        if not reports:
            return []
        feeds_payload: list[dict[str, Any]] = []
        entry_count = 0
        for section in result.reports:
            entries = section.payload.get("entries") or []
            count = len(entries)
            entry_count += count
            feeds_payload.append(
                {
                    "title": section.payload.get("feed_title") or section.title,
                    "entry_count": count,
                    "url": section.payload.get("site_url") or "",
                }
            )
        if not feeds_payload:
            return []
        integration_report = reports[0]
        return [
            NotificationEvent(
                kind="feed",
                title=integration_report.title,
                summary=integration_report.summary,
                markpost_url=integration_report.markpost_url,
                batch_index=integration_report.batch_index,
                total_batches=integration_report.total_batches,
                data={
                    "feed_count": len(feeds_payload),
                    "entry_count": entry_count,
                    "feeds": feeds_payload,
                },
            )
        ]

    async def teardown(self) -> None:
        client = self._client
        self._client = None
        self._ctx = None
        self._cfg = None
        if client is not None:
            try:
                await client.close()
            except Exception as e:  # pragma: no cover - best-effort cleanup
                logger.debug("feed client close failed: %s", e)


def _entry_analysis(analysis: FeedAnalysis, entry: RawEntry, index: int) -> str:
    for item in analysis.entries:
        if item.entry_index == index:
            return item.analysis
    record_business_event(
        "progress.feed.entry_unmatched",
        attributes={"entry_index": str(index), "entry_id": str(entry.id)},
    )
    return ""


def _degraded_analysis(feed: Feed, *, reason: str) -> FeedAnalysis:
    return FeedAnalysis(
        summary=reason,
        entries=[EntryAnalysis(entry_index=idx, analysis="") for idx, _ in enumerate(feed.entries)],
    )


__all__ = ["EntryAnalysis", "FeedAnalysis", "FeedIntegration"]
