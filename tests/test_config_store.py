"""Tests for the database-backed application config store."""

import json

import pytest

from progress.config_store import (
    SECRET_MASK,
    ConfigVersionConflict,
    build_runtime_config,
    get_config_json_schema,
    import_app_config,
    load_app_config,
    mask_secrets,
    save_app_config,
    seed_app_config_if_needed,
)
from progress.db import close_db, create_tables, init_db
from progress.errors import ConfigException

SAMPLE = {
    "language": "en",
    "timezone": "UTC",
    "github": {"gh_token": "ghp_real_token", "protocol": "https"},
    "analysis": {"concurrency": 2},
    "notification": {
        "channels": [
            {"type": "feishu", "enabled": True, "webhook_url": "https://hook/secret"},
            {
                "type": "email",
                "enabled": True,
                "host": "smtp.example.com",
                "password": "pw",
                "recipient": ["a@example.com"],
            },
        ]
    },
    "markpost": {"enabled": False, "url": None},
}


@pytest.fixture
async def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("PROGRESS_DB_PATH", db_path)
    await init_db(db_path)
    await create_tables()
    yield db_path
    await close_db()


async def test_seed_is_idempotent(db):
    assert await seed_app_config_if_needed(SAMPLE) is True
    assert await seed_app_config_if_needed(SAMPLE) is False
    data, version = await load_app_config()  # ty: ignore[not-iterable]
    assert version == 1
    assert data["github"]["gh_token"] == "ghp_real_token"


async def test_seed_strips_infra(db):
    await seed_app_config_if_needed({**SAMPLE, "data_dir": "/x", "workspace_dir": "/y"})
    data, _ = await load_app_config()  # ty: ignore[not-iterable]
    assert "data_dir" not in data
    assert "workspace_dir" not in data


async def test_mask_secrets(db):
    await seed_app_config_if_needed(SAMPLE)
    masked = mask_secrets((await load_app_config())[0])  # ty: ignore[not-subscriptable]
    assert masked["github"]["gh_token"] == SECRET_MASK
    assert masked["notification"]["channels"][0]["webhook_url"] == SECRET_MASK
    assert masked["notification"]["channels"][1]["password"] == SECRET_MASK
    assert masked["markpost"]["url"] is None


async def test_save_increments_version(db):
    await seed_app_config_if_needed(SAMPLE)
    data, version = await save_app_config(
        {"language": "zh-hans", "github": {"gh_token": "ghp_real_token"}},
        expected_version=1,
    )
    assert version == 2
    assert data["language"] == "zh-hans"


async def test_save_optimistic_lock_conflict(db):
    await seed_app_config_if_needed(SAMPLE)
    await save_app_config(
        {"language": "zh-hans", "github": {"gh_token": "t"}},
        expected_version=1,
    )
    with pytest.raises(ConfigVersionConflict):
        await save_app_config(
            {"language": "en", "github": {"gh_token": "t"}},
            expected_version=1,
        )


async def test_save_preserves_masked_secrets(db):
    await seed_app_config_if_needed(SAMPLE)
    masked = mask_secrets((await load_app_config())[0])  # ty: ignore[not-subscriptable]
    data, _ = await save_app_config(masked, expected_version=1)
    assert data["github"]["gh_token"] == "ghp_real_token"
    assert data["notification"]["channels"][0]["webhook_url"] == "https://hook/secret"
    assert data["notification"]["channels"][1]["password"] == "pw"


async def test_save_rejects_invalid(db):
    await seed_app_config_if_needed(SAMPLE)
    with pytest.raises(ConfigException):
        await save_app_config({"github": {}}, expected_version=1)


async def test_build_runtime_config_merges_infra(db):
    await seed_app_config_if_needed(SAMPLE)
    data, _ = await load_app_config()  # ty: ignore[not-iterable]
    cfg = build_runtime_config(data, {"data_dir": "/data", "workspace_dir": "/ws"})
    assert cfg.language == "en"
    assert cfg.data_dir == "/data"
    assert cfg.workspace_dir == "/ws"
    assert cfg.github.gh_token == "ghp_real_token"
    assert cfg.analysis.concurrency == 2


def test_schema_excludes_infra_and_has_channels_oneof():
    schema = get_config_json_schema()
    assert "data_dir" not in schema["properties"]
    assert "workspace_dir" not in schema["properties"]
    assert "repos" not in schema["properties"]
    assert "owners" not in schema["properties"]
    assert "github" in schema["properties"]
    items = schema["$defs"]["NotificationConfig"]["properties"]["channels"]["items"]
    assert "oneOf" in items
    assert items["discriminator"]["propertyName"] == "type"
    assert schema["schemaVersion"] == 2


async def test_migrate_blob_schema_strips_inline_repos_and_owners(db):
    from progress.config_store import (
        APP_CONFIG_ID,
        CURRENT_SCHEMA_VERSION,
        migrate_blob_schema,
    )
    from progress.db.models import AppConfig

    await AppConfig.create(
        id=APP_CONFIG_ID,
        data=json.dumps(
            {
                "language": "en",
                "repos": [{"url": "vitejs/vite"}],
                "owners": [{"type": "user", "name": "torvalds"}],
            }
        ),
        version=1,
        schema_version=1,
    )

    await migrate_blob_schema()

    data, _ = await load_app_config()  # ty: ignore[not-iterable]
    assert "repos" not in data
    assert "owners" not in data
    assert data["language"] == "en"
    row = await AppConfig.filter(id=APP_CONFIG_ID).first()
    assert row is not None
    assert row.schema_version == CURRENT_SCHEMA_VERSION


async def test_migrate_blob_schema_is_idempotent(db):
    from progress.config_store import migrate_blob_schema

    await test_migrate_blob_schema_strips_inline_repos_and_owners(db)
    await migrate_blob_schema()
    data, _ = await load_app_config()  # ty: ignore[not-iterable]
    assert "repos" not in data


async def test_seed_lists_if_needed_seeds_empty_tables(db):
    from progress.config_store import _config_from_dict, seed_lists_if_needed
    from progress.contrib.repo.models import GitHubOwner
    from progress.db.models import Repository

    file_cfg = _config_from_dict(
        {
            "github": {"gh_token": "t"},
            "repos": [{"url": "vitejs/vite"}, {"url": "vue/core"}],
            "owners": [{"type": "user", "name": "torvalds"}],
        }
    )
    await seed_lists_if_needed(file_cfg)
    assert await Repository.all().count() == 2
    assert await GitHubOwner.all().count() == 1


async def test_seed_lists_if_needed_noop_when_populated(db):
    from progress.config_store import _config_from_dict, seed_lists_if_needed
    from progress.contrib.repo.models import GitHubOwner
    from progress.db.models import Repository

    await Repository.create(
        name="django/django", url="https://github.com/django/django.git", branch="main"
    )
    await GitHubOwner.create(owner_type="user", name="existing")

    file_cfg = _config_from_dict(
        {
            "github": {"gh_token": "t"},
            "repos": [{"url": "vitejs/vite"}],
            "owners": [{"type": "user", "name": "torvalds"}],
        }
    )
    await seed_lists_if_needed(file_cfg)
    urls = {r.url for r in await Repository.all()}
    assert urls == {"https://github.com/django/django.git"}
    assert {o.name for o in await GitHubOwner.all()} == {"existing"}


async def test_import_overwrites_and_bumps_version(db):
    await seed_app_config_if_needed(SAMPLE)
    version = await import_app_config({"language": "ja", "github": {"gh_token": "ghp_new"}})
    assert version == 2
    data, _ = await load_app_config()  # ty: ignore[not-iterable]
    assert data["language"] == "ja"
    assert data["github"]["gh_token"] == "ghp_new"
