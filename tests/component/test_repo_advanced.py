"""Component tests for the repo integration's advanced flows (spec repo §6/7/8).

Covers:
- Release tracking (spec §6): first-run latest-only, incremental strict->,
  prereleases included / drafts filtered (client-level), published_at parsing,
  release diff truncation, checkpoint independence (release vs commit).
- Owner discovery (spec §7): first-run latest-only, incremental strict->,
  fork filtering, dedup against Repository table, README 404 skip,
  discovery events emitted.
- AI analysis (spec §8): commit diff + release + README analyses, failure
  fallback, json_repair.
- Tracking toggles (T6): track_commits/track_releases toggles + stale reenabled
  lookback window (commit diff count ≤ max_reenabled_lookback_commits when stale).

Uses:
- aioresponses to mock the GitHub REST API (gidgethub aiohttp adapter).
- Pydantic AI TestModel via ``agent.override`` (no real LLM call).
- Real local git via the conftest git_helper fixture for clone/diff paths.
- Real SQLite tmp file for state.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
from pydantic import SecretStr, ValidationError
import pytest

from progress.cli.ai import AnalysisResult
from progress.cli.git import GitHubClient, RepoRef, RepositoryInfo
from progress.cli.git.github import _parse_release, _parse_repository
from progress.cli.notifications.events import DiscoveredRepoEvent
from progress.config.root import AnalysisConfig, CoreConfig, GitHubConfig
from progress.db import close_db, init_db, set_config
from progress.errors import CommandException, GitException, ProgressException
from progress.integrations.base import Components
from progress.integrations.repo import commit as commit_module, tracker as repo_tracker
import progress.integrations.repo.analysis as analysis_module
from progress.integrations.repo.analysis import (
    MAX_DIFF_LENGTH,
    MAX_README_LENGTH,
    TruncatedDiff,
    analyze_commit_diff,
    analyze_readme,
    analyze_release,
    truncate_diff,
    truncate_readme,
)
from progress.integrations.repo.commit import DiffResult, _incremental_diff
from progress.integrations.repo.config import (
    OwnerItemConfig,
    RepoIntegrationConfig,
    RepoItemConfig,
)
from progress.integrations.repo.discovery import OwnerDiscoveryResult, discover_owner_repos, select_candidates
from progress.integrations.repo.models import GitHubOwner, Repository
from progress.integrations.repo.release import (
    check_releases,
    normalize_checkpoint_timestamp,
    parse_published_at,
)
from progress.integrations.repo.tracker import RepoIntegration


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


def _make_repo_payload(
    *,
    full_name: str = "vitejs/vite",
    created_at: str = "2024-01-01T00:00:00Z",
    fork: bool = False,
    description: str | None = "A build tool",
) -> dict[str, Any]:
    owner, name = full_name.split("/")
    return {
        "id": 1,
        "name": name,
        "full_name": full_name,
        "owner": {"login": owner},
        "default_branch": "main",
        "description": description,
        "html_url": f"https://github.com/{full_name}",
        "created_at": created_at,
        "fork": fork,
        "archived": False,
    }


def _make_release_payload(
    *,
    tag: str = "v1.0.0",
    name: str | None = "First Release",
    body: str | None = "Initial release",
    published_at: str = "2024-01-15T00:00:00Z",
    prerelease: bool = False,
    draft: bool = False,
    url: str = "https://github.com/vitejs/vite/releases/tag/v1.0.0",
) -> dict[str, Any]:
    return {
        "id": 1,
        "tag_name": tag,
        "name": name,
        "body": body,
        "published_at": published_at,
        "prerelease": prerelease,
        "draft": draft,
        "html_url": url,
    }


async def _setup(
    cfg: CoreConfig,
    session: aiohttp.ClientSession,
    plugin_cfg: RepoIntegrationConfig | None = None,
) -> RepoIntegration:
    integration = RepoIntegration()
    if plugin_cfg is not None:
        await set_config("repo", plugin_cfg.model_dump(mode="json"))
    await integration.setup(Components(cfg=cfg, session=session))
    return integration


def _patch_clone_local(monkeypatch: pytest.MonkeyPatch, workspace: Path, bare_path: Path):
    """Patch the repo tracker's clone_or_fetch to use a local bare repo."""

    async def _fake_clone_or_fetch(*, ref, dest, branch, token, state_home, lookback=3) -> None:
        cloned = workspace / "clone-tmp"
        if cloned.exists():
            shutil.rmtree(cloned)
        repo_dir = workspace / "clone-work"
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.mkdir()

        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
        }
        subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", branch or "main"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(bare_path)], cwd=repo_dir, check=True, capture_output=True
        )
        (repo_dir / "README.md").write_text("# hello\n")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, env=env, capture_output=True)
        subprocess.run(["git", "push", "origin", branch or "main"], cwd=repo_dir, check=True, capture_output=True)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", str(bare_path), str(dest)], check=True, capture_output=True)

    monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)


class TestReleaseTimestampParsing:
    """Spec repo §6.2 — checkpoint timestamp normalization."""

    def test_z_suffix(self) -> None:
        assert parse_published_at("2024-01-15T00:00:00Z") == datetime(2024, 1, 15, tzinfo=UTC)

    def test_explicit_offset(self) -> None:
        assert parse_published_at("2024-01-15T00:00:00+00:00") == datetime(2024, 1, 15, tzinfo=UTC)

    def test_invalid_returns_none(self) -> None:
        assert parse_published_at("not-a-date") is None
        assert parse_published_at("") is None
        assert parse_published_at(None) is None

    def test_naive_datetime_forced_utc(self) -> None:
        naive = datetime(2024, 1, 1)
        normalized = normalize_checkpoint_timestamp(naive)
        assert normalized is not None
        assert normalized.tzinfo == UTC

    def test_string_normalized(self) -> None:
        normalized = normalize_checkpoint_timestamp("2024-01-01T00:00:00Z")
        assert normalized == datetime(2024, 1, 1, tzinfo=UTC)

    def test_invalid_string_returns_none(self) -> None:
        assert normalize_checkpoint_timestamp("garbage") is None


class TestReleaseCheckAlgorithm:
    """Spec repo §6.2 — release selection via check_releases."""

    async def test_first_run_picks_latest_only(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")
        gh = AsyncMock(spec=GitHubClient)

        async def _iter_releases(_ref):
            for r in [
                _make_release_payload(tag="v1.0.0", published_at="2024-01-15T00:00:00Z"),
                _make_release_payload(tag="v0.9.0", published_at="2023-12-01T00:00:00Z"),
                _make_release_payload(tag="v0.5.0", published_at="2023-06-01T00:00:00Z", prerelease=True),
            ]:
                yield _parse_release(r)

        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="abc123")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=None,
        )
        assert result is not None
        assert len(result.candidates) == 1
        assert result.candidates[0].tag == "v1.0.0"
        assert result.latest_tag == "v1.0.0"

    async def test_first_run_picks_latest_prerelease(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        """A repo whose latest (or only) releases are prereleases must still
        surface one on first run — the deepseek-harness regression."""

        ref = RepoRef(owner="deepseek-ai", name="deepseek-harness")

        async def _iter_releases(_ref):
            for r in [
                _make_release_payload(tag="dsh-v0.1.1-rc.2", published_at="2026-08-21T12:35:08Z", prerelease=True),
                _make_release_payload(tag="dsh-v0.1.1-rc.1", published_at="2026-08-21T07:12:39Z", prerelease=True),
            ]:
                yield _parse_release(r)

        gh = AsyncMock(spec=GitHubClient)
        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="b150a55")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=None,
        )
        assert result is not None
        assert len(result.candidates) == 1
        assert result.candidates[0].tag == "dsh-v0.1.1-rc.2"
        assert result.latest_tag == "dsh-v0.1.1-rc.2"

    async def test_incremental_picks_new_prerelease(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")
        checkpoint_dt = datetime(2026, 8, 20, tzinfo=UTC)

        async def _iter_releases(_ref):
            for r in [
                _make_release_payload(tag="v1.0.0", published_at="2026-08-19T00:00:00Z"),
                _make_release_payload(tag="v1.1.0-rc.1", published_at="2026-08-21T00:00:00Z", prerelease=True),
            ]:
                yield _parse_release(r)

        gh = AsyncMock(spec=GitHubClient)
        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="abc789")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag="v1.0.0",
            last_release_commit_hash="prev",
            last_release_check_time=checkpoint_dt,
        )
        assert result is not None
        assert [c.tag for c in result.candidates] == ["v1.1.0-rc.1"]
        assert result.latest_tag == "v1.1.0-rc.1"

    async def test_incremental_strict_greater_than(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")
        checkpoint_dt = datetime(2024, 1, 10, tzinfo=UTC)

        async def _iter_releases(_ref):
            for r in [
                _make_release_payload(tag="v1.0.0", published_at="2024-01-15T00:00:00Z"),
                _make_release_payload(tag="v0.9.5", published_at="2024-01-12T00:00:00Z"),
                _make_release_payload(tag="v0.9.0", published_at="2023-12-01T00:00:00Z"),
                _make_release_payload(tag="v0.8.0", published_at="2024-01-10T00:00:00Z"),
            ]:
                yield _parse_release(r)

        gh = AsyncMock(spec=GitHubClient)
        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="def456")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag="v0.9.0",
            last_release_commit_hash="prev",
            last_release_check_time=checkpoint_dt,
        )
        assert result is not None
        candidate_tags = [c.tag for c in result.candidates]
        assert "v1.0.0" in candidate_tags
        assert "v0.9.5" in candidate_tags
        assert "v0.8.0" not in candidate_tags
        assert "v0.9.0" not in candidate_tags

    async def test_empty_releases_returns_none(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")

        async def _empty(_ref):
            return
            yield  # pragma: no cover

        gh = AsyncMock(spec=GitHubClient)
        gh.iter_releases = _empty

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=None,
        )
        assert result is None

    async def test_unparsable_published_at_skipped(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")

        async def _iter_releases(_ref):
            yield _parse_release(_make_release_payload(tag="v1.0.0", published_at="not-a-date"))
            yield _parse_release(_make_release_payload(tag="v0.9.0", published_at="2024-01-01T00:00:00Z"))

        gh = AsyncMock(spec=GitHubClient)
        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="abc")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=None,
        )
        assert result is not None
        assert len(result.candidates) == 1
        assert result.candidates[0].tag == "v0.9.0"

    async def test_incremental_caps_at_limit_and_marks_truncated(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")
        gh = AsyncMock(spec=GitHubClient)

        async def _iter_releases(_ref):
            for i in range(7, 0, -1):
                yield _parse_release(
                    _make_release_payload(
                        tag=f"v1.0.{i}",
                        published_at=f"2024-01-{i:02d}T00:00:00Z",
                    )
                )

        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="abc123")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=datetime(2024, 1, 1, tzinfo=UTC),
            max_incremental_lookback_releases=3,
        )
        assert result is not None
        assert len(result.candidates) == 3
        assert result.truncated is True
        assert result.total_available == 6
        assert result.candidates[0].tag == "v1.0.7"

    async def test_first_run_takes_latest_single_release(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")
        gh = AsyncMock(spec=GitHubClient)

        async def _iter_releases(_ref):
            for i in range(7, 0, -1):
                yield _parse_release(
                    _make_release_payload(
                        tag=f"v1.0.{i}",
                        published_at=f"2024-01-{i:02d}T00:00:00Z",
                    )
                )

        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="abc123")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=None,
        )
        assert result is not None
        assert len(result.candidates) == 1
        assert result.truncated is False
        assert result.candidates[0].tag == "v1.0.7"

    async def test_incremental_under_limit_not_truncated(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        ref = RepoRef(owner="vitejs", name="vite")
        gh = AsyncMock(spec=GitHubClient)

        async def _iter_releases(_ref):
            for i in (2, 1):
                yield _parse_release(
                    _make_release_payload(
                        tag=f"v1.0.{i}",
                        published_at=f"2024-01-{i:02d}T00:00:00Z",
                    )
                )

        gh.iter_releases = _iter_releases
        gh.get_release_commit_sha = AsyncMock(return_value="abc123")

        result = await check_releases(
            ref=ref,
            gh=gh,
            repos_dir=Path(tmp_state_home) / "repos",
            last_release_tag=None,
            last_release_commit_hash=None,
            last_release_check_time=datetime(2024, 1, 1, tzinfo=UTC),
            max_incremental_lookback_releases=3,
        )
        assert result is not None
        assert len(result.candidates) == 1
        assert result.truncated is False


class TestOwnerDiscovery:
    """Spec repo §7 — owner auto-discovery."""

    async def test_select_candidates_first_run_picks_latest(self) -> None:

        repos = [
            RepositoryInfo(
                owner="vitejs",
                name="vite",
                full_name="vitejs/vite",
                default_branch="main",
                description="",
                html_url="https://github.com/vitejs/vite",
                created_at="2024-03-01T00:00:00Z",
            ),
            RepositoryInfo(
                owner="vitejs",
                name="old",
                full_name="vitejs/old",
                default_branch="main",
                description="",
                html_url="https://github.com/vitejs/old",
                created_at="2023-01-01T00:00:00Z",
            ),
        ]
        candidates, newest = select_candidates(repos, watermark=None)
        assert len(candidates) == 1
        assert candidates[0].full_name == "vitejs/vite"
        assert newest is not None

    async def test_select_candidates_incremental_strict_greater(self) -> None:

        watermark = datetime(2024, 1, 1, tzinfo=UTC)
        repos = [
            RepositoryInfo(
                owner="vitejs",
                name="a",
                full_name="vitejs/a",
                default_branch="main",
                description="",
                html_url="https://github.com/vitejs/a",
                created_at="2024-02-01T00:00:00Z",
            ),
            RepositoryInfo(
                owner="vitejs",
                name="b",
                full_name="vitejs/b",
                default_branch="main",
                description="",
                html_url="https://github.com/vitejs/b",
                created_at="2024-01-01T00:00:00Z",
            ),
            RepositoryInfo(
                owner="vitejs",
                name="c",
                full_name="vitejs/c",
                default_branch="main",
                description="",
                html_url="https://github.com/vitejs/c",
                created_at="2023-12-01T00:00:00Z",
            ),
        ]
        candidates, _ = select_candidates(repos, watermark=watermark)
        assert {c.full_name for c in candidates} == {"vitejs/a"}

    async def test_select_candidates_advances_watermark_even_with_no_candidates(self) -> None:

        watermark = datetime(2025, 1, 1, tzinfo=UTC)
        repos = [
            RepositoryInfo(
                owner="vitejs",
                name="old",
                full_name="vitejs/old",
                default_branch="main",
                description="",
                html_url="https://github.com/vitejs/old",
                created_at="2024-01-01T00:00:00Z",
            ),
        ]
        candidates, newest = select_candidates(repos, watermark=watermark)
        assert candidates == []
        assert newest == datetime(2024, 1, 1, tzinfo=UTC)

    async def test_forks_filtered(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:

        gh = AsyncMock(spec=GitHubClient)

        async def _list(owner, *, owner_type, watermark=None):
            for r in [
                _make_repo_payload(full_name="vitejs/vite", fork=False),
                _make_repo_payload(full_name="vitejs/fork", fork=True),
            ]:
                yield _parse_repository(r)

        gh.list_owner_repos = _list
        repos = await discover_owner_repos(gh=gh, owner_name="vitejs", owner_type="organization")
        names = [r.full_name for r in repos]
        assert "vitejs/vite" in names
        assert "vitejs/fork" not in names

    async def test_owner_run_emits_discovered_event(
        self,
        db: None,
        tmp_state_home: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("t")))
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                owners=[OwnerItemConfig(type="organization", name="vitejs")],
            )
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            owner = await GitHubOwner.first()
            owner.last_tracked_repo = None  # ty:ignore[invalid-assignment]
            await owner.save()  # ty:ignore[unresolved-attribute]

            async def _fake_discover(self, owner, known_urls):

                return OwnerDiscoveryResult(
                    events=[
                        DiscoveredRepoEvent(
                            owner="vitejs",
                            name="vitejs/vite",
                            url="https://github.com/vitejs/vite",
                            description="A build tool",
                            readme_summary="Summary",
                            readme_detail="Detail",
                        )
                    ],
                    newest_created_at=datetime.now(UTC),
                )

            monkeypatch.setattr(RepoIntegration, "_discover_for_owner", _fake_discover)

            result = await integration.run()
            assert len(result.events) == 1
            assert result.events[0].name == "vitejs/vite"  # ty:ignore[unresolved-attribute]
            assert len(result.reports) == 1
            assert result.reports[0].payload.get("report_type") == "repo_new"

    async def test_no_gh_client_skips_discovery(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))
        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                owners=[OwnerItemConfig(type="organization", name="vitejs")],
            )
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()
            result = await integration.run()
            assert result.events == []


class TestAIAnalysis:
    """Spec repo §8 — AI analysis failure fallback."""

    async def test_commit_diff_analysis_failure_returns_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        analysis_module.build_model_string = lambda cfg: "test:test"  # ty:ignore[invalid-assignment]

        async def _failing_run(agent, prompt, *, model=None):
            raise RuntimeError("simulated AI failure")

        monkeypatch.setattr(analysis_module, "run_extraction", _failing_run)

        cfg = AnalysisConfig(provider="test", model="test:claude", api_key=SecretStr("k"))
        truncated = TruncatedDiff(text="diff content", truncated=False, original_length=12, analyzed_length=12)

        result = await analyze_commit_diff(
            repo_name="vitejs/vite",
            branch="main",
            diff_text="diff content",
            commit_messages=["msg"],
            truncated=truncated,
            cfg=cfg,
        )
        assert "AI analysis unavailable" in result.summary
        assert result.detail == ""

    async def test_release_analysis_failure_returns_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        analysis_module.build_model_string = lambda cfg: "test:test"  # ty:ignore[invalid-assignment]

        async def _failing_run(agent, prompt, *, model=None):
            raise RuntimeError("simulated AI failure")

        monkeypatch.setattr(analysis_module, "run_extraction", _failing_run)

        cfg = AnalysisConfig(provider="test", model="test:claude", api_key=SecretStr("k"))

        result = await analyze_release(
            repo_name="vitejs/vite",
            branch="main",
            tag="v1.0.0",
            name="First",
            notes="notes",
            published_at="2024-01-15T00:00:00Z",
            commit_hash="abc",
            diff_text="diff",
            cfg=cfg,
        )
        assert "AI analysis unavailable for v1.0.0" in result.summary
        assert result.detail == ""

    async def test_release_analysis_prompt_carries_notes_and_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: ``analyze_release`` must populate the prompt template
        variables the prompt actually references (``release_tag`` /
        ``release_notes`` / ``release_published_at`` / ``branch``). A prior
        rename of ``release_analysis_prompt.j2`` left the caller passing
        ``tag`` / ``notes`` / ``published_at``; Jinja2 rendered them as empty,
        so the AI saw "No release notes provided." and emitted vacuous
        summaries even when full notes existed."""

        captured: dict[str, str] = {}

        async def _capturing_run(agent, prompt, *, model=None):
            captured["prompt"] = prompt

            return AnalysisResult(summary="s", detail="d")

        monkeypatch.setattr(analysis_module, "build_model_string", lambda cfg: "test:test")
        monkeypatch.setattr(analysis_module, "run_extraction", _capturing_run)

        cfg = AnalysisConfig(provider="test", model="test:claude", api_key=SecretStr("k"))

        await analyze_release(
            repo_name="vitejs/vite",
            branch="main",
            tag="v2.1.0",
            name="Big Release",
            notes="Plan Canvas and Kimi harness ship in this release.",
            published_at="2026-07-28T00:00:00Z",
            commit_hash="abc123",
            diff_text="diff body",
            cfg=cfg,
        )
        prompt = captured["prompt"]
        assert "v2.1.0" in prompt
        assert "2026-07-28T00:00:00Z" in prompt
        assert "Plan Canvas and Kimi harness ship in this release." in prompt
        assert "No release notes provided." not in prompt
        assert "main" in prompt

    async def test_readme_analysis_failure_returns_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        analysis_module.build_model_string = lambda cfg: "test:test"  # ty:ignore[invalid-assignment]

        async def _failing_run(agent, prompt, *, model=None):
            raise RuntimeError("simulated AI failure")

        monkeypatch.setattr(analysis_module, "run_extraction", _failing_run)

        cfg = AnalysisConfig(provider="test", model="test:claude", api_key=SecretStr("k"))

        result = await analyze_readme(
            repo_name="vitejs/vite",
            description="A build tool",
            readme="content",
            cfg=cfg,
        )
        assert "README analysis unavailable" in result.summary
        assert result.detail == ""

    async def test_readme_truncation_at_50000_chars(self) -> None:

        small = "x" * 100
        text, truncated = truncate_readme(small)
        assert text == small
        assert truncated is False

        big = "x" * (MAX_README_LENGTH + 100)
        text, truncated = truncate_readme(big)
        assert len(text) == MAX_README_LENGTH
        assert truncated is True

    async def test_diff_truncation(self) -> None:

        small = "x" * 100
        result = truncate_diff(small)
        assert result.truncated is False
        assert result.text == small

        big = "y" * (MAX_DIFF_LENGTH + 1000)
        result = truncate_diff(big)
        assert result.truncated is True
        assert result.original_length == MAX_DIFF_LENGTH + 1000
        assert result.analyzed_length == MAX_DIFF_LENGTH
        assert len(result.text) == MAX_DIFF_LENGTH

    async def test_no_ai_config_returns_fallback(self) -> None:

        cfg = AnalysisConfig()
        truncated = TruncatedDiff(text="diff", truncated=False, original_length=4, analyzed_length=4)

        result = await analyze_commit_diff(
            repo_name="vitejs/vite",
            branch="main",
            diff_text="diff",
            commit_messages=["msg"],
            truncated=truncated,
            cfg=cfg,
        )
        assert "AI analysis unavailable" in result.summary


async def _empty_releases():
    return
    yield  # pragma: no cover


class TestTrackingToggles:
    """T6 — track_commits/track_releases toggles + stale reenabled lookback."""

    async def test_track_commits_false_skips_diff_but_advances_checkpoint(
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
                repos=[RepoItemConfig(url="owner/repo", branch="main", track_commits=False)],
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()

            async def _fake_clone_or_fetch(
                *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
            ) -> None:
                cloned = workspace / "owner_repo-clone"
                if cloned.exists():
                    shutil.rmtree(cloned)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch="main")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cloned), str(dest))

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            await integration.run()
            head = repo.head
            rows = await Repository.all()
            assert rows[0].last_commit_hash == head
            assert rows[0].last_check_time is not None

    async def test_track_releases_false_skips_but_checkpoint_unchanged(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[RepoItemConfig(url="owner/repo", branch="main", track_releases=False)],
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()

            async def _fake_clone_or_fetch(
                *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
            ) -> None:
                cloned = workspace / "owner_repo-clone"
                if cloned.exists():
                    shutil.rmtree(cloned)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch="main")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cloned), str(dest))

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            await integration.run()
            rows = await Repository.all()
            assert rows[0].last_release_tag is None
            assert rows[0].last_release_check_time is None

    async def test_stale_config_fields_removed(self) -> None:

        for removed_field in (
            "max_reenabled_lookback_commits",
            "max_reenabled_lookback_releases",
            "reenabled_stale_days",
        ):
            with pytest.raises(ValidationError):
                RepoIntegrationConfig.model_validate({removed_field: 7})

    async def test_release_failure_degrades_to_commit_analysis(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second commit", files={"file.txt": "content\n"})
        cfg = CoreConfig(
            state_home=tmp_state_home,
            github=GitHubConfig(gh_token=SecretStr("real-token")),
        )

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[RepoItemConfig(url="owner/repo", branch="main")],
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()

            async def _fake_clone_or_fetch(
                *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
            ) -> None:
                cloned = workspace / "owner_repo-clone"
                if cloned.exists():
                    shutil.rmtree(cloned)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch="main")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cloned), str(dest))

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            async def _exploding_iter_releases(_ref):
                raise TypeError("'NoneType' object is not iterable")
                yield  # pragma: no cover

            monkeypatch.setattr(integration._gh.__class__, "iter_releases", _exploding_iter_releases)

            result = await integration.run()

        update_sections = [r for r in result.reports if r.payload.get("report_type") != "repo_new"]
        assert len(update_sections) > 0
        payload = update_sections[0].payload
        assert payload.get("status") == "success"
        assert payload.get("commit_count", 0) > 0

    async def test_owner_discovery_failure_records_event(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second commit", files={"file.txt": "content\n"})

        cfg = CoreConfig(
            state_home=tmp_state_home,
            github=GitHubConfig(gh_token=SecretStr("ghp_valid_token")),
        )

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[RepoItemConfig(url="owner/repo", branch="main")],
                owners=[OwnerItemConfig(type="organization", name="exploding_owner")],
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()

            async def _fake_clone_or_fetch(
                *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
            ) -> None:
                cloned = workspace / "owner_repo-clone"
                if cloned.exists():
                    shutil.rmtree(cloned)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch="main")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cloned), str(dest))

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            async def _empty_releases(_ref):
                return
                yield  # pragma: no cover

            monkeypatch.setattr(integration._gh.__class__, "iter_releases", _empty_releases)

            async def _exploding_discover(self, owner, known_urls):
                raise RuntimeError("simulated crash")

            monkeypatch.setattr(RepoIntegration, "_discover_for_owner", _exploding_discover)

            result = await integration.run()

        assert result.status == "partial"


class TestFeature1EnsureObject:
    """Feature 1: airflow dead-loop fix — ensure_object + checkpoint fallback."""

    async def test_incremental_diff_recovers_via_fetch_by_sha(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """bad object → ensure_object fetches it → diff succeeds (no dead loop)."""

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second", files={"f.txt": "x\n"})
        git_helper.add_commit(repo, "third", files={"g.txt": "y\n"})
        dest = workspace / "clone"
        shutil.copytree(repo.work_path, dest)
        old_sha = repo.head
        git_helper.add_commit(repo, "fourth", files={"h.txt": "z\n"})
        new_sha = repo.head

        call_log = []

        async def mock_get_diff(d, o, n):
            call_log.append(("get_diff", o, n))
            if o == old_sha and call_log.count(("get_diff", old_sha, new_sha)) < 2:
                raise ProgressException(f"fatal: bad object {o}")
            return "diff content"

        async def mock_get_commit_messages(d, *, old_hash=None, new_hash=None):
            return []

        async def mock_get_commit_count(d, o, n):
            return 1

        async def mock_ensure_object(d, sha):
            call_log.append(("ensure_object", sha))
            return True

        monkeypatch.setattr(commit_module, "get_diff", mock_get_diff)
        monkeypatch.setattr(commit_module, "get_commit_messages", mock_get_commit_messages)
        monkeypatch.setattr(commit_module, "get_commit_count", mock_get_commit_count)
        monkeypatch.setattr(commit_module, "ensure_object", mock_ensure_object)

        result = await _incremental_diff(dest=dest, old_hash=old_sha, new_hash=new_sha, lookback=3)
        assert result is not None
        assert result.diff == "diff content"
        assert any(c[0] == "ensure_object" for c in call_log)

    async def test_incremental_diff_unreachable_raises_gitexception(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Object unreachable → raise GitException with unreachable marker."""

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second", files={"f.txt": "x\n"})
        dest = workspace / "clone"
        shutil.copytree(repo.work_path, dest)
        old_sha = repo.head
        git_helper.add_commit(repo, "third", files={"g.txt": "y\n"})
        new_sha = repo.head

        async def mock_get_diff(d, o, n):

            raise ProgressException(f"fatal: bad object {o}")

        async def mock_ensure_object(d, sha):
            return False

        monkeypatch.setattr(commit_module, "get_diff", mock_get_diff)
        monkeypatch.setattr(commit_module, "ensure_object", mock_ensure_object)
        monkeypatch.setattr(commit_module, "get_commit_messages", lambda *a, **k: [])
        monkeypatch.setattr(commit_module, "get_commit_count", lambda *a, **k: 0)

        with pytest.raises(GitException, match="unreachable"):
            await _incremental_diff(dest=dest, old_hash=old_sha, new_hash=new_sha, lookback=3)

    async def test_incremental_diff_network_error_propagates(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Network error during ensure_object: propagates as CommandException."""

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second", files={"f.txt": "x\n"})
        dest = workspace / "clone"
        shutil.copytree(repo.work_path, dest)
        old_sha = repo.head
        git_helper.add_commit(repo, "third", files={"g.txt": "y\n"})
        new_sha = repo.head

        async def mock_get_diff(d, o, n):

            raise ProgressException(f"fatal: bad object {o}")

        async def mock_ensure_object(d, sha):

            raise CommandException("git fetch origin abc123 timed out after 300s")

        monkeypatch.setattr(commit_module, "get_diff", mock_get_diff)
        monkeypatch.setattr(commit_module, "ensure_object", mock_ensure_object)

        with pytest.raises(CommandException, match="timed out"):
            await _incremental_diff(dest=dest, old_hash=old_sha, new_hash=new_sha, lookback=3)

    async def test_run_one_repo_advances_checkpoint_on_unreachable(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Tracker fallback: unreachable checkpoint → advance + first-run diff → success."""

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second", files={"f.txt": "x\n"})
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[RepoItemConfig(url="owner/repo", branch="main")],
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()
            # Set checkpoint to a sha that will become "unreachable"
            repo_row = await Repository.first()
            assert repo_row is not None
            old_head = repo.head
            repo_row.last_commit_hash = old_head
            await repo_row.save()

            async def _fake_clone_or_fetch(
                *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
            ) -> None:
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch=branch or "main")

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            # Make _compute_commit_diff first call raise unreachable, second succeed
            call_count = 0

            async def _fake_compute_diff(self_inst, dest, repo_row):
                nonlocal call_count
                call_count += 1
                if call_count == 1 and repo_row.last_commit_hash is not None:
                    raise GitException(
                        f"checkpoint object {repo_row.last_commit_hash} unreachable on remote; advancing checkpoint"
                    )

                new_head = repo.head
                return DiffResult(
                    diff="diff content",
                    previous_commit=repo_row.last_commit_hash or new_head,
                    commit_count=1,
                    is_range_check=True,
                )

            monkeypatch.setattr(repo_tracker.RepoIntegration, "_compute_commit_diff", _fake_compute_diff)

            events = []
            original_record = repo_tracker.record_business_event

            def _capture_event(name, attributes=None):
                events.append((name, attributes))
                original_record(name, attributes=attributes)

            monkeypatch.setattr(repo_tracker, "record_business_event", _capture_event)

            result = await integration.run()

        assert result.status == "success"
        assert len(result.errors) == 0
        assert any(e[0] == "progress.git.checkpoint_advanced" for e in events)
        updated_row = await Repository.first()
        assert updated_row is not None
        assert call_count == 2

    async def test_run_one_repo_network_error_does_not_advance_checkpoint(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Network error → checkpoint NOT advanced → partial status with error."""

        repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# X\n"})
        git_helper.add_commit(repo, "second", files={"f.txt": "x\n"})
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))

        async with aiohttp.ClientSession() as session:
            plugin_cfg = RepoIntegrationConfig(
                repos=[RepoItemConfig(url="owner/repo", branch="main")],
            )
            integration = await _setup_integration(cfg, session, plugin_cfg)
            await integration.sync()
            repo_row = await Repository.first()
            assert repo_row is not None
            old_head = repo.head
            repo_row.last_commit_hash = old_head
            await repo_row.save()

            async def _fake_clone_or_fetch(
                *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
            ) -> None:
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                git_helper.clone_as_local(workspace, repo.bare_path, "owner_repo", branch=branch or "main")

            monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

            async def _failing_compute_diff(self_inst, dest, repo_row):
                raise CommandException(f"git diff {repo_row.last_commit_hash}..HEAD failed: Read timed out")

            monkeypatch.setattr(repo_tracker.RepoIntegration, "_compute_commit_diff", _failing_compute_diff)

            events = []
            original_record = repo_tracker.record_business_event

            def _capture_event(name, attributes=None):
                events.append((name, attributes))
                original_record(name, attributes=attributes)

            monkeypatch.setattr(repo_tracker, "record_business_event", _capture_event)

            result = await integration.run()

        assert result.status == "partial"
        assert len(result.errors) == 1
        assert "timed out" in str(result.errors[0]).lower()
        assert not any(e[0] == "progress.git.checkpoint_advanced" for e in events)
        assert any(e[0] == "progress.git.diff_failed" for e in events)
        updated_row = await Repository.first()
        assert updated_row is not None
        assert updated_row.last_commit_hash == old_head
