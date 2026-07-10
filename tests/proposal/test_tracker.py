import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from progress.contrib.proposal.models import Proposal, ProposalTrackerState
from progress.contrib.proposal.tracker import ProposalTracker
from progress.contrib.proposal.types import ProposalKind
from progress.db import close_db, create_tables, init_db


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo_dir = tmp_path / "proposal-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "test")
    for name, content in files.items():
        p = repo_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        _git(repo_dir, "add", name)
    _git(repo_dir, "commit", "-m", "initial")
    return repo_dir


def _mock_analyzer(**overrides):
    analyzer = Mock()
    analyzer.analyze = AsyncMock(return_value=('{"summary": "s", "detail": "d"}'))
    for k, v in overrides.items():
        setattr(analyzer, k, v)
    return analyzer


def _mock_git(tmp_path, commit, **overrides):
    git_client = Mock()
    git_client.workspace_dir = tmp_path / "ws"
    git_client.get_current_commit = AsyncMock(return_value=commit)
    git_client.get_changed_file_statuses = AsyncMock(return_value=[])
    git_client.get_file_creation_date = AsyncMock(return_value="2024-01-01 00:00:00 +0000")
    git_client.fetch_and_reset = AsyncMock()
    git_client.get_file_diff = AsyncMock(return_value="")
    git_client.timeout = 30
    for k, v in overrides.items():
        setattr(git_client, k, v if isinstance(v, Mock) else AsyncMock(return_value=v))
    return git_client


def _make_tracker(analyzer, git_client, github_client=None):
    return ProposalTracker(
        analyzer=analyzer,
        git_client=git_client,
        clock=lambda: datetime.now(ZoneInfo("UTC")),
        github_client=github_client,
    )


def _async_return(value):
    """Build an awaitable returning ``value`` — replaces the sync lambda override
    for ``tracker._clone_or_update`` (now awaited) in tests that stub the clone."""

    async def _stub(config):
        return value

    return _stub


@pytest.fixture()
async def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    await init_db(str(db_path))
    await create_tables()
    yield
    await close_db()


class TestInitialCheck:
    async def test_saves_all_proposals_to_db(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Draft\n---\n\nBody\n",
                "EIPS/eip-2.md": "---\neip: 2\ntitle: Another EIP\nstatus: Final\n---\n\nBody\n",
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.EIP)

        assert len(reports) == 1
        assert await Proposal.all().count() == 2

        state = await ProposalTrackerState.get(kind="eip")
        assert state.last_seen_commit == commit

    async def test_returns_one_verification_report(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "text/0001-a.md": "# A\n\n- Feature Name: a\n",
                "text/0002-b.md": "# B\n\n- Feature Name: b\n",
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.RFC)
        assert len(reports) == 1

    async def test_empty_repo_returns_no_reports(self, db, tmp_path: Path):
        repo_dir = _make_repo(tmp_path, {"README.md": "# README\n"})
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.RFC)
        assert len(reports) == 0

    async def test_updates_last_seen_commit(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {"EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"},
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        await tracker.check(ProposalKind.EIP)

        state = await ProposalTrackerState.get(kind="eip")
        assert state.last_seen_commit == commit


class TestIncrementalCheck:
    async def test_detect_status_change_draft_to_final(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Draft\ntype: Standards Track\n---\n\nBody\n"
            },
        )
        commit1 = _git(repo_dir, "rev-parse", "HEAD")

        analyzer = _mock_analyzer()
        git_client = _mock_git(tmp_path, commit1, get_file_diff="diff content")
        tracker = _make_tracker(analyzer, git_client)
        tracker._clone_or_update = _async_return(repo_dir)
        await tracker.check(ProposalKind.EIP)

        (repo_dir / "EIPS" / "eip-1.md").write_text(
            "---\neip: 1\ntitle: Test EIP\nstatus: Final\ntype: Standards Track\n---\n\nBody changed\n",
            encoding="utf-8",
        )
        _git(repo_dir, "add", "EIPS/eip-1.md")
        _git(repo_dir, "commit", "-m", "update status")
        commit2 = _git(repo_dir, "rev-parse", "HEAD")

        git_client.get_current_commit = AsyncMock(return_value=commit2)
        git_client.get_changed_file_statuses = AsyncMock(
            return_value=[("M", "EIPS/eip-1.md")]
        )

        reports = await tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].new_status.value == "final"

    async def test_no_change_same_commit_returns_empty(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {"EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"},
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        await tracker.check(ProposalKind.EIP)
        reports2 = await tracker.check(ProposalKind.EIP)
        assert len(reports2) == 0


class TestDeletedFile:
    async def test_nonterminal_becomes_withdrawn(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"
            },
        )
        commit1 = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit1))
        tracker._clone_or_update = _async_return(repo_dir)
        await tracker.check(ProposalKind.EIP)

        _git(repo_dir, "rm", "EIPS/eip-1.md")
        _git(repo_dir, "commit", "-m", "delete eip")
        commit2 = _git(repo_dir, "rev-parse", "HEAD")

        git_client = tracker.git
        git_client.get_current_commit = AsyncMock(return_value=commit2)
        git_client.get_changed_file_statuses = AsyncMock(
            return_value=[("D", "EIPS/eip-1.md")]
        )

        reports = await tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].new_status.value == "withdrawn"

    async def test_terminal_no_status_change(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Final\n---\n\nBody\n"
            },
        )
        commit1 = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit1))
        tracker._clone_or_update = _async_return(repo_dir)
        await tracker.check(ProposalKind.EIP)

        _git(repo_dir, "rm", "EIPS/eip-1.md")
        _git(repo_dir, "commit", "-m", "delete eip")
        commit2 = _git(repo_dir, "rev-parse", "HEAD")

        git_client = tracker.git
        git_client.get_current_commit = AsyncMock(return_value=commit2)
        git_client.get_changed_file_statuses = AsyncMock(
            return_value=[("D", "EIPS/eip-1.md")]
        )

        reports = await tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].new_status.value == "final"

    async def test_unknown_file_returns_none(self, db, tmp_path: Path):
        repo_dir = _make_repo(tmp_path, {"README.md": "# Hello\n"})
        commit = _git(repo_dir, "rev-parse", "HEAD")

        state = await ProposalTrackerState.create(kind="eip", last_seen_commit=commit)

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))

        from progress.contrib.proposal.parser import EIPParser

        result = await tracker._handle_deleted(
            ProposalKind.EIP, state, EIPParser(), "EIPS/eip-999.md", commit
        )
        assert result is None


class TestErrorHandling:
    async def test_parse_error_skipped_gracefully(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "peps/pep-bad.rst": "PEP: TBD\nTitle: Bad\nStatus: Draft\n\nBody\n",
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.PEP)
        assert len(reports) == 0

    async def test_analysis_failure_does_not_block_check(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {"EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"},
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        analyzer = _mock_analyzer(
            analyze=AsyncMock(side_effect=Exception("AI service unavailable"))
        )
        tracker = _make_tracker(analyzer, _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].analysis_summary is None


class TestRFCPRTitleResolution:
    _RFC_FILE = (
        "- Feature Name: `complex_numbers`\n"
        "- RFC PR: [rust-lang/rfcs#3892](https://github.com/rust-lang/rfcs/pull/3892)\n"
        "\n"
        "## Summary\n"
        "Add complex number support.\n"
    )

    def _make_rfc_repo(self, tmp_path: Path) -> Path:
        return _make_repo(tmp_path, {"text/3892-complex-numbers.md": self._RFC_FILE})

    async def test_uses_pr_title_when_available(self, db, tmp_path: Path):
        repo_dir = self._make_rfc_repo(tmp_path)
        commit = _git(repo_dir, "rev-parse", "HEAD")

        github_client = Mock()
        github_client.get_pr_title = AsyncMock(return_value="Complex number types")
        tracker = _make_tracker(
            _mock_analyzer(), _mock_git(tmp_path, commit), github_client
        )
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.RFC)
        assert len(reports) == 1
        assert reports[0].title == "Complex number types"

        from progress.contrib.proposal.models import Proposal

        saved = await Proposal.get(tracker__kind="rfc", number="3892")
        assert saved.title == "Complex number types"

    async def test_falls_back_when_pr_title_unavailable(self, db, tmp_path: Path):
        repo_dir = self._make_rfc_repo(tmp_path)
        commit = _git(repo_dir, "rev-parse", "HEAD")

        github_client = Mock()
        github_client.get_pr_title = AsyncMock(return_value=None)
        tracker = _make_tracker(
            _mock_analyzer(), _mock_git(tmp_path, commit), github_client
        )
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.RFC)
        assert len(reports) == 1
        assert reports[0].title == "Complex Numbers"

    async def test_pr_title_error_does_not_block(self, db, tmp_path: Path):
        repo_dir = self._make_rfc_repo(tmp_path)
        commit = _git(repo_dir, "rev-parse", "HEAD")

        github_client = Mock()
        github_client.get_pr_title = AsyncMock(
            side_effect=Exception("network failure")
        )
        tracker = _make_tracker(
            _mock_analyzer(), _mock_git(tmp_path, commit), github_client
        )
        tracker._clone_or_update = _async_return(repo_dir)

        reports = await tracker.check(ProposalKind.RFC)
        assert len(reports) == 1
        assert reports[0].title == "Complex Numbers"


class TestLanguagePropagation:
    async def test_configured_language_reaches_analysis_prompt(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        analyzer = _mock_analyzer()
        analyzer.analyze = AsyncMock(return_value=("summary", "detail"))
        tracker = ProposalTracker(
            analyzer=analyzer,
            git_client=_mock_git(tmp_path, commit),
            clock=lambda: datetime.now(ZoneInfo("UTC")),
            language="zh",
        )
        tracker._clone_or_update = _async_return(repo_dir)

        await tracker.check(ProposalKind.EIP)

        prompt = analyzer.analyze.call_args.kwargs["prompt"]
        assert 'language is "zh"' in prompt

    async def test_default_language_is_english(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Draft\n---\n\nBody\n"
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        analyzer = _mock_analyzer()
        analyzer.analyze = AsyncMock(return_value=("summary", "detail"))
        tracker = _make_tracker(analyzer, _mock_git(tmp_path, commit))
        tracker._clone_or_update = _async_return(repo_dir)

        await tracker.check(ProposalKind.EIP)

        prompt = analyzer.analyze.call_args.kwargs["prompt"]
        assert 'language is "en"' in prompt


class TestCloneFailure:
    async def test_clone_failure_reports_error_and_reraises(
        self, db, tmp_path: Path, monkeypatch
    ):
        from progress.errors import GitException

        analyzer = _mock_analyzer()
        tracker = _make_tracker(analyzer, _mock_git(tmp_path, "abc"))
        tracker._clone_or_update = AsyncMock(side_effect=GitException("exit status 128"))

        reported = []
        monkeypatch.setattr(
            "progress.contrib.proposal.tracker.report_error",
            lambda exc, **tags: reported.append((exc, tags)),
        )

        with pytest.raises(GitException):
            await tracker.check(ProposalKind.ERC)

        assert len(reported) == 1
        assert isinstance(reported[0][0], GitException)
        assert reported[0][1]["kind"] == "erc"
        assert reported[0][1]["stage"] == "clone"


def test_erc_tracker_branch_is_master():
    """ethereum/ercs default branch is master, not main (clone exit 128 regression)."""
    from progress.contrib.proposal.types import KIND_CONFIGS

    assert KIND_CONFIGS[ProposalKind.ERC].branch == "master"


class TestCloneOrUpdateSelfHeal:
    """_clone_or_update recovers from a corrupt HEAD (refs/heads/.invalid).

    Reproduces the prod erc-tracker failure: fetch_and_reset leaves the on-disk
    HEAD pointing at GitPython's ``.invalid`` placeholder, and the next
    get_current_commit raises ValueError on every run. The fix re-clones.
    """

    def _make_remote(self, tmp_path: Path) -> Path:
        remote = tmp_path / "remote"
        remote.mkdir()
        _git(remote, "init", "-b", "master", "--bare")
        work = tmp_path / "work"
        work.mkdir()
        _git(work, "init", "-b", "master")
        _git(work, "config", "user.email", "test@example.com")
        _git(work, "config", "user.name", "test")
        (work / "ERCS" / "erc-1.md").parent.mkdir(parents=True)
        (work / "ERCS" / "erc-1.md").write_text(
            "---\nern: 1\ntitle: T\nstatus: Draft\n---\n\nBody\n", encoding="utf-8"
        )
        _git(work, "add", ".")
        _git(work, "commit", "-m", "init")
        _git(work, "remote", "add", "origin", str(remote))
        _git(work, "push", "-q", "origin", "master")
        return remote

    def _erc_config(self, remote: Path):
        from progress.contrib.proposal.types import KindConfig

        return KindConfig(
            repo_url=str(remote),
            branch="master",
            proposal_dir="ERCS",
            file_pattern=["erc-*.md"],
        )

    def _corrupt_head(self, repo_path: Path) -> None:
        git_dir = repo_path / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        (git_dir / "refs" / "heads" / ".invalid").write_text(
            _git(repo_path, "rev-parse", "HEAD"), encoding="utf-8"
        )
        (git_dir / "HEAD").write_text("ref: refs/heads/.invalid\n", encoding="utf-8")

    async def test_re_clones_when_head_is_corrupt(self, db, tmp_path: Path):
        from progress.git import GitClient

        remote = self._make_remote(tmp_path)
        git_client = GitClient(workspace_dir=str(tmp_path / "ws"), timeout=30)
        config = self._erc_config(remote)
        tracker = _make_tracker(_mock_analyzer(), git_client)

        repo_path = await tracker._clone_or_update(config)
        self._corrupt_head(repo_path)
        with pytest.raises(ValueError):
            await git_client.get_current_commit(repo_path)

        returned = await tracker._clone_or_update(config)

        assert returned == repo_path
        assert await git_client.get_current_commit(repo_path) == _git(
            repo_path, "rev-parse", "HEAD"
        )

    async def test_healthy_clone_is_reused(self, db, tmp_path: Path):
        from progress.git import GitClient

        remote = self._make_remote(tmp_path)
        git_client = GitClient(workspace_dir=str(tmp_path / "ws"), timeout=30)
        config = self._erc_config(remote)
        tracker = _make_tracker(_mock_analyzer(), git_client)

        first = await tracker._clone_or_update(config)
        first_commit = await git_client.get_current_commit(first)
        second = await tracker._clone_or_update(config)

        assert second == first
        assert await git_client.get_current_commit(second) == first_commit
