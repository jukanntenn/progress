from datetime import datetime

import pytest

from progress.contrib.repo.models import GitHubOwner
from progress.contrib.repo.owner import OwnerManager
from progress.db import close_db, create_tables, init_db


@pytest.fixture()
async def temp_db(tmp_path):
    db_path = tmp_path / "progress_test.db"
    await init_db(str(db_path))
    await create_tables()
    try:
        yield
    finally:
        await close_db()


async def test_owner_manager_check_owner_first_check_returns_most_recent(
    temp_db, monkeypatch
):
    manager = OwnerManager(gh_token=None)
    owner = await GitHubOwner.create(owner_type="organization", name="acme", enabled=True)

    async def fake_repo_list(owner_name, limit=100, source=True):
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

    async def fake_get_readme(owner_name, repo_name):
        return "# Hello"

    monkeypatch.setattr(manager.github_client, "list_repos", fake_repo_list)
    monkeypatch.setattr(manager.github_client, "get_readme", fake_get_readme)

    new_repos = await manager._check_owner(owner)
    assert len(new_repos) == 1
    assert new_repos[0]["repo_name"] == "new"

    owner_refreshed = await GitHubOwner.get(id=owner.id)
    assert owner_refreshed.last_tracked_repo is not None


async def test_owner_manager_check_owner_subsequent_only_newer(temp_db, monkeypatch):
    manager = OwnerManager(gh_token=None)
    owner = await GitHubOwner.create(
        owner_type="user",
        name="alice",
        enabled=True,
        last_tracked_repo=datetime.fromisoformat("2024-01-15T00:00:00+00:00"),
    )

    async def fake_repo_list(owner_name, limit=100, source=True):
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

    async def fake_get_readme(*args, **kwargs):
        return None

    monkeypatch.setattr(manager.github_client, "list_repos", fake_repo_list)
    monkeypatch.setattr(manager.github_client, "get_readme", fake_get_readme)

    new_repos = await manager._check_owner(owner)
    assert len(new_repos) == 1
    assert new_repos[0]["repo_name"] == "newer"
