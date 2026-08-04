"""feed e2e phase 3: multiple feeds in one run (spec feed §15.5).

Asserts:
- 3 feeds (3/2/2 entries) → commit_count=7
- 3 FeedTracker rows created, one per feed
- the report body contains all 3 feed titles
- each feed's water mark advances independently

Requires docker (spec feed §15.1).
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
async def test_multiple_feeds(test_cfg: Any, miniflux_service: tuple[str, str]) -> None:

    clear_all_data()
    create_feed_with_entries(name="Tech Blog", count=3, base_entry_id=1)
    create_feed_with_entries(name="News Feed", count=2, base_entry_id=50)
    create_feed_with_entries(name="Dev Blog", count=2, base_entry_id=80)

    base_url, api_key = miniflux_service
    async with seed_config(
        test_cfg.state_home, "feed", FeedIntegrationConfig(base_url=base_url, api_key=SecretStr(api_key))
    ):
        outcome = await run(test_cfg)

    assert outcome.exit_code == 0

    async with db_view(test_cfg.state_home):
        reports = await Report.filter(report_type="feed")
        assert len(reports) == 1
        report = reports[0]
        assert report.commit_count == 7  # 3 + 2 + 2
        for title in ("Tech Blog", "News Feed", "Dev Blog"):
            assert title in report.content

        trackers = await FeedTracker.all()
        assert len(trackers) == 3
        tracker_titles = {t.title for t in trackers}
        assert tracker_titles == {"Tech Blog", "News Feed", "Dev Blog"}
        for tracker in trackers:
            assert tracker.last_entry_id is not None
            assert tracker.last_check_time is not None
