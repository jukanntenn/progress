"""Root conftest — shared across all four test layers (spec 15 §2.4.1).

Responsibilities (spec 15 §2.4.1):
- uvloop policy (works around aiosqlite hanging on the default asyncio loop).
- Shared fixtures used by both ``tests/`` and ``e2e/``: ``tmp_state_home`` /
  ``workspace`` / ``git_helper`` / ``patch_clone_local`` / ``core_cfg`` /
  ``test_cfg``. pytest walks the directory tree upward, so a root conftest is
  visible to every test dir — this kills the copy-paste between tests/ and e2e/.
- autouse ``_stub_observability`` — monkeypatch every observability binding site
  to a no-op so tests do not pollute global OTel/structlog/Bugsink state.
- autouse ``_disable_real_model_requests`` — set pydantic-ai's
  ``ALLOW_MODEL_REQUESTS=False`` so a stray un-mocked agent can never make a real
  LLM call. Tests opt into a mock explicitly via ``agent.override(model=...)``.
- ``pytest_collection_modifyitems`` — auto-tag tests by directory (spec 15 §1.3),
  so case files never need a hand-written ``@pytest.mark.xxx``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
import uvloop

from progress.cli.ai import agent as ai_agent
from progress.config.root import CoreConfig
from progress.integrations.repo import tracker as repo_tracker

if TYPE_CHECKING:
    from pathlib import Path

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())  # ty: ignore[deprecated] -- uvloop workaround for aiosqlite; remove when upgrading to Python 3.14+


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-add layer markers by test file path (spec 15 §1.3)."""
    for item in items:
        path = str(item.fspath)
        if "/tests/e2e/" in path or path.startswith("tests/e2e/"):
            item.add_marker(pytest.mark.e2e)
        elif "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/component/" in path:
            item.add_marker(pytest.mark.component)


@pytest.fixture(autouse=True)
def _stub_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every observability binding site to a no-op (spec 15 §2.4.1).

    The runtime telemetry entry (``progress.runtime.telemetry``) and the
    webserver entry (``progress.runtime.webserver``) bind the names via
    ``from progress.observability import ...`` into their own module
    namespaces, so each binding site must be patched individually. The
    canonical ``progress.observability.*`` targets are patched too as
    belt-and-suspenders for any lazy import.
    """

    def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    targets = [
        "progress.runtime.telemetry.setup_telemetry",
        "progress.runtime.telemetry.flush_telemetry",
        "progress.runtime.telemetry.configure_structlog",
        "progress.runtime.telemetry.init_bugsink",
        "progress.runtime.webserver.instrument_fastapi_app",
        "progress.observability.setup_observability",
        "progress.observability.shutdown_observability",
    ]
    for target in targets:
        with contextlib.suppress(AttributeError):
            monkeypatch.setattr(target, _noop)


@pytest.fixture(autouse=True)
def _disable_real_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Globally forbid real LLM calls (spec 15 §2.4.1).

    Sets pydantic-ai's ``ALLOW_MODEL_REQUESTS=False``; a real ``Model.run`` would
    raise ``RuntimeError``. Tests opt into a fake model explicitly via
    ``agent.override(model=TestModel())`` / ``FunctionModel``.
    """
    monkeypatch.setattr("pydantic_ai.models.ALLOW_MODEL_REQUESTS", False)


@pytest.fixture(autouse=True)
def _reset_ai_agent_cache() -> Any:
    """Clear the per-result_type AI agent cache before each test.

    :func:`progress.cli.ai.agent.get_agent` caches one agent per output type so
    that ``agent.override`` reaches production call sites. Without a reset, an
    agent built (and possibly overridden) in one test would leak its model /
    ContextVar state into the next test.
    """

    ai_agent._agents.clear()
    yield
    ai_agent._agents.clear()


@pytest.fixture
def tmp_state_home(tmp_path: Path) -> str:
    """Per-test state_home directory (DB file lives at <state_home>/progress.db)."""
    state = tmp_path / "state"
    state.mkdir()
    return str(state)


@pytest.fixture
def core_cfg(tmp_state_home: str) -> CoreConfig:
    """Minimal CoreConfig with state_home pointing at a tmp directory."""
    return CoreConfig(state_home=tmp_state_home)


@pytest.fixture
def test_cfg(tmp_state_home: str) -> CoreConfig:
    """Alias of core_cfg named per spec 15 §2.4.1 (e2e cases reference ``test_cfg``)."""
    return CoreConfig(state_home=tmp_state_home)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Scratch directory for git repos / file IO."""
    d = tmp_path / "workspace"
    d.mkdir()
    return d


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _git_date_env(commit_date: str | None) -> dict[str, str]:
    """Build a GIT_AUTHOR_DATE/GIT_COMMITTER_DATE env override for deterministic timestamps.

    Tests that rely on commit ordering by author date (e.g. proposal first-run
    picking the newest-created file) pass an explicit ISO date here instead of
    sleeping to cross a wall-clock second boundary.
    """
    if not commit_date:
        return {}
    return {"GIT_AUTHOR_DATE": commit_date, "GIT_COMMITTER_DATE": commit_date}


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_GIT_ENV, **(env_override or {})}
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


class GitRepo:
    """Handle to a working repo + its bare remote for e2e/component tests."""

    def __init__(self, bare_path: Path, work_path: Path, branch: str = "main") -> None:
        self.bare_path = bare_path
        self.work_path = work_path
        self.branch = branch

    @property
    def head(self) -> str:
        result = _run_git(["rev-parse", "HEAD"], cwd=self.work_path)
        return result.stdout.strip()

    def add_commit(self, msg: str, *, files: dict[str, str] | None = None) -> str:
        return _GitHelper.add_commit(self, msg, files=files)


class _GitHelper:
    """Build bare + working repos under a tmp_path, with commit helpers."""

    def make_repo(
        self,
        workspace: Path,
        slug: str,
        *,
        initial_files: dict[str, str] | None = None,
        branch: str = "main",
        commit_date: str | None = None,
    ) -> GitRepo:
        bare = workspace / f"{slug}.git"
        work = workspace / slug
        bare.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "--bare", str(bare)])
        _run_git(["init", str(work)])
        _run_git(["checkout", "-b", branch], cwd=work)
        _run_git(["remote", "add", "origin", str(bare)], cwd=work)
        if initial_files:
            for rel_path, content in initial_files.items():
                full = work / rel_path
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
            _run_git(["add", "."], cwd=work)
        date_env = _git_date_env(commit_date)
        _run_git(["commit", "-m", "Initial commit", "--allow-empty"], cwd=work, env_override=date_env)
        _run_git(["push", "origin", branch], cwd=work)
        return GitRepo(bare_path=bare, work_path=work, branch=branch)

    @staticmethod
    def add_commit(
        repo: GitRepo,
        msg: str,
        *,
        files: dict[str, str] | None = None,
        commit_date: str | None = None,
    ) -> str:
        if files:
            for rel_path, content in files.items():
                full = repo.work_path / rel_path
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
            _run_git(["add", "."], cwd=repo.work_path)
        else:
            _run_git(["add", "."], cwd=repo.work_path)
        date_env = _git_date_env(commit_date)
        _run_git(["commit", "-m", msg], cwd=repo.work_path, env_override=date_env)
        _run_git(["push", "origin", repo.branch], cwd=repo.work_path)
        return repo.head

    @staticmethod
    def clone_as_local(workspace: Path, bare_path: Path, slug: str, branch: str = "main") -> Path:
        """Clone a bare repo to a working dir (used to simulate fetch+clone)."""
        dest = workspace / f"{slug}-clone"
        if dest.exists():
            shutil.rmtree(dest)
        _run_git(["clone", "--branch", branch, str(bare_path), str(dest)])
        return dest


@pytest.fixture
def git_helper() -> Any:
    """Expose git subprocess helpers for tests that build real local repos.

    Real git is used (spec 15) so the tests exercise the same code path as
    production; only the remote URL is replaced with a local file:// path.
    """
    return _GitHelper()


@pytest.fixture
def patch_clone_local() -> Any:
    """Return a callable that patches the repo tracker's bound ``clone_or_fetch``.

    Spec 15: tests use a real local git subprocess (not a mock) and only replace
    the remote URL with a local file:// path. ``clone_or_fetch`` is imported by
    name into ``progress.integrations.repo.tracker`` (from
    ``progress.integrations.repo.commit``), so patching the tracker module's
    bound name is what intercepts the production call.

    The fake clones the local bare repo (matching the component-test pattern)
    into ``dest``. ``url_to_bare`` maps the canonical GitHub URL
    (``https://github.com/owner/repo.git``) to the bare repo path; an unmapped
    URL raises so clone-failure cases get a real error.
    """

    def _patch(monkeypatch: pytest.MonkeyPatch, url_to_bare: dict[str, Path]) -> None:
        async def _fake_clone_or_fetch(
            *, ref, dest: Path, branch: str, token: str, state_home: str, lookback: int = 3
        ) -> None:
            canonical = f"https://github.com/{ref.owner}/{ref.name}.git"
            bare = url_to_bare.get(canonical)
            if bare is None:
                raise FileNotFoundError(f"no mock for clone url {canonical!r}")
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["clone", "--branch", branch or "main", str(bare), str(dest)])

        monkeypatch.setattr(repo_tracker, "clone_or_fetch", _fake_clone_or_fetch)

    return _patch


__all__ = [
    "GitRepo",
    "core_cfg",
    "git_helper",
    "patch_clone_local",
    "test_cfg",
    "tmp_state_home",
    "workspace",
]
