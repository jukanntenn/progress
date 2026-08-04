"""Unit test for the migration watermark advance (spec fix-acceptance-run-issues Fix 4).

Covers:
- ``advance_owner_watermarks`` overwrites every owner's ``last_tracked_repo``
  with ``now_utc() - 3 days`` so the first post-migration run only discovers
  repos created in the last 3 days (not 4 months of backlog).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from scripts.migrate_from_legacy import advance_owner_watermarks
from tortoise import Tortoise

from progress.db.tortoise_config import build_tortoise_config
from progress.integrations.repo.models import GitHubOwner
from progress.utils.timezone import now_utc


@pytest.fixture
async def db():
    return


async def test_advance_owner_watermarks_sets_to_now_minus_3_days() -> None:
    db_url = "sqlite://:memory:?journal_mode=WAL&synchronous=NORMAL&busy_timeout=5000&foreign_keys=ON&cache_size=-64000"
    await Tortoise.init(
        config=build_tortoise_config(db_url),
        _enable_global_fallback=True,
    )
    try:
        await Tortoise.generate_schemas()
        old_watermark = datetime(2026, 3, 16, 3, 9, 13, tzinfo=UTC)
        await GitHubOwner.create(
            owner_type="organization",
            name="microsoft",
            enabled=True,
            last_tracked_repo=old_watermark,
        )
        await GitHubOwner.create(
            owner_type="organization",
            name="google",
            enabled=True,
            last_tracked_repo=old_watermark,
        )
        conn = Tortoise.get_connection("default")

        before = now_utc()
        await advance_owner_watermarks(conn, days=3)
        after = now_utc()

        rows = (await conn.execute_query("SELECT name, last_tracked_repo FROM github_owners"))[1]
        lower = before - timedelta(days=3)
        upper = after - timedelta(days=3) + timedelta(seconds=60)
        for row in rows:
            _name, value = row[0], row[1]
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            assert lower <= parsed <= upper
    finally:
        await Tortoise.close_connections()
