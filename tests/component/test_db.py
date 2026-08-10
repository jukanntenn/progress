"""Component tests for the DB layer (spec 03, 15).

Real SQLite tmp file (spec 15). Verifies:
- init_db creates schema via tortoise migrations
- config table CRUD via get_config / set_config / get_all_config
- Report + Batch CRUD
- Repository model CRUD via the repo integration's models
"""

from __future__ import annotations

import pytest
from tortoise.exceptions import IntegrityError

from progress.db import close_db, get_all_config, get_config, init_db, set_config
from progress.db.models.batch import Batch
from progress.db.models.config import Config
from progress.db.models.report import Report
from progress.errors import ConfigException
from progress.integrations.repo.models import GitHubOwner, Repository


@pytest.fixture(autouse=True)
async def _db(tmp_state_home: str):
    """Per-test fresh DB."""
    await init_db(tmp_state_home)
    yield
    await close_db()


class TestInitDb:
    async def test_init_creates_schema(self) -> None:
        # If we can query these tables without erroring, schema exists.
        assert await Report.all().count() == 0
        assert await Config.all().count() == 0
        assert await Repository.all().count() == 0
        assert await Batch.all().count() == 0

    async def test_init_idempotent(self, tmp_state_home: str) -> None:
        # Calling init_db again on the same DB should not error.
        await close_db()
        await init_db(tmp_state_home)
        assert await Report.all().count() == 0


class TestConfigCrud:
    async def test_get_missing_section_returns_empty(self) -> None:
        assert await get_config("nonexistent") == {}

    async def test_set_and_get(self) -> None:
        await set_config("core", {"language": "zh-hans"})
        out = await get_config("core")
        assert out["language"] == "zh-Hans"

    async def test_set_upserts(self) -> None:
        await set_config("core", {"language": "en"})
        await set_config("core", {"language": "zh-hans"})
        out = await get_config("core")
        assert out["language"] == "zh-Hans"
        assert await Config.all().count() == 1

    async def test_get_all(self) -> None:
        await set_config("core", {"language": "en"})
        await set_config("repo", {"repos": [{"url": "a/b"}]})
        out = await get_all_config()
        assert "core" in out
        assert "repo" in out
        assert out["core"]["language"] == "en"

    async def test_set_invalid_plugin_section_raises(self) -> None:

        # repo is a known section; passing invalid data should fail validation.
        with pytest.raises(ConfigException):
            await set_config("repo", {"repos": "not-a-list"})

    async def test_set_unknown_section_rejected(self) -> None:
        """Unknown sections have no Pydantic model; set_config rejects them."""
        with pytest.raises(ConfigException, match="unknown config section"):
            await set_config("unknown", {"key": "val"})

    async def test_mask_literal_stored_as_plain_value(self) -> None:
        """Plaintext design: there is no sentinel — a submitted '**********'
        is a literal string like any other and is stored verbatim."""
        await set_config("core", {"github": {"gh_token": "ghp_real_secret"}})
        await set_config(
            "core",
            {"github": {"gh_token": "**********"}, "language": "zh-hans"},
        )
        out = await get_config("core")
        assert out["github"]["gh_token"] == "**********"
        assert out["language"] == "zh-Hans"

    async def test_set_overwrites_when_real_value_submitted(self) -> None:
        await set_config("core", {"github": {"gh_token": "old"}})
        await set_config("core", {"github": {"gh_token": "new"}})
        assert (await get_config("core"))["github"]["gh_token"] == "new"

    async def test_plaintext_round_trip_in_list_of_dicts(self) -> None:
        """notification.channels secrets move with their channel object; no
        positional mask merging (acceptance #4/#5)."""
        await set_config(
            "core",
            {"notification": {"channels": [{"type": "email", "password": "real_pw"}]}},
        )
        await set_config(
            "core",
            {"notification": {"channels": [{"type": "email", "password": "**********"}]}},
        )
        out = await get_config("core")
        assert out["notification"]["channels"][0]["password"] == "**********"

    async def test_set_plugin_secret_not_masked(self) -> None:
        """A real SecretStr value must be stored as real plaintext."""
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "real_api_key_123"})
        out = await get_config("feed")
        assert out["api_key"] == "real_api_key_123"
        assert out["base_url"] == "http://localhost:18080"

    async def test_set_plugin_secret_plaintext_round_trip(self) -> None:
        """The value submitted is the value stored (no sentinel preservation)."""
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "real_api_key_123"})
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "**********"})
        out = await get_config("feed")
        assert out["api_key"] == "**********"

    async def test_plugin_secret_cleared_with_empty_string(self) -> None:
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "real"})
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": ""})
        out = await get_config("feed")
        assert out["api_key"] == ""

    async def test_set_list_shortening_takes_effect(self) -> None:
        # Removing list items must work (no masked-secret coupling here).
        await set_config(
            "core",
            {"notification": {"channels": [{"type": "console"}, {"type": "email"}]}},
        )
        await set_config(
            "core",
            {"notification": {"channels": [{"type": "console"}]}},
        )
        out = await get_config("core")
        assert len(out["notification"]["channels"]) == 1


class TestReportCrud:
    async def test_create_report(self) -> None:
        r = await Report.create(
            report_type="repo_update",
            title="t",
            commit_hash="abc123",
            commit_count=1,
            content="body",
        )
        assert r.id is not None
        fetched = await Report.get(id=r.id)
        assert fetched.title == "t"
        assert fetched.content == "body"

    async def test_report_default_report_type(self) -> None:
        r = await Report.create(title="t", commit_hash="h")
        assert r.report_type == "repo_update"

    async def test_batch_create(self) -> None:
        r = await Report.create(title="t", commit_hash="h")
        b = await Batch.create(report_id=r.id, seq=0, title="batch 1", markpost_url="https://x")
        assert b.id is not None
        fetched = await Batch.get(id=b.id)
        assert fetched.title == "batch 1"


class TestRepositoryModel:
    async def test_create(self) -> None:
        r = await Repository.create(url="a/b", branch="main", name="b")
        assert r.id is not None
        fetched = await Repository.get(id=r.id)
        assert fetched.url == "a/b"
        assert fetched.enabled is True
        assert fetched.last_commit_hash is None

    async def test_unique_url(self) -> None:
        await Repository.create(url="a/b", branch="main")
        with pytest.raises(IntegrityError):
            await Repository.create(url="a/b", branch="main")

    async def test_update_checkpoint(self) -> None:
        r = await Repository.create(url="a/b", branch="main")
        r.last_commit_hash = "deadbeef"
        await r.save()
        fetched = await Repository.get(id=r.id)
        assert fetched.last_commit_hash == "deadbeef"


class TestGitHubOwnerModel:
    async def test_create(self) -> None:
        o = await GitHubOwner.create(name="vitejs", owner_type="organization")
        assert o.id is not None
        fetched = await GitHubOwner.get(id=o.id)
        assert fetched.name == "vitejs"

    async def test_unique_together(self) -> None:
        await GitHubOwner.create(name="vitejs", owner_type="organization")
        with pytest.raises(IntegrityError):
            await GitHubOwner.create(name="vitejs", owner_type="organization")

    async def test_different_types_allowed(self) -> None:
        await GitHubOwner.create(name="vitejs", owner_type="organization")
        await GitHubOwner.create(name="vitejs", owner_type="user")
        assert await GitHubOwner.all().count() == 2


class TestInternalFieldPreservation:
    """set_config-level checks for _preserve_internal_fields behaviour."""

    async def test_core_internal_fields_preserved_across_writes(self) -> None:
        await set_config(
            "core",
            {"state_home": "/app/data", "auth": {"secret_key": "sk-1", "initial_admin_password": "pw-1"}},
        )
        await set_config("core", {"language": "zh-Hans"})
        out = await get_config("core")
        assert out["state_home"] == "/app/data"
        assert out["auth"]["secret_key"] == "sk-1"
        assert out["auth"]["initial_admin_password"] == "pw-1"
        assert out["language"] == "zh-Hans"

    async def test_first_boot_defaults_used(self) -> None:
        """No existing row → nothing injected; state_home falls back to the
        model default 'data' (spec 3.6.2 first-deploy boundary)."""
        await set_config("core", {"language": "zh-Hans"})
        out = await get_config("core")
        assert out["state_home"] == "data"

    async def test_normalized_dump_is_round_trip_stable(self) -> None:
        await set_config("core", {"language": "zh-Hans"})
        first = await get_config("core")
        await set_config("core", first)
        second = await get_config("core")
        assert first == second
