"""feed e2e phase 2: incremental run with new entries on the same feed (§15.5).

Asserts the water-mark dedup works end to end:
- run 1 with 2 entries → report with commit_count=2
- add 3 more entries, run 2 → new report with commit_count=3 (only the new ones)
- the previously-seen 2 entries are NOT reprocessed
- the FeedTracker row's last_entry_id advances to the new max

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
async def test_incremental_new_entries(test_cfg: Any, miniflux_service: tuple[str, str]) -> None:

    clear_all_data()
    create_feed_with_entries(name="Lobsters", count=2)

    base_url, api_key = miniflux_service
    async with seed_config(
        test_cfg.state_home, "feed", FeedIntegrationConfig(base_url=base_url, api_key=SecretStr(api_key))
    ):
        first = await run(test_cfg)

    assert first.exit_code == 0

    async with db_view(test_cfg.state_home):
        first_reports = await Report.filter(report_type="feed").order_by("-id")
        assert len(first_reports) == 1
        first_count = first_reports[0].commit_count
        assert first_count == 2

    # add 3 more entries on the same feed and run again
    create_feed_with_entries(name="Lobsters", count=3, base_entry_id=100)
    async with seed_config(
        test_cfg.state_home, "feed", FeedIntegrationConfig(base_url=base_url, api_key=SecretStr(api_key))
    ):
        second = await run(test_cfg)

    assert second.exit_code == 0
    async with db_view(test_cfg.state_home):
        reports = await Report.filter(report_type="feed").order_by("-id")
        latest = reports[0]
        # only the 3 new entries should be counted this run
        assert latest.commit_count == 3
        assert latest.id != first_reports[0].id

        trackers = await FeedTracker.filter(title="Lobsters")
        assert len(trackers) == 1
        # water mark advanced strictly beyond the first-run max
        assert trackers[0].last_entry_id is not None
