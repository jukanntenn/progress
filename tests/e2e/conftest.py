"""E2E fixtures: init/close DB boilerplate + per-integration atomic envs (spec 15).

Per spec 15 §2.4.2-2.4.4:
- ``core.run()`` owns its own lifespan (``init_db → run → close_db``), so tests
  cannot query the DB outside it. ``seed_config`` / ``db_view`` wrap the
  repeated init/close so cases stay terse and leak-free.
- Atomic fixtures are split **by integration** (not by mock tool), mirroring the
  ``e2e/<integration>/`` package layout. Each fixture bundles that
  integration's mock + seed config coupling.

Shared cross-layer fixtures (``tmp_state_home`` / ``workspace`` / ``git_helper``
/ ``patch_clone_local`` / ``core_cfg`` / ``test_cfg``) and the autouse
observability / ``ALLOW_MODEL_REQUESTS`` / agent-cache-reset stubs come from the
**root** conftest.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from pydantic import BaseModel

from typing import cast

from aioresponses import aioresponses
from aiosmtpd.controller import Controller
from pydantic import SecretStr
from pydantic_ai.models.test import TestModel
import pytest

from progress.cli.ai.agent import get_agent
from progress.db import close_db, init_db, set_config
from progress.integrations.proposal.tracker import (
    _KIND_CONFIGS,
    ProposalIntegration,
    ProposalKindConfig,
)


def _dump_for_seed(cfg: Any) -> dict[str, Any]:
    """Serialize a pydantic model for DB seeding, preserving SecretStr values.

    ``model_dump(mode='json')`` masks SecretStr to ``'**********'``; this
    helper walks the result and replaces masked values with the real ones so
    tests (and ``progress config import``) store usable credentials.
    """

    data = cfg.model_dump(mode="json") if hasattr(cfg, "model_dump") else cfg
    raw = cfg.model_dump() if hasattr(cfg, "model_dump") else {}
    return _unmask_secrets(data, raw)


def _unmask_secrets(data: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:

    out: dict[str, Any] = {}
    for key, value in data.items():
        raw_value = raw.get(key)
        if isinstance(raw_value, SecretStr):
            out[key] = raw_value.get_secret_value()
        elif isinstance(value, dict) and isinstance(raw_value, dict):
            out[key] = _unmask_secrets(value, raw_value)
        else:
            out[key] = value
    return out


@asynccontextmanager
async def seed_config(state_home: str, section: str, cfg: Any):
    """Pre-seed a config section before ``core.run()`` (spec 15 §2.4.3).

    open DB → set_config → close DB → yield. ``core.run()`` owns its own DB
    lifespan, so seeding must open/close the connection around the write; the
    body of the ``async with`` block runs after the DB is closed (typically the
    ``await run(test_cfg)`` call, which re-opens it).
    """
    await init_db(state_home)
    try:
        data = _dump_for_seed(cfg)
        await set_config(section, data)
    finally:
        await close_db()
    yield


@asynccontextmanager
async def db_view(state_home: str):
    """Open the DB for post-run assertions, then close (spec 15 §2.4.3).

    Usage::

        async with db_view(test_cfg.state_home):
            rows = await Report.all()
    """
    await init_db(state_home)
    try:
        yield
    finally:
        await close_db()


def _patch_kind_repo_url(monkeypatch: pytest.MonkeyPatch, kind: str, local_bare: Path) -> None:
    """Redirect a proposal kind's repo URL to a local bare repo path."""
    original = _KIND_CONFIGS[kind]
    monkeypatch.setitem(
        _KIND_CONFIGS,
        kind,
        ProposalKindConfig(
            kind=original.kind,
            repo_url=f"file://{local_bare}",
            branch=original.branch,
            subdirectory=original.subdirectory,
            file_pattern=original.file_pattern,
            tracker_url=original.tracker_url,
        ),
    )


def _patch_proposal_clone(monkeypatch: pytest.MonkeyPatch, local_bare: Path, branch: str) -> None:
    """Patch ``ProposalIntegration._clone_or_update`` to clone from a local bare repo."""

    async def _fake_clone_or_update(self: ProposalIntegration, kind_cfg: ProposalKindConfig) -> Path:
        state_home = self._cfg.state_home if self._cfg else "data"
        slug = f"{kind_cfg.kind}_repo"
        dest = Path(state_home) / "proposal_repos" / slug
        if dest.is_dir():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", branch, str(local_bare), str(dest)],
            check=True,
            capture_output=True,
        )
        return dest

    monkeypatch.setattr(ProposalIntegration, "_clone_or_update", _fake_clone_or_update)


@pytest.fixture
def repo_env(
    workspace: Path,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Real git repo + ``patch_clone_local`` mapping a GitHub URL to its bare path.

    Builds an ``owner/repo`` working repo with two commits (so the first-run
    lookback yields a non-empty diff — a single-commit repo produces an empty
    diff and is skipped) and binds the clone mock so ``core.run()``'s repo clone
    resolves to the local bare repo. Returns a dict with ``repo`` (GitRepo
    handle), ``bare_path``, ``url`` and ``branch``.
    """
    repo = git_helper.make_repo(
        workspace,
        "owner_repo",
        initial_files={"README.md": "# hello\n"},
    )
    repo.add_commit("Add feature", files={"feature.py": "print('hi')\n"})
    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})
    return {"repo": repo, "bare_path": repo.bare_path, "url": "owner/repo", "branch": "main"}


@pytest.fixture
def changelog_env(httpserver: Any) -> dict[str, Any]:
    """pytest-httpserver local server for changelog fetches (spec 15 §3.2).

    Yields a dict with the live ``httpserver``; cases register the specific
    responses they need (the URL is dynamic per test, so the changelog tracker
    config is built inside each case rather than seeded here).
    """
    return {"httpserver": httpserver}


@pytest.fixture
def proposal_env(
    workspace: Path,
    git_helper: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Real git repo with EIP frontmatter files + kind URL redirected to local.

    Builds a repo under ``EIPS/eip-*.md`` on the ``master`` branch (matching the
    ``eip`` kind config) and patches the proposal kind's repo URL + clone so
    ``core.run()`` clones locally. Returns a dict with ``repo`` / ``bare_path``.
    """
    repo = git_helper.make_repo(
        workspace,
        "eips_repo",
        branch="master",
        initial_files={
            "EIPS/eip-1.md": (
                "---\n"
                "eip: 1\n"
                "title: First EIP\n"
                "status: Draft\n"
                "type: Standards Track\n"
                "category: Core\n"
                "---\n\n"
                "# First EIP\n\n"
                "Body of the first EIP.\n"
            ),
            "EIPS/eip-2.md": (
                "---\n"
                "eip: 2\n"
                "title: Second EIP\n"
                "status: Final\n"
                "type: Standards Track\n"
                "---\n\n"
                "# Second EIP\n\n"
                "Body of the second EIP.\n"
            ),
        },
    )
    _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
    _patch_proposal_clone(monkeypatch, repo.bare_path, "master")
    return {"repo": repo, "bare_path": repo.bare_path}


@pytest.fixture
def gh_mock():
    """aioresponses-scoped GitHub API mock (gidgethub only, spec 15 §3.1/§3.4).

    Yields the ``aioresponses`` context so cases can register ``get``/``post``
    expectations against ``https://api.github.com/...``. Opt-in (not autouse)
    because it intercepts ALL aiohttp traffic and conflicts with
    pytest-httpserver (spec 15 §3.2). Mock responses should carry
    ``x-ratelimit-*`` headers to mirror real GitHub (spec 15 §3.4).
    """

    with aioresponses() as mocked:
        yield mocked


def _ratelimit_headers() -> dict[str, str]:
    return {
        "x-ratelimit-limit": "5000",
        "x-ratelimit-remaining": "4999",
        "x-ratelimit-reset": "9999999999",
    }


@contextmanager
def override_agent(result_type: type[BaseModel], *, response_text: str | None = None):
    """Override the cached AI agent with a ``TestModel`` (spec 08).

    ``get_agent(result_type)`` returns the same per-type singleton that
    production call sites use, so ``agent.override`` reaches them. ``TestModel``
    wins over the baked-in model (pydantic-ai ``_get_model`` checks the override
    first). ``response_text`` is fed through the agent's output validator
    (``_validate_with_repair``), so it must be valid JSON for ``result_type``;
    when ``None``, ``TestModel`` auto-generates schema-valid output.
    """

    agent = get_agent(result_type)
    test_model = TestModel(custom_output_text=response_text) if response_text else TestModel()
    with agent.override(model=test_model):
        yield agent


@pytest.fixture
async def smtp_server(tmp_path: Path):
    """Start a local aiosmtpd SMTP server; yield ``(host, port, messages)``.

    Opt-in (spec 15 §3.3). ``messages`` is the list of received ``DATA`` payloads
    (bytes), so cases can assert notification emails were dispatched. The server
    is stopped on teardown.
    """

    handler = _CaptureHandler()
    controller = Controller(handler, hostname="127.0.0.1", port=0)
    controller.start()
    try:
        server = cast("asyncio.Server", controller.server)
        sock = server.sockets[0]
        host, port = sock.getsockname()[:2]
        yield host, port, handler.messages
    finally:
        controller.stop()


class _CaptureHandler:
    """Minimal aiosmtpd handler that records received messages."""

    def __init__(self) -> None:
        self.messages: list[bytes] = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope.content)
        return "250 Message accepted for delivery"


__all__ = [
    "db_view",
    "override_agent",
    "seed_config",
]
