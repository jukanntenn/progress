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

from progress.db import _unmask_real_secrets, close_db, get_all_config, get_config, init_db, set_config
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
        assert out == {"language": "zh-hans"}

    async def test_set_upserts(self) -> None:
        await set_config("core", {"language": "en"})
        await set_config("core", {"language": "zh-hans"})
        out = await get_config("core")
        assert out == {"language": "zh-hans"}
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

    async def test_set_unknown_section_passes_through(self) -> None:
        # Unknown sections (no registered schema) are stored as-is.
        await set_config("unknown", {"key": "val"})
        out = await get_config("unknown")
        assert out == {"key": "val"}

    async def test_set_preserves_masked_secret(self) -> None:
        # Spec 02: a PUT that round-trips the SecretStr mask sentinel must
        # preserve the real stored value rather than overwriting it with the
        # literal mask string.
        await set_config("core", {"github": {"gh_token": "ghp_real_secret"}})
        await set_config(
            "core",
            {"github": {"gh_token": "**********"}, "language": "zh-hans"},
        )
        out = await get_config("core")
        assert out["github"]["gh_token"] == "ghp_real_secret"
        assert out["language"] == "zh-hans"

    async def test_set_overwrites_when_real_value_submitted(self) -> None:
        await set_config("core", {"github": {"gh_token": "old"}})
        await set_config("core", {"github": {"gh_token": "new"}})
        assert (await get_config("core"))["github"]["gh_token"] == "new"

    async def test_set_preserves_masked_secret_in_list_of_dicts(self) -> None:
        # Spec 02: ``notification.channels`` is a discriminated union list;
        # a channel that round-tripped its masked ``password`` must keep the
        # real one while non-secret edits still take effect.
        await set_config(
            "core",
            {"notification": {"channels": [{"type": "email", "password": "real_pw"}]}},
        )
        await set_config(
            "core",
            {"notification": {"channels": [{"type": "email", "password": "**********"}]}},
        )
        out = await get_config("core")
        assert out["notification"]["channels"][0]["password"] == "real_pw"

    async def test_set_plugin_secret_not_masked(self) -> None:
        """set_config with a real SecretStr value must store the real value, not the mask.

        _validate_section round-trips through model_validate + model_dump(mode='json')
        which masks SecretStr to '**********'. _unmask_real_secrets must restore it.
        """
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "real_api_key_123"})
        out = await get_config("feed")
        assert out["api_key"] == "real_api_key_123"
        assert out["base_url"] == "http://localhost:18080"

    async def test_set_plugin_secret_mask_preserved_from_db(self) -> None:
        """When the submitted value is the mask sentinel, the existing DB value is kept."""
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "real_api_key_123"})
        await set_config("feed", {"base_url": "http://localhost:18080", "api_key": "**********"})
        out = await get_config("feed")
        assert out["api_key"] == "real_api_key_123"

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


class TestUnmaskRealSecrets:
    """Pure-function tests for _unmask_real_secrets."""

    def test_replaces_masked_value_with_original(self) -> None:

        result = _unmask_real_secrets({"api_key": "**********"}, {"api_key": "real_key"})
        assert result == {"api_key": "real_key"}

    def test_preserves_non_masked_value(self) -> None:

        result = _unmask_real_secrets({"base_url": "http://x"}, {"base_url": "http://x"})
        assert result == {"base_url": "http://x"}

    def test_nested_dict_unmasked(self) -> None:

        validated = {"github": {"gh_token": "**********"}, "language": "en"}
        original = {"github": {"gh_token": "ghp_real"}, "language": "en"}
        result = _unmask_real_secrets(validated, original)
        assert result == {"github": {"gh_token": "ghp_real"}, "language": "en"}

    def test_masked_original_not_used(self) -> None:
        """If original is also masked, keep the validated (masked) value."""

        result = _unmask_real_secrets({"key": "**********"}, {"key": "********"})
        assert result == {"key": "**********"}

    def test_missing_original_keeps_validated(self) -> None:

        result = _unmask_real_secrets({"key": "**********"}, {})
        assert result == {"key": "**********"}

    def test_empty_dicts(self) -> None:

        assert _unmask_real_secrets({}, {}) == {}
