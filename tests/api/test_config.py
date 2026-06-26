"""Tests for the DB-backed config API routes."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
timezone = "UTC"
language = "en"

[github]
gh_token = "test_token"

[analysis]
concurrency = 2
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PROGRESS_DB_PATH", str(tmp_path / "progress.db"))

    from progress import db as db_module
    from progress.api import create_app
    from progress.db import close_db

    app = create_app()
    with TestClient(app) as client:
        yield client

    close_db()
    if db_module.database is not None:
        db_module.database.close_all()


def test_get_config_returns_data_and_version(client: TestClient):
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 1
    assert data["data"]["timezone"] == "UTC"
    assert data["data"]["github"]["gh_token"] == "********"


def test_get_config_schema_is_json_schema(client: TestClient):
    response = client.get("/api/v1/config/schema")
    assert response.status_code == 200
    schema = response.json()
    assert schema["type"] == "object"
    assert "github" in schema["properties"]
    assert "data_dir" not in schema["properties"]
    items = schema["$defs"]["NotificationConfig"]["properties"]["channels"]["items"]
    assert "oneOf" in items
    assert items["discriminator"]["propertyName"] == "type"


def test_save_config_increments_version(client: TestClient):
    current = client.get("/api/v1/config").json()
    response = client.post(
        "/api/v1/config",
        json={
            "config": {
                "language": "zh-hans",
                "github": {"gh_token": "test_token"},
                "analysis": {"concurrency": 4},
            },
            "version": current["version"],
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["version"] == current["version"] + 1
    assert saved["data"]["analysis"]["concurrency"] == 4

    refreshed = client.get("/api/v1/config").json()
    assert refreshed["data"]["language"] == "zh-hans"


def test_save_config_optimistic_lock_conflict(client: TestClient):
    response = client.post(
        "/api/v1/config",
        json={
            "config": {"language": "en", "github": {"gh_token": "test_token"}},
            "version": 999,
        },
    )
    assert response.status_code == 409


def test_save_config_validation_error(client: TestClient):
    response = client.post(
        "/api/v1/config",
        json={"config": {"github": {}}, "version": 1},
    )
    assert response.status_code == 400


def test_save_config_preserves_masked_secret(client: TestClient):
    current = client.get("/api/v1/config").json()
    data = current["data"]
    assert data["github"]["gh_token"] == "********"
    response = client.post(
        "/api/v1/config",
        json={"config": data, "version": current["version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["github"]["gh_token"] == "********"


def test_validate_config_success(client: TestClient):
    response = client.post(
        "/api/v1/config/validate",
        json={"config": {"github": {"gh_token": "t"}}},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_validate_config_failure(client: TestClient):
    response = client.post(
        "/api/v1/config/validate",
        json={"config": {"github": {}}},
    )
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_get_timezones(client: TestClient):
    response = client.get("/api/v1/config/timezones")
    assert response.status_code == 200
    data = response.json()
    assert "UTC" in data["timezones"]
