"""Tests for the startup config-data migration (spec 6.3).

Covers the two known production corruptions (bugsink list → object,
recipient ``[{}]`` → ``[]``), the stale repo-section keys (removed from the
``RepoIntegrationConfig`` model after the stale-reenabled feature was dropped),
combined-fix single-write behaviour, idempotency and the lifespan integration
order (acceptance #12/#13).
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.db import close_db, get_config, init_db, set_config
from progress.db.migrations._config_data import (
    _fix_core_bugsink,
    _fix_core_recipient,
    _fix_repo_deprecated_fields,
    migrate_config_data,
)
from progress.db.models.config import Config


@pytest.fixture(autouse=True)
async def _db(tmp_state_home: str):
    """Per-test fresh DB."""
    await init_db(tmp_state_home)
    yield
    await close_db()


async def _put_raw_core(tmp_state_home: str, data: dict[str, Any]) -> None:
    """Write a core row directly, bypassing validation (simulates legacy
    corruption that slipped past the old non-validating write path)."""
    await Config.update_or_create(section="core", defaults={"data": data})


class TestFixCoreBugsink:
    async def test_fixes_list_to_first_object(self, tmp_state_home: str) -> None:
        await _put_raw_core(
            tmp_state_home,
            {"github": {"gh_token": "tok"}, "observability": {"bugsink": [{"dsn": "dsn-1", "environment": "prod"}]}},
        )
        core = await get_config("core")
        assert _fix_core_bugsink(core) == 1
        assert core["observability"]["bugsink"] == {"dsn": "dsn-1", "environment": "prod"}
        assert core["github"]["gh_token"] == "tok"

    async def test_empty_list_becomes_empty_object(self, tmp_state_home: str) -> None:
        await _put_raw_core(tmp_state_home, {"observability": {"bugsink": []}})
        core = await get_config("core")
        assert _fix_core_bugsink(core) == 1
        assert core["observability"]["bugsink"] == {}

    async def test_healthy_object_untouched(self, tmp_state_home: str) -> None:
        await _put_raw_core(tmp_state_home, {"observability": {"bugsink": {"dsn": "x"}}})
        core = await get_config("core")
        assert _fix_core_bugsink(core) == 0
        assert core["observability"]["bugsink"] == {"dsn": "x"}

    async def test_missing_observability_untouched(self, tmp_state_home: str) -> None:
        await _put_raw_core(tmp_state_home, {"language": "en"})
        core = await get_config("core")
        assert _fix_core_bugsink(core) == 0


class TestFixCoreRecipient:
    async def test_filters_non_string_recipients(self, tmp_state_home: str) -> None:
        await _put_raw_core(
            tmp_state_home,
            {
                "notification": {
                    "channels": [
                        {
                            "type": "email",
                            "recipient": ["alice@example.com", {}],
                            "host": "smtp.x",
                        }
                    ]
                }
            },
        )
        core = await get_config("core")
        assert _fix_core_recipient(core) == 1
        ch = core["notification"]["channels"][0]
        assert ch["recipient"] == ["alice@example.com"]

    async def test_healthy_recipients_untouched(self, tmp_state_home: str) -> None:
        await _put_raw_core(
            tmp_state_home,
            {"notification": {"channels": [{"type": "email", "recipient": ["a@b.c"]}]}},
        )
        core = await get_config("core")
        assert _fix_core_recipient(core) == 0

    async def test_missing_channels_untouched(self, tmp_state_home: str) -> None:
        await _put_raw_core(tmp_state_home, {"language": "en"})
        core = await get_config("core")
        assert _fix_core_recipient(core) == 0


class TestFixRepoDeprecatedFields:
    async def test_strips_deprecated_top_level_keys(self, tmp_state_home: str) -> None:
        await Config.update_or_create(
            section="repo",
            defaults={
                "data": {
                    "repos": [],
                    "owners": [],
                    "first_run_lookback_commits": 3,
                    "max_incremental_lookback_releases": 3,
                    "max_reenabled_lookback_commits": 30,
                    "max_reenabled_lookback_releases": 3,
                    "reenabled_stale_days": 7,
                }
            },
        )
        assert await _fix_repo_deprecated_fields() == 3
        stored = await get_config("repo")
        assert "max_reenabled_lookback_commits" not in stored
        assert "max_reenabled_lookback_releases" not in stored
        assert "reenabled_stale_days" not in stored
        assert stored["first_run_lookback_commits"] == 3
        assert stored["max_incremental_lookback_releases"] == 3

    async def test_healthy_data_untouched(self, tmp_state_home: str) -> None:
        await set_config("repo", {"repos": [], "owners": []})
        assert await _fix_repo_deprecated_fields() == 0

    async def test_missing_repo_untouched(self, tmp_state_home: str) -> None:
        assert await _fix_repo_deprecated_fields() == 0


class TestMigrateConfigData:
    async def test_fixes_both_corruptions_in_one_write(self, tmp_state_home: str) -> None:
        """fn's production DB carries BOTH corruptions; they must be fixed in a
        single validated write (two sequential writes would each fail on the
        still-broken other half)."""
        await _put_raw_core(
            tmp_state_home,
            {
                "github": {"gh_token": "tok"},
                "observability": {"bugsink": [{"dsn": "dsn-1"}]},
                "notification": {
                    "channels": [
                        {
                            "type": "email",
                            "recipient": ["a@b.c", {}],
                            "host": "smtp.x",
                            "user": "u",
                            "password": "p",
                        }
                    ]
                },
            },
        )
        fixed = await migrate_config_data()
        assert fixed == 2
        stored = await get_config("core")
        assert stored["observability"]["bugsink"]["dsn"] == "dsn-1"
        assert stored["notification"]["channels"][0]["recipient"] == ["a@b.c"]
        assert stored["github"]["gh_token"] == "tok"
        assert stored["notification"]["channels"][0]["password"] == "p"

    async def test_idempotent_second_run_reports_zero(self, tmp_state_home: str) -> None:
        await _put_raw_core(
            tmp_state_home,
            {"observability": {"bugsink": [{"dsn": "d"}]}},
        )
        assert await migrate_config_data() == 1
        assert await migrate_config_data() == 0

    async def test_healthy_data_untouched(self, tmp_state_home: str) -> None:
        await set_config("core", {"language": "en"})
        assert await migrate_config_data() == 0
        stored = await get_config("core")
        assert stored["language"] == "en"

    async def test_fixes_repo_and_core_independently(self, tmp_state_home: str) -> None:
        await Config.update_or_create(
            section="repo",
            defaults={
                "data": {
                    "repos": [],
                    "owners": [],
                    "reenabled_stale_days": 7,
                }
            },
        )
        await _put_raw_core(
            tmp_state_home,
            {"observability": {"bugsink": [{"dsn": "dsn-1"}]}},
        )
        assert await migrate_config_data() == 2
        stored_repo = await get_config("repo")
        assert "reenabled_stale_days" not in stored_repo
        stored_core = await get_config("core")
        assert stored_core["observability"]["bugsink"]["dsn"] == "dsn-1"

    async def test_repo_fix_idempotent(self, tmp_state_home: str) -> None:
        await Config.update_or_create(
            section="repo",
            defaults={
                "data": {
                    "repos": [],
                    "owners": [],
                    "reenabled_stale_days": 7,
                }
            },
        )
        assert await migrate_config_data() == 1
        assert await migrate_config_data() == 0

    async def test_unfixable_corruption_does_not_block(self, tmp_state_home: str) -> None:
        """If the remaining data still fails validation, the migration logs and
        gives up (0) instead of crashing startup (spec 6.3.1 note)."""
        await _put_raw_core(
            tmp_state_home,
            {
                "observability": {"bugsink": [{"dsn": "d"}]},
                "github": {"gh_token": 123},
            },
        )
        fixed = await migrate_config_data()
        assert fixed == 0
        stored = await get_config("core")
        assert stored["github"]["gh_token"] == 123
