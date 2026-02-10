from datetime import datetime

import pytest

from progress.config import OwnerConfig
from progress.db import close_db, create_tables, init_db
from progress.models import DiscoveredRepository, GitHubOwner
from progress.owner import OwnerManager


@pytest.fixture()
def temp_db(tmp_path):
    db_path = tmp_path / "progress_test.db"
    init_db(str(db_path))
    create_tables()
    try:
        yield
    finally:
        close_db()


def test_owner_manager_sync_owners_create_update_delete(temp_db):
    manager = OwnerManager(gh_token=None)

    result = manager.sync_owners(
        [OwnerConfig(type="organization", name="bytedance", enabled=True)]
    )
    assert result["created"] == 1
    assert GitHubOwner.select().count() == 1

    result = manager.sync_owners(
        [OwnerConfig(type="organization", name="bytedance", enabled=True)]
    )
    assert result["created"] == 0

    result = manager.sync_owners(
        [OwnerConfig(type="organization", name="bytedance", enabled=False)]
    )
    assert result["deleted"] == 1
    assert GitHubOwner.select().count() == 0


def test_owner_manager_sync_owners_removes_missing(temp_db):
    manager = OwnerManager(gh_token=None)
    manager.sync_owners([OwnerConfig(type="user", name="torvalds", enabled=True)])
    assert GitHubOwner.select().count() == 1

    result = manager.sync_owners([])
    assert result["deleted"] == 1
    assert GitHubOwner.select().count() == 0


def test_owner_manager_check_owner_first_check_returns_most_recent(temp_db, monkeypatch):
    manager = OwnerManager(gh_token=None)
    owner = GitHubOwner.create(owner_type="organization", name="acme", enabled=True)

    def fake_repo_list(owner_name, limit=100, source=True):
        assert owner_name == "acme"
        return [
            {
                "nameWithOwner": "acme/old",
                "description": "old",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            },
            {
                "nameWithOwner": "acme/new",
                "description": "new",
                "createdAt": "2024-02-01T00:00:00Z",
                "updatedAt": "2024-02-01T00:00:00Z",
            },
        ]

    def fake_get_readme(owner_name, repo_name):
        return "# Hello"

    monkeypatch.setattr(manager.github_client, "list_repos", fake_repo_list)
    monkeypatch.setattr(manager.github_client, "get_readme", fake_get_readme)

    new_repos = manager._check_owner(owner)
    assert len(new_repos) == 1
    assert new_repos[0]["repo_name"] == "new"
    assert DiscoveredRepository.select().count() == 1

    owner_refreshed = GitHubOwner.get_by_id(owner.id)
    assert owner_refreshed.last_tracked_repo is not None


def test_owner_manager_check_owner_subsequent_only_newer(temp_db, monkeypatch):
    manager = OwnerManager(gh_token=None)
    owner = GitHubOwner.create(
        owner_type="user",
        name="alice",
        enabled=True,
        last_tracked_repo=datetime.fromisoformat("2024-01-15T00:00:00+00:00"),
    )

    def fake_repo_list(owner_name, limit=100, source=True):
        return [
            {
                "nameWithOwner": "alice/older",
                "description": "older",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            },
            {
                "nameWithOwner": "alice/newer",
                "description": "newer",
                "createdAt": "2024-02-01T00:00:00Z",
                "updatedAt": "2024-02-01T00:00:00Z",
            },
        ]

    monkeypatch.setattr(manager.github_client, "list_repos", fake_repo_list)
    monkeypatch.setattr(manager.github_client, "get_readme", lambda *args, **kwargs: None)

    new_repos = manager._check_owner(owner)
    assert len(new_repos) == 1
    assert new_repos[0]["repo_name"] == "newer"
