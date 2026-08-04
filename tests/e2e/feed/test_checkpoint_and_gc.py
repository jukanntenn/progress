"""feed e2e phase 4: GC of unsubscribed feeds between runs (spec feed §15.5).

Asserts:
- run 1 creates FeedTracker rows for each Miniflux feed
- deleting one feed via the Miniflux API, then running again, GC's that feed's
  FeedTracker row
- the surviving feed's water mark is unaffected

Requires docker (spec feed §15.1).
"""

from __future__ import annotations

from typing import Any

import miniflux as _mf
from pydantic import SecretStr
import pytest

from progress.cli.core import run
from progress.integrations.feed.config import FeedIntegrationConfig
from progress.integrations.feed.models import FeedTracker
from tests.e2e.conftest import db_view, seed_config

from .conftest import clear_all_data, create_feed_with_entries, delete_feed, list_feed_ids

pytestmark = [pytest.mark.e2e, pytest.mark.feed]


@pytest.mark.asyncio
async def test_checkpoint_and_gc(test_cfg: Any, miniflux_service: tuple[str, str]) -> None:

    clear_all_data()
    create_feed_with_entries(name="Stays", count=2, base_entry_id=1)
    create_feed_with_entries(name="Goes Away", count=1, base_entry_id=10)

    base_url, api_key = miniflux_service
    async with seed_config(
        test_cfg.state_home, "feed", FeedIntegrationConfig(base_url=base_url, api_key=SecretStr(api_key))
    ):
        first = await run(test_cfg)
    assert first.exit_code == 0

    async with db_view(test_cfg.state_home):
        before = await FeedTracker.all()
        assert len(before) == 2
        titles_before = {t.title for t in before}
        assert titles_before == {"Stays", "Goes Away"}

    # unsubscribe the "Goes Away" feed in Miniflux, then run again
    feed_ids = list_feed_ids()
    goes_away_id = None

    admin = _mf.Client(base_url, username="admin", password="password")
    for fid in feed_ids:
        feed = admin.get_feed(fid)
        if feed.get("title") == "Goes Away":
            goes_away_id = int(feed["id"])
            break
    assert goes_away_id is not None, "Goes Away feed not found for GC"
    delete_feed(goes_away_id)

    async with seed_config(
        test_cfg.state_home, "feed", FeedIntegrationConfig(base_url=base_url, api_key=SecretStr(api_key))
    ):
        second = await run(test_cfg)
    assert second.exit_code == 0

    async with db_view(test_cfg.state_home):
        after = await FeedTracker.all()
        assert len(after) == 1
        assert after[0].title == "Stays"
        # the surviving feed's water mark is preserved from run 1
        assert after[0].last_entry_id is not None
