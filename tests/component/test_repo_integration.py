"""Component tests for the repo integration (spec 06, 15).

Uses real local git via the conftest git_helper fixture (spec 15) — only the
clone URL is replaced with a local file:// path. Real SQLite tmp file.

Per the new spec 06/09 architecture: integrations no longer write ``Report``
rows directly; they populate ``RunResult.reports`` (``ReportSection`` with
structured ``payload``) and ``RunResult.events``. The reports pipeline
writes the ``Report`` rows from the sections.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import aiohttp
from pydantic import SecretStr
import pytest

from progress.config.root import CoreConfig, GitHubConfig
from progress.db import close_db, init_db, set_config
from progress.errors import CommandException
from progress.integrations.base import Components
from progress.integrations.repo import tracker as repo_tracker
from progress.integrations.repo.config import (
    OwnerItemConfig,
    RepoIntegrationConfig,
    RepoItemConfig,
    normalize_repo_url,
)
from progress.integrations.repo.models import GitHubOwner, Repository
from progress.integrations.repo.tracker import RepoIntegration

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def db(tmp_state_home: str):
    await init_db(tmp_state_home)
    yield
    await close_db()


async def _setup_integration(
    cfg: CoreConfig,
    session: aiohttp.ClientSession,
    plugin_cfg: RepoIntegrationConfig | None = None,
) -> RepoIntegration:
    integration = RepoIntegration()
    if plugin_cfg is not None:
        await set_config("repo", plugin_cfg.model_dump(mode="json"))
    await integration.setup(Components(cfg=cfg, session=session))
    return integration


class TestSync:
    async def test_sync_creates_repos(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[
                    RepoItemConfig(url="vitejs/vite", branch="main"),
                    RepoItemConfig(url="facebook/react"),
                ]
            )
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            result = await integration.sync()
            assert result.created == 2
            rows = await Repository.all()
            assert len(rows) == 2
            urls = {r.url for r in rows}
            assert normalize_repo_url("vitejs/vite") in urls

    async def test_sync_normalizes_urls(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(repos=[RepoItemConfig(url="vitejs/vite")])
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            await integration.sync()
            rows = await Repository.all()
            assert rows[0].url == "https://github.com/vitejs/vite.git"
            assert rows[0].name == "vitejs/vite"

    async def test_sync_updates_branch(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(repos=[RepoItemConfig(url="a/b", branch="main")])
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            await integration.sync()

            plugin_cfg2 = RepoIntegrationConfig(repos=[RepoItemConfig(url="a/b", branch="develop")])
            await set_config("repo", plugin_cfg2.model_dump(mode="json"))
            integration._plugin_cfg = plugin_cfg2
            result = await integration.sync()
            assert result.updated == 1
            rows = await Repository.all()
            assert rows[0].branch == "develop"

    async def test_sync_gc_removes_dropped_repos(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(repos=[RepoItemConfig(url="a/b"), RepoItemConfig(url="c/d")])
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            await integration.sync()
            assert await Repository.all().count() == 2

            plugin_cfg2 = RepoIntegrationConfig(repos=[RepoItemConfig(url="a/b")])
            await set_config("repo", plugin_cfg2.model_dump(mode="json"))
            integration._plugin_cfg = plugin_cfg2
            result = await integration.sync()
            assert result.deleted == 1
            assert await Repository.all().count() == 1

    async def test_sync_gc_keeps_disabled_repos(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(repos=[RepoItemConfig(url="a/b", enabled=False)])
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            result = await integration.sync()
            assert result.created == 1
            assert await Repository.all().count() == 1

    async def test_sync_creates_owners(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                owners=[
                    OwnerItemConfig(type="organization", name="vitejs"),
                    OwnerItemConfig(type="user", name="torvalds"),
                ]
            )
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            result = await integration.sync()
            assert result.created == 2
            rows = await GitHubOwner.all()
            assert len(rows) == 2

    async def test_sync_owner_updates_enabled_only(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                owners=[OwnerItemConfig(type="organization", name="vitejs", enabled=True)]
            )
            integration = await _setup_integration(core_cfg, session, plugin_cfg)
            await integration.sync()

            plugin_cfg2 = RepoIntegrationConfig(
                owners=[OwnerItemConfig(type="organization", name="vitejs", enabled=False)]
            )
            await set_config("repo", plugin_cfg2.model_dump(mode="json"))
            integration._plugin_cfg = plugin_cfg2
            result = await integration.sync()
            assert result.updated == 1
            owner = await GitHubOwner.first()
            assert owner is not None
            assert owner.enabled is False


class TestRun:
    async def test_run_baseline_report(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second commit", files={"file.txt": "content\n"})
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[RepoItemConfig(url="owner/repo", branch="main")],
                first_run_lookback_commits=1,
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()

            async def _fake_clone_or_fetch(*, ref, dest, branch, token, state_home, lookback=3) -> None:
                cloned = workspace / "owner_repo-clone"
                if cloned.exists():
                    shutil.rmtree(cloned)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch="main")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cloned), str(dest))

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            result = await integration.run()
            assert result.status == "success"
            assert len(result.reports) >= 1
            assert result.reports[0].payload.get("repo_name") == "owner/repo"
            assert result.reports[0].payload.get("commit_count", 0) >= 1

            rows = await Repository.all()
            assert rows[0].last_commit_hash is not None

    async def test_run_partial_on_clone_failure(
        self,
        db: None,
        tmp_state_home: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(repos=[RepoItemConfig(url="owner/repo", branch="main")])
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()

            async def _bad_clone_or_fetch(*, ref, dest, branch, token, state_home, lookback=3) -> None:
                raise CommandException("clone failed")

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _bad_clone_or_fetch)
            result = await integration.run()
            assert result.status in {"partial", "failed"}
            assert len(result.errors) >= 1

    async def test_run_skips_when_no_repos(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            integration = await _setup_integration(cfg, session, RepoIntegrationConfig())
            await integration.sync()
            result = await integration.run()
            assert result.status == "success"
            assert len(result.reports) == 0


class TestSetup:
    async def test_setup_without_token_logs_warning(self, db: None, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))
        async with aiohttp.ClientSession() as session:
            integration = await _setup_integration(cfg, session)
            assert integration._gh is None

    async def test_setup_loads_plugin_config(self, db: None, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(repos=[RepoItemConfig(url="a/b")])
            integration = await _setup_integration(cfg, session, plugin_cfg)
            assert integration._plugin_cfg.repos[0].url == "a/b"


class TestTeardown:
    async def test_teardown_clears_state(self, db: None, core_cfg: CoreConfig) -> None:
        async with aiohttp.ClientSession() as session:
            integration = await _setup_integration(core_cfg, session)
            await integration.teardown()
            assert integration._ctx is None
            assert integration._cfg is None
