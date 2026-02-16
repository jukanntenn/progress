import pytest
from fastapi.testclient import TestClient

from progress.db.models import Report


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
timezone = "UTC"
language = "en"

[github]
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


def test_list_reports_empty_db(client: TestClient):
    response = client.get("/api/v1/reports")
    assert response.status_code == 200
    data = response.json()
    assert data["reports"] == []
    assert data["page"] == 1
    assert data["total_pages"] == 1
    assert data["total"] == 0


def test_get_report_not_found(client: TestClient):
    response = client.get("/api/v1/reports/99999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"


def test_get_report_renders_markdown(client: TestClient):
    report = Report.create(
        title="Test Report",
        content="# Heading\n\n<details><summary>Click</summary>Content</details>",
        repo=None,
        commit_hash="test_commit",
    )

    response = client.get(f"/api/v1/reports/{report.id}")
    assert response.status_code == 200
    data = response.json()
    assert "<h1>Heading</h1>" in data["content"]
    assert "<details>" in data["content"]
    assert "<summary>Click</summary>" in data["content"]
