"""Component tests for the changelog integration (spec 06 / spec changelog, 15).

Uses pytest-httpserver to mock the upstream changelog fetch + real SQLite tmp
file for state. Verifies the full setup → sync → run → teardown lifecycle.

Per the new spec 06/09 architecture: integrations no longer write ``Report``
rows directly; they populate ``RunResult.reports`` and ``RunResult.events``.
The reports pipeline writes the ``Report`` rows from the sections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import pytest

from progress.cli.notifications.events import ChangelogEvent
from progress.db import close_db, init_db, set_config
from progress.integrations.base import Components
from progress.integrations.changelog.config import (
    ChangelogIntegrationConfig,
    ChangelogItemConfig,
)
from progress.integrations.changelog.models import ChangelogTracker
from progress.integrations.changelog.parsers import ChangelogVersion
from progress.integrations.changelog.tracker import (
    ChangelogIntegration,
    detect_new_entries,
)
from progress.utils.timezone import now_utc

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer

_MD_CHANGELOG = """# Changelog

## [2.0.0] - 2026-02-01

### Added

- New feature.

## [1.1.0] - 2025-12-01

### Fixed

- Bug.

## [1.0.0]

Initial.
"""


@pytest.fixture
async def db_and_session(tmp_state_home: str, httpserver: HTTPServer):
    await init_db(tmp_state_home)
    async with aiohttp.ClientSession() as session:
        yield session
    await close_db()


async def _setup_integration(
    session: aiohttp.ClientSession,
    plugin_cfg: ChangelogIntegrationConfig | None = None,
) -> ChangelogIntegration:
    integration = ChangelogIntegration()
    if plugin_cfg is not None:
        await set_config("changelog", plugin_cfg.model_dump(mode="json"))
    await integration.setup(Components(cfg=None, session=session))
    return integration


class TestSync:
    async def test_sync_creates_trackers(self, db_and_session: aiohttp.ClientSession) -> None:
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(
                    name="Vite",
                    url="https://example.com/vite.md",
                    parser_type="markdown_heading",
                ),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        result = await integration.sync()
        assert result.created == 1
        rows = await ChangelogTracker.all()
        assert len(rows) == 1
        assert rows[0].name == "Vite"
        assert rows[0].url == "https://example.com/vite.md"
        assert rows[0].last_seen_version is None

    async def test_sync_url_is_identity_key(self, db_and_session: aiohttp.ClientSession) -> None:
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url="https://a", parser_type="markdown_heading"),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()

        cfg2 = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite Renamed", url="https://b", parser_type="markdown_heading"),
            ]
        )
        await set_config("changelog", cfg2.model_dump(mode="json"))
        integration._plugin_cfg = cfg2
        result = await integration.sync()
        assert result.deleted == 1
        assert result.created == 1
        rows = await ChangelogTracker.all()
        assert len(rows) == 1
        assert rows[0].url == "https://b"

    async def test_sync_updates_existing_name_parser_enabled(self, db_and_session: aiohttp.ClientSession) -> None:
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url="https://a", parser_type="markdown_heading"),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        first = await ChangelogTracker.first()
        assert first is not None
        first.last_seen_version = "1.5.0"
        first.last_check_time = now_utc()
        await first.save()

        cfg2 = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite Renamed", url="https://a", parser_type="html_generic"),
            ]
        )
        await set_config("changelog", cfg2.model_dump(mode="json"))
        integration._plugin_cfg = cfg2
        result = await integration.sync()
        assert result.updated == 1
        row = await ChangelogTracker.first()
        assert row is not None
        assert row.name == "Vite Renamed"
        assert row.parser_type == "html_generic"
        assert row.last_seen_version == "1.5.0"

    async def test_sync_deletes_removed(self, db_and_session: aiohttp.ClientSession) -> None:
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url="https://a"),
                ChangelogItemConfig(name="Vue", url="https://b"),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        assert await ChangelogTracker.all().count() == 2

        cfg2 = ChangelogIntegrationConfig(trackers=[ChangelogItemConfig(name="Vite", url="https://a")])
        await set_config("changelog", cfg2.model_dump(mode="json"))
        integration._plugin_cfg = cfg2
        result = await integration.sync()
        assert result.deleted == 1
        assert await ChangelogTracker.all().count() == 1

    async def test_sync_keeps_disabled(self, db_and_session: aiohttp.ClientSession) -> None:
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url="https://a", enabled=False),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        result = await integration.sync()
        assert result.created == 1
        assert await ChangelogTracker.all().count() == 1


class TestRun:
    async def test_first_run_reports_only_latest_version(
        self, db_and_session: aiohttp.ClientSession, httpserver: HTTPServer
    ) -> None:
        httpserver.expect_request("/vite.md").respond_with_data(_MD_CHANGELOG)
        url = httpserver.url_for("/vite.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url=url, parser_type="markdown_heading"),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        result = await integration.run()
        assert result.status == "success"
        assert len(result.reports) == 1
        new_entries = result.reports[0].payload.get("new_entries", [])
        assert len(new_entries) == 1
        assert new_entries[0]["version"] == "2.0.0"
        assert len(result.events) == 1

        event = result.events[0]
        assert isinstance(event, ChangelogEvent)
        assert event.version == "2.0.0"

        rows = await ChangelogTracker.all()
        assert rows[0].last_seen_version == "2.0.0"

    async def test_run_advances_checkpoint(self, db_and_session: aiohttp.ClientSession, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/vite.md").respond_with_data(_MD_CHANGELOG)
        url = httpserver.url_for("/vite.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url=url, parser_type="markdown_heading"),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        await integration.run()

        result = await integration.run()
        assert result.status == "success"
        assert len(result.reports) == 0
        assert len(result.events) == 0

    async def test_run_partial_on_fetch_error(
        self, db_and_session: aiohttp.ClientSession, httpserver: HTTPServer
    ) -> None:
        httpserver.expect_request("/missing").respond_with_data("not found", status=404)
        url = httpserver.url_for("/missing")
        cfg = ChangelogIntegrationConfig(trackers=[ChangelogItemConfig(name="Vite", url=url)])
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        result = await integration.run()
        assert result.status in {"partial", "failed"}
        assert len(result.errors) >= 1

    async def test_run_partial_on_parse_error(
        self, db_and_session: aiohttp.ClientSession, httpserver: HTTPServer
    ) -> None:
        httpserver.expect_request("/empty").respond_with_data("# plain doc\nno versions here")
        url = httpserver.url_for("/empty")
        cfg = ChangelogIntegrationConfig(trackers=[ChangelogItemConfig(name="Vite", url=url)])
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        result = await integration.run()
        assert result.status in {"partial", "failed"}
        assert len(result.errors) >= 1

    async def test_run_skips_disabled_tracker(
        self, db_and_session: aiohttp.ClientSession, httpserver: HTTPServer
    ) -> None:
        httpserver.expect_request("/vite.md").respond_with_data(_MD_CHANGELOG)
        url = httpserver.url_for("/vite.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Vite", url=url, parser_type="markdown_heading", enabled=False),
            ]
        )
        integration = await _setup_integration(db_and_session, cfg)
        await integration.sync()
        result = await integration.run()
        assert result.status == "success"
        assert len(result.reports) == 0
        row = await ChangelogTracker.first()
        assert row is not None
        assert row.last_check_time is None


class TestDetectNewEntries:
    """Spec changelog §5.3 four-branch decision tree."""

    def _versions(self, *vers: str):

        return [ChangelogVersion(version=v, description="") for v in vers]

    def test_empty_list(self) -> None:
        new, warning = detect_new_entries([], None)
        assert new == []
        assert warning is None

    def test_first_run_returns_latest_only(self) -> None:
        versions = self._versions("3.0.0", "2.0.0", "1.0.0")
        new, warning = detect_new_entries(versions, None)
        assert [v.version for v in new] == ["3.0.0"]
        assert warning is None

    def test_hit_watermark_returns_newer_than_it(self) -> None:
        versions = self._versions("3.0.0", "2.5.0", "2.0.0", "1.0.0")
        new, warning = detect_new_entries(versions, "2.0.0")
        assert [v.version for v in new] == ["3.0.0", "2.5.0"]
        assert warning is None

    def test_miss_watermark_returns_latest_with_warning(self) -> None:
        versions = self._versions("3.0.0", "2.0.0")
        new, warning = detect_new_entries(versions, "9.9.9")
        assert [v.version for v in new] == ["3.0.0"]
        assert warning is not None
        assert "not found" in warning

    def test_no_new_versions_when_watermark_at_head(self) -> None:
        versions = self._versions("3.0.0", "2.0.0")
        new, warning = detect_new_entries(versions, "3.0.0")
        assert new == []
        assert warning is None


class TestTeardown:
    async def test_teardown_clears_state(self, db_and_session: aiohttp.ClientSession) -> None:
        integration = await _setup_integration(db_and_session)
        await integration.teardown()
        assert integration._ctx is None
        assert integration._cfg is None
