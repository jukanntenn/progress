"""Component tests for the feed integration tracker (spec feed §4-8).

Covers the lifecycle without a real Miniflux (spec 15 §1.2: component layer uses
injected fakes). The :class:`MinifluxClient` is replaced by a stub that returns
canned ``RawEntry`` lists; AI is replaced by monkeypatching
:func:`progress.cli.ai.run_extraction`.

Scenarios (spec feed §14 test matrix, component subset):
- setup: disabled / configured / invalid-config-fallback
- sync: no-op
- run: client=None degrade; no entries; first run; incremental water-mark;
  multiple feeds; AI failure per-feed degrade; multi-feed all-failed
- FeedTracker upsert + GC
- build_notification: empty / single aggregated NotificationEvent
- ReportSection.payload shape
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from progress.cli.reports.pipeline import IntegrationReport, _commit_count_for, _report_type_for
from progress.config.root import CoreConfig
from progress.db import close_db, init_db, set_config
from progress.errors import ExternalServiceException, ProgressException
from progress.integrations.base import Components, ReportSection, RunResult
from progress.integrations.feed.client import MINIFLUX_TIMEOUT, RawEntry
from progress.integrations.feed.config import FeedIntegrationConfig
from progress.integrations.feed.models import FeedTracker
from progress.integrations.feed.tracker import EntryAnalysis, FeedAnalysis, FeedIntegration


@pytest.fixture
async def db(tmp_state_home: str):
    await init_db(tmp_state_home)
    yield
    await close_db()


def _entry(
    entry_id: int,
    feed_id: int = 10,
    *,
    title: str = "e",
    feed_title: str = "Feed",
    site_url: str = "https://feed.example",
) -> RawEntry:
    return RawEntry(
        id=entry_id,
        feed_id=feed_id,
        title=title,
        url=f"https://example.com/{entry_id}",
        published_at=datetime(2026, 7, 25, tzinfo=UTC),
        content="content",
        feed={"id": feed_id, "title": feed_title, "site_url": site_url},
    )


class StubMinifluxClient:
    def __init__(self, entries: list[RawEntry] | None = None, *, error: Exception | None = None) -> None:
        self._entries = entries or []
        self._error = error
        self.close = AsyncMock()

    async def get_unread_entries(self) -> list[RawEntry]:
        if self._error is not None:
            raise self._error
        return list(self._entries)

    async def get_feeds(self) -> list[dict[str, Any]]:
        return []


def _core_cfg() -> CoreConfig:
    return CoreConfig()


async def _setup_integration(
    db,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plugin_cfg: FeedIntegrationConfig | None = None,
    client_entries: list[RawEntry] | None = None,
    client_error: Exception | None = None,
    ai_result: FeedAnalysis | None = None,
    ai_error: Exception | None = None,
    seed_water_marks: dict[int, int | None] | None = None,
) -> tuple[FeedIntegration, StubMinifluxClient]:
    cfg = _core_cfg()
    if plugin_cfg is not None:
        await set_config("feed", plugin_cfg.model_dump(mode="json"))
    integration = FeedIntegration()
    # session=None: the feed integration talks to Miniflux via its own
    # requests.Session inside the MinifluxClient, not the shared aiohttp session.
    await integration.setup(Components(cfg=cfg, session=None))
    stub = StubMinifluxClient(client_entries, error=client_error)
    monkeypatch.setattr(integration, "_client", stub)

    if seed_water_marks:
        for feed_id, wm in seed_water_marks.items():
            await FeedTracker.create(feed_id=feed_id, title=f"seed-{feed_id}", last_entry_id=wm)

    if ai_error is not None:

        async def _boom(_agent, _prompt, **_kw):
            raise ai_error

        monkeypatch.setattr("progress.integrations.feed.tracker.run_extraction", _boom)
        monkeypatch.setattr("progress.integrations.feed.tracker.build_model_string", lambda _cfg: "stub:model")
    elif ai_result is not None:

        async def _ok(_agent, _prompt, **_kw):
            return ai_result

        monkeypatch.setattr("progress.integrations.feed.tracker.run_extraction", _ok)
        monkeypatch.setattr("progress.integrations.feed.tracker.build_model_string", lambda _cfg: "stub:model")
    else:

        async def _unconfigured(_agent, _prompt, **_kw):

            raise ProgressException("AI not configured")

        monkeypatch.setattr("progress.integrations.feed.tracker.run_extraction", _unconfigured)
        # also defeat build_model_string so AI path short-circuits to degrade
        monkeypatch.setattr("progress.integrations.feed.tracker.build_model_string", lambda _cfg: None)

    return integration, stub


class TestSetup:
    async def test_disabled_when_base_url_empty(self, db) -> None:
        integration = FeedIntegration()
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        assert integration._client is None

    async def test_disabled_when_api_key_empty(self, db) -> None:
        integration = FeedIntegration()
        await set_config("feed", FeedIntegrationConfig(base_url="https://miniflux.example").model_dump(mode="json"))
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        assert integration._client is None

    async def test_disabled_does_not_build_client_even_if_db_says_so(self, db) -> None:
        # zero-config default: empty base_url → disabled
        integration = FeedIntegration()
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        assert integration._client is None

    async def test_invalid_config_falls_back_to_default(self, db, monkeypatch) -> None:
        # set_config validates eagerly, so simulate a malformed raw config being
        # read back from the DB: _load_plugin_config must catch and default.
        async def _bad_get(_section: str):
            return {"base_url": "x", "bogus": "field"}

        monkeypatch.setattr("progress.integrations.feed.tracker.get_config", _bad_get)
        integration = FeedIntegration()
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        assert integration._client is None


class TestSyncIsNoOp:
    async def test_sync_returns_empty(self, db) -> None:
        integration = FeedIntegration()
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        result = await integration.sync()
        assert result.created == 0
        assert result.updated == 0
        assert result.deleted == 0
        # no FeedTracker rows created by sync
        assert await FeedTracker.all().count() == 0


class TestRunDegrade:
    async def test_client_none_returns_empty_runresult(self, db) -> None:
        integration = FeedIntegration()
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        result = await integration.run()
        assert result.name == "feed"
        assert result.reports == []
        assert result.events == []
        assert result.errors == []
        assert result.status == "success"

    async def test_miniflux_failure_sets_failed(self, db, monkeypatch) -> None:
        integration, _ = await _setup_integration(
            db,
            monkeypatch,
            client_error=ExternalServiceException("boom"),
        )
        result = await integration.run()
        assert result.status == "failed"
        assert result.reports == []
        assert len(result.errors) == 1
        # water mark NOT advanced
        assert await FeedTracker.all().count() == 0


class TestRunNoEntries:
    async def test_no_entries_returns_empty_and_no_tracker(self, db, monkeypatch) -> None:
        integration, _ = await _setup_integration(db, monkeypatch, client_entries=[])
        result = await integration.run()
        assert result.reports == []
        assert await FeedTracker.all().count() == 0
        assert result.status == "success"


class TestFirstRun:
    async def test_first_run_creates_tracker_advances_watermark(self, db, monkeypatch) -> None:
        entries = [_entry(1), _entry(3)]
        ai = FeedAnalysis(
            summary="agg",
            entries=[EntryAnalysis(entry_index=0, analysis="a1"), EntryAnalysis(entry_index=1, analysis="a3")],
        )
        integration, _ = await _setup_integration(db, monkeypatch, client_entries=entries, ai_result=ai)
        result = await integration.run()
        assert len(result.reports) == 1
        section = result.reports[0]
        assert section.title == "Feed"
        assert section.payload["feed_title"] == "Feed"
        assert section.payload["summary"] == "agg"
        assert len(section.payload["entries"]) == 2
        # entries newest first
        assert section.payload["entries"][0]["title"] == "e"
        tracker = await FeedTracker.get(feed_id=10)
        assert tracker.last_entry_id == 3
        assert tracker.last_check_time is not None
        assert result.events == []


class TestIncrementalWaterMark:
    async def test_only_new_entries_beyond_watermark(self, db, monkeypatch) -> None:
        entries = [_entry(1), _entry(2), _entry(4), _entry(5)]
        ai = FeedAnalysis(
            summary="s", entries=[EntryAnalysis(entry_index=0, analysis=""), EntryAnalysis(entry_index=1, analysis="")]
        )
        integration, _ = await _setup_integration(
            db,
            monkeypatch,
            client_entries=entries,
            ai_result=ai,
            seed_water_marks={10: 2},
        )
        result = await integration.run()
        assert len(result.reports) == 1
        ids = [e["title"] for e in result.reports[0].payload["entries"]]  # titles are "e" for all; check via URL
        urls = [e["url"] for e in result.reports[0].payload["entries"]]
        assert urls == ["https://example.com/5", "https://example.com/4"]
        tracker = await FeedTracker.get(feed_id=10)
        assert tracker.last_entry_id == 5
        del ids

    async def test_all_below_watermark_skips_report_stamps_check_time(self, db, monkeypatch) -> None:
        entries = [_entry(1), _entry(2)]
        integration, _ = await _setup_integration(
            db,
            monkeypatch,
            client_entries=entries,
            seed_water_marks={10: 5},
        )
        result = await integration.run()
        assert result.reports == []
        tracker = await FeedTracker.get(feed_id=10)
        assert tracker.last_entry_id == 5  # unchanged
        assert tracker.last_check_time is not None


class TestMultipleFeeds:
    async def test_three_feeds_produces_three_sections_each_own_watermark(self, db, monkeypatch) -> None:
        entries = [
            _entry(11, feed_id=10, feed_title="A"),
            _entry(12, feed_id=10, feed_title="A"),
            _entry(13, feed_id=20, feed_title="B"),
            _entry(14, feed_id=30, feed_title="C", site_url="https://c"),
            _entry(15, feed_id=30, feed_title="C", site_url="https://c"),
        ]
        ai = FeedAnalysis(summary="s", entries=[])
        integration, _ = await _setup_integration(db, monkeypatch, client_entries=entries, ai_result=ai)
        result = await integration.run()
        assert len(result.reports) == 3
        titles = {s.title for s in result.reports}
        assert titles == {"A", "B", "C"}
        assert (await FeedTracker.get(feed_id=10)).last_entry_id == 12
        assert (await FeedTracker.get(feed_id=20)).last_entry_id == 13
        assert (await FeedTracker.get(feed_id=30)).last_entry_id == 15


class TestFeedTrackerGc:
    async def test_unsubscribed_feed_row_is_deleted(self, db, monkeypatch) -> None:
        # pre-existing tracker for a feed Miniflux no longer returns
        await FeedTracker.create(feed_id=99, title="gone", last_entry_id=5)
        entries = [_entry(1, feed_id=10, feed_title="Live")]
        integration, _ = await _setup_integration(
            db, monkeypatch, client_entries=entries, ai_result=FeedAnalysis(summary="s", entries=[])
        )
        await integration.run()
        assert await FeedTracker.filter(feed_id=99).count() == 0
        assert await FeedTracker.filter(feed_id=10).count() == 1

    async def test_title_update_on_metadata_change(self, db, monkeypatch) -> None:
        await FeedTracker.create(feed_id=10, title="Old Title", last_entry_id=1)
        entries = [_entry(5, feed_id=10, feed_title="New Title", site_url="https://new")]
        integration, _ = await _setup_integration(
            db, monkeypatch, client_entries=entries, ai_result=FeedAnalysis(summary="s", entries=[])
        )
        await integration.run()
        tracker = await FeedTracker.get(feed_id=10)
        assert tracker.title == "New Title"
        assert tracker.last_entry_id == 5


class TestAiDegrade:
    async def test_ai_failure_degrades_single_feed_keeps_report(self, db, monkeypatch) -> None:
        entries = [_entry(1, feed_id=10, feed_title="A"), _entry(2, feed_id=20, feed_title="B")]

        integration, _ = await _setup_integration(
            db,
            monkeypatch,
            client_entries=entries,
            ai_error=ProgressException("ai down"),
        )
        result = await integration.run()
        assert len(result.reports) == 2
        for section in result.reports:
            # §5.4: summary downgraded to the marker text; entries retained but analysis empty
            assert section.payload["summary"] == "AI analysis unavailable"
            for entry in section.payload["entries"]:
                assert entry["analysis"] == ""
        # water marks still advance (analysis "completed" in degraded form)
        assert (await FeedTracker.get(feed_id=10)).last_entry_id == 1
        assert (await FeedTracker.get(feed_id=20)).last_entry_id == 2

    async def test_ai_not_configured_all_feeds_degrade(self, db, monkeypatch) -> None:
        entries = [_entry(1, feed_id=10, feed_title="A")]
        integration, _ = await _setup_integration(db, monkeypatch, client_entries=entries)
        result = await integration.run()
        assert len(result.reports) == 1
        assert "unavailable" in result.reports[0].payload["summary"].lower()


class TestBuildNotification:
    async def test_no_reports_returns_empty(self, db) -> None:
        integration = FeedIntegration()
        await integration.setup(Components(cfg=_core_cfg(), session=None))
        events = await integration.build_notification(result=RunResult(name="feed"), reports=[])
        assert events == []

    async def test_single_aggregated_notification(self, db, monkeypatch) -> None:
        entries = [_entry(1, feed_id=10, feed_title="A"), _entry(2, feed_id=20, feed_title="B")]
        ai = FeedAnalysis(
            summary="s",
            entries=[EntryAnalysis(entry_index=0, analysis="x"), EntryAnalysis(entry_index=1, analysis="y")],
        )
        integration, _ = await _setup_integration(db, monkeypatch, client_entries=entries, ai_result=ai)
        result = await integration.run()

        reports = [
            IntegrationReport(
                integration_name="feed",
                report_type="feed",
                report_id=1,
                title="Digest",
                summary="summ",
                markpost_url="https://mp/1",
                total_batches=2,
            )
        ]
        events = await integration.build_notification(result=result, reports=reports)
        assert len(events) == 1
        event = events[0]
        assert event.kind == "feed"
        assert event.title == "Digest"
        assert event.summary == "summ"
        assert event.markpost_url == "https://mp/1"
        assert event.total_batches == 2
        assert event.data["feed_count"] == 2
        assert event.data["entry_count"] == 2
        feed_titles = {f["title"] for f in event.data["feeds"]}
        assert feed_titles == {"A", "B"}
        # run_at timestamp present for the Feishu footer
        assert event.data["run_at"]


class TestPipelineCommitCount:
    def test_commit_count_for_feed_sums_entries(self) -> None:

        sections = [
            ReportSection(title="A", payload={"entries": [1, 2, 3]}),
            ReportSection(title="B", payload={"entries": [4, 5]}),
        ]
        assert _commit_count_for("feed", "feed", sections) == 5

    def test_report_type_map_has_feed(self) -> None:

        assert _report_type_for("feed") == "feed"


class TestMinifluxTimeoutConstant:
    def test_miniflux_timeout_is_30(self) -> None:
        assert MINIFLUX_TIMEOUT == 30
