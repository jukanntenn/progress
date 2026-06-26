"""Tests for the database-backed application config store."""

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
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("PROGRESS_DB_PATH", db_path)
    init_db(db_path)
    create_tables()
    yield db_path
    close_db()
    from progress import db as db_module

    if db_module.database is not None:
        db_module.database.close_all()


def test_seed_is_idempotent(db):
    assert seed_app_config_if_needed(SAMPLE) is True
    assert seed_app_config_if_needed(SAMPLE) is False
    data, version = load_app_config()
    assert version == 1
    assert data["github"]["gh_token"] == "ghp_real_token"


def test_seed_strips_infra(db):
    seed_app_config_if_needed({**SAMPLE, "data_dir": "/x", "workspace_dir": "/y"})
    data, _ = load_app_config()
    assert "data_dir" not in data
    assert "workspace_dir" not in data


def test_mask_secrets(db):
    seed_app_config_if_needed(SAMPLE)
    masked = mask_secrets(load_app_config()[0])
    assert masked["github"]["gh_token"] == SECRET_MASK
    assert masked["notification"]["channels"][0]["webhook_url"] == SECRET_MASK
    assert masked["notification"]["channels"][1]["password"] == SECRET_MASK
    assert masked["markpost"]["url"] is None


def test_save_increments_version(db):
    seed_app_config_if_needed(SAMPLE)
    data, version = save_app_config(
        {"language": "zh-hans", "github": {"gh_token": "ghp_real_token"}},
        expected_version=1,
    )
    assert version == 2
    assert data["language"] == "zh-hans"


def test_save_optimistic_lock_conflict(db):
    seed_app_config_if_needed(SAMPLE)
    save_app_config(
        {"language": "zh-hans", "github": {"gh_token": "t"}},
        expected_version=1,
    )
    with pytest.raises(ConfigVersionConflict):
        save_app_config(
            {"language": "en", "github": {"gh_token": "t"}},
            expected_version=1,
        )


def test_save_preserves_masked_secrets(db):
    seed_app_config_if_needed(SAMPLE)
    masked = mask_secrets(load_app_config()[0])
    data, _ = save_app_config(masked, expected_version=1)
    assert data["github"]["gh_token"] == "ghp_real_token"
    assert data["notification"]["channels"][0]["webhook_url"] == "https://hook/secret"
    assert data["notification"]["channels"][1]["password"] == "pw"


def test_save_rejects_invalid(db):
    seed_app_config_if_needed(SAMPLE)
    with pytest.raises(ConfigException):
        save_app_config({"github": {}}, expected_version=1)


def test_build_runtime_config_merges_infra(db):
    seed_app_config_if_needed(SAMPLE)
    data, _ = load_app_config()
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
    assert "github" in schema["properties"]
    items = schema["$defs"]["NotificationConfig"]["properties"]["channels"]["items"]
    assert "oneOf" in items
    assert items["discriminator"]["propertyName"] == "type"
    assert schema["schemaVersion"] == 1


def test_import_overwrites_and_bumps_version(db):
    seed_app_config_if_needed(SAMPLE)
    version = import_app_config({"language": "ja", "github": {"gh_token": "ghp_new"}})
    assert version == 2
    data, _ = load_app_config()
    assert data["language"] == "ja"
    assert data["github"]["gh_token"] == "ghp_new"
