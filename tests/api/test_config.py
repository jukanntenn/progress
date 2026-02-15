import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
# Timezone setting
timezone = "UTC"

# Interface language
language = "en"

[github]
# GitHub token for authentication
gh_token = "test_token"

[web]
enabled = true
host = "0.0.0.0"
port = 5000
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PROGRESS_DB_PATH", str(tmp_path / "progress.db"))

    from progress.api import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_get_config_includes_comments(client: TestClient):
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["timezone"] == "UTC"
    assert isinstance(data["comments"], dict)


def test_save_config_missing_both_fields(client: TestClient):
    response = client.post(
        "/api/v1/config",
        content=json.dumps({"invalid": "data"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "Missing 'toml' or 'config' field" in data["error"]


def test_save_config_invalid_toml(client: TestClient):
    response = client.post(
        "/api/v1/config",
        json={"toml": 'timezone = "UTC"\n[invalid'},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "Invalid TOML syntax" in data["error"]


def test_save_config_preserves_comments(client: TestClient):
    toml_with_comments = """
# Timezone comment
timezone = "UTC"

# Language comment
language = "en"

[github]
# GitHub token comment
gh_token = "test_token"
"""

    response = client.post("/api/v1/config", json={"toml": toml_with_comments})
    assert response.status_code == 200
    assert response.json()["success"] is True

    get_response = client.get("/api/v1/config")
    data = get_response.json()
    assert "# Timezone comment" in data["toml"]
    assert "# Language comment" in data["toml"]
    assert "# GitHub token comment" in data["toml"]


def test_validate_config_invalid_toml(client: TestClient):
    response = client.post(
        "/api/v1/config/validate",
        json={"toml": "invalid [toml"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False


def test_validate_config_model_success(client: TestClient):
    response = client.post(
        "/api/v1/config/validate",
        json={
            "toml": """
timezone = "UTC"
language = "en"

[github]
gh_token = "test_token"
"""
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_validate_config_data_success(client: TestClient):
    response = client.post(
        "/api/v1/config/validate-data",
        json={
            "config": {
                "timezone": "UTC",
                "language": "en",
                "github": {"gh_token": "test_token"},
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_get_config_schema(client: TestClient):
    response = client.get("/api/v1/config/schema")
    assert response.status_code == 200
    data = response.json()
    assert "sections" in data
    assert len(data["sections"]) > 0
    section_ids = {s["id"] for s in data["sections"]}
    assert "general" in section_ids
    assert "github" in section_ids
    notification_section = next(s for s in data["sections"] if s["id"] == "notification")
    notification_field = next(
        f for f in notification_section["fields"] if f["path"] == "notification.channels"
    )
    assert notification_field["type"] == "discriminated_object_list"
    assert notification_field["discriminator"] == "type"
    assert "variants" in notification_field
    assert "email" in notification_field["variants"]


def test_save_config_data_updates_nested_fields(client: TestClient):
    response = client.post(
        "/api/v1/config",
        json={
            "config": {
                "web": {"port": 6000},
                "repos": [{"url": "owner/repo", "branch": "main", "enabled": True}],
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    get_response = client.get("/api/v1/config")
    assert get_response.status_code == 200
    data = get_response.json()["data"]
    assert data["web"]["port"] == 6000
    assert isinstance(data["repos"], list)
    assert data["repos"][0]["url"] == "owner/repo"


def test_get_timezones(client: TestClient):
    response = client.get("/api/v1/config/timezones")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "UTC" in data["timezones"]
    assert len(data["timezones"]) > 0
