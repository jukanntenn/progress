"""feed e2e phase 1: first run with one feed + 2 unread entries (spec feed §15.5).

Asserts:
- one aggregated ``feed`` report is persisted (report_type="feed")
- ``commit_count`` equals the entry count (2)
- one FeedTracker row exists with last_entry_id set + last_check_time set
- the report body carries the feed's entries

AI is left unconfigured (spec feed §15.6): summaries degrade and we assert
structure/contract, not AI content. Requires docker (spec feed §15.1).
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr
import pytest

from progress.cli.core import run
from progress.db.models.report import Report
from progress.integrations.feed.config import FeedIntegrationConfig
from progress.integrations.feed.models import FeedTracker
from tests.e2e.conftest import db_view, seed_config

from .conftest import clear_all_data, create_feed_with_entries

pytestmark = [pytest.mark.e2e, pytest.mark.feed]


@pytest.mark.asyncio
async def test_first_run_single_feed(test_cfg: Any, miniflux_service: tuple[str, str]) -> None:

    clear_all_data()
    create_feed_with_entries(name="Hacker News", count=2)

    base_url, api_key = miniflux_service
    async with seed_config(
        test_cfg.state_home, "feed", FeedIntegrationConfig(base_url=base_url, api_key=SecretStr(api_key))
    ):
        outcome = await run(test_cfg)

    assert outcome.exit_code == 0
    assert outcome.results["feed"].status == "success"

    async with db_view(test_cfg.state_home):
        feed_reports = await Report.filter(report_type="feed")
        assert len(feed_reports) == 1
        report = feed_reports[0]
        assert report.commit_count == 2
        assert "Hacker News" in report.content

        trackers = await FeedTracker.all()
        assert len(trackers) == 1
        tracker = trackers[0]
        assert tracker.title == "Hacker News"
        assert tracker.last_entry_id is not None
        assert tracker.last_check_time is not None
