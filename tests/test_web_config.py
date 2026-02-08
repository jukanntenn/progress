"""Tests for configuration editor web routes."""

import json
import os

import pytest


@pytest.fixture
def app(tmp_path):
    """Create test app with temporary config file."""
    config_file = tmp_path / "test_config.toml"
    config_file.write_text(
        """
# Timezone setting
timezone = "UTC"

# Interface language
language = "en"

[markpost]
# Markpost API URL
url = "https://example.com/p/key"

[notification]
[[notification.channels]]
type = "feishu"
enabled = true
webhook_url = "https://example.com/hook"

[github]
# GitHub token for authentication
gh_token = "test_token"

[web]
enabled = true
host = "0.0.0.0"
port = 5000

[[repos]]
url = "test/repo"
branch = "main"
    """
    )

    from progress.web import create_app

    os.environ["CONFIG_FILE"] = str(config_file)

    app = create_app()
    app.config["TESTING"] = True

    yield app

    if "CONFIG_FILE" in os.environ:
        del os.environ["CONFIG_FILE"]


@pytest.fixture
def client(app):
    return app.test_client()


def test_config_page_get(client):
    """Test GET /config route."""
    response = client.get("/config")
    assert response.status_code == 200
    assert b"Configuration Editor" in response.data


def test_api_config_get(client):
    """Test GET /api/config route."""
    response = client.get("/api/config")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data["success"] is True
    assert "data" in data
    assert data["data"]["timezone"] == "UTC"
    assert "comments" in data


def test_api_config_get_includes_comments(client):
    """Test GET /api/config includes comments."""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "comments" in data
    assert isinstance(data["comments"], dict)


def test_api_config_post_valid(client):
    """Test POST /api/config with valid data."""
    new_toml = """
# Timezone
timezone = "Asia/Shanghai"

# Language
language = "zh-hans"

[markpost]
url = "https://example.com/p/key"

[notification]
[[notification.channels]]
type = "feishu"
enabled = true
webhook_url = "https://example.com/hook"

[github]
gh_token = "test_token"
    """

    response = client.post(
        "/api/config",
        data=json.dumps({"toml": new_toml}),
        content_type="application/json"
    )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True


def test_api_config_post_preserves_comments(client):
    """Test that saving config preserves comments."""
    toml_with_comments = """
# Timezone comment
timezone = "UTC"

# Language comment
language = "en"

[markpost]
url = "https://example.com/p/key"

[notification]
[[notification.channels]]
type = "feishu"
enabled = true
webhook_url = "https://example.com/hook"

[github]
# GitHub token comment
gh_token = "test_token"
    """

    response = client.post(
        "/api/config",
        data=json.dumps({"toml": toml_with_comments}),
        content_type="application/json"
    )

    assert response.status_code == 200

    get_response = client.get("/api/config")
    data = json.loads(get_response.data)
    assert "# Timezone comment" in data["toml"]
    assert "# Language comment" in data["toml"]
    assert "# GitHub token comment" in data["toml"]


def test_api_config_post_invalid(client):
    """Test POST /api/config with invalid TOML."""
    invalid_toml = """
timezone = "UTC"
[invalid
    """

    response = client.post(
        "/api/config",
        data=json.dumps({"toml": invalid_toml}),
        content_type="application/json"
    )

    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["success"] is False
    assert "error" in data


def test_api_config_post_with_config_field(client):
    """Test POST /api/config with config field (JSON)."""
    response = client.post(
        "/api/config",
        data=json.dumps({"config": {"timezone": "UTC", "language": "en"}}),
        content_type="application/json"
    )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True


def test_api_config_post_missing_both_fields(client):
    """Test POST /api/config without toml or config field."""
    response = client.post(
        "/api/config",
        data=json.dumps({"invalid": "data"}),
        content_type="application/json"
    )

    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["success"] is False
    assert "Missing 'toml' or 'config' field" in data["error"]


def test_api_config_validate_valid(client):
    """Test POST /api/config/validate with valid data."""
    valid_toml = """
timezone = "UTC"
language = "en"

[markpost]
url = "https://example.com/p/key"

[notification]
[[notification.channels]]
type = "feishu"
enabled = true
webhook_url = "https://example.com/hook"

[github]
gh_token = "test_token"
    """

    response = client.post(
        "/api/config/validate",
        data=json.dumps({"toml": valid_toml}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True


def test_api_config_validate_invalid(client):
    """Test POST /api/config/validate with invalid data."""
    invalid_toml = "invalid toml [[[["

    response = client.post(
        "/api/config/validate",
        data=json.dumps({"toml": invalid_toml}),
        content_type="application/json",
    )

    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["success"] is False


def test_api_config_schema(client):
    """Test GET /api/config/schema route."""
    response = client.get("/api/config/schema")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert "sections" in data
    assert isinstance(data["sections"], list)


def test_api_timezones(client):
    """Test GET /api/timezones route."""
    response = client.get("/api/timezones")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert isinstance(data, dict)
    assert data["success"] is True
    assert isinstance(data["timezones"], list)
    assert len(data["timezones"]) > 0
    assert "UTC" in data["timezones"]
    assert "America/New_York" in data["timezones"]
    assert "Asia/Shanghai" in data["timezones"]

def test_api_timezones_sorted(client):
    """Test that /api/timezones returns sorted timezones."""
    response = client.get("/api/timezones")
    assert response.status_code == 200

    data = json.loads(response.data)
    timezones = data["timezones"]
    assert timezones == sorted(timezones)
