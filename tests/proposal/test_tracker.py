import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
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
    analyzer.analyze = Mock(return_value=('{"summary": "s", "detail": "d"}'))
    for k, v in overrides.items():
        setattr(analyzer, k, v)
    return analyzer


def _mock_git(tmp_path, commit, **overrides):
    git_client = Mock()
    git_client.workspace_dir = tmp_path / "ws"
    git_client.get_current_commit = Mock(return_value=commit)
    git_client.get_changed_file_statuses = Mock(return_value=[])
    git_client.get_file_creation_date = Mock(return_value="2024-01-01 00:00:00 +0000")
    git_client.fetch_and_reset = Mock()
    git_client.get_file_diff = Mock(return_value="")
    git_client.timeout = 30
    for k, v in overrides.items():
        setattr(git_client, k, v if isinstance(v, Mock) else Mock(return_value=v))
    return git_client


def _make_tracker(analyzer, git_client):
    return ProposalTracker(
        analyzer=analyzer,
        git_client=git_client,
        clock=lambda: datetime.now(ZoneInfo("UTC")),
    )


@pytest.fixture()
def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    create_tables()
    yield
    close_db()


class TestInitialCheck:
    def test_saves_all_proposals_to_db(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Draft\n---\n\nBody\n",
                "EIPS/eip-2.md": "---\neip: 2\ntitle: Another EIP\nstatus: Final\n---\n\nBody\n",
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        reports = tracker.check(ProposalKind.EIP)

        assert len(reports) == 1
        assert Proposal.select().count() == 2

        state = ProposalTrackerState.get(ProposalTrackerState.kind == "eip")
        assert state.last_seen_commit == commit

    def test_returns_one_verification_report(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "text/0001-a.md": "# A\n\n- Feature Name: a\n",
                "text/0002-b.md": "# B\n\n- Feature Name: b\n",
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        reports = tracker.check(ProposalKind.RFC)
        assert len(reports) == 1

    def test_empty_repo_returns_no_reports(self, db, tmp_path: Path):
        repo_dir = _make_repo(tmp_path, {"README.md": "# README\n"})
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        reports = tracker.check(ProposalKind.RFC)
        assert len(reports) == 0

    def test_updates_last_seen_commit(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {"EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"},
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        tracker.check(ProposalKind.EIP)

        state = ProposalTrackerState.get(ProposalTrackerState.kind == "eip")
        assert state.last_seen_commit == commit


class TestIncrementalCheck:
    def test_detect_status_change_draft_to_final(self, db, tmp_path: Path):
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
        tracker._clone_or_update = lambda config: repo_dir
        tracker.check(ProposalKind.EIP)

        (repo_dir / "EIPS" / "eip-1.md").write_text(
            "---\neip: 1\ntitle: Test EIP\nstatus: Final\ntype: Standards Track\n---\n\nBody changed\n",
            encoding="utf-8",
        )
        _git(repo_dir, "add", "EIPS/eip-1.md")
        _git(repo_dir, "commit", "-m", "update status")
        commit2 = _git(repo_dir, "rev-parse", "HEAD")

        git_client.get_current_commit = Mock(return_value=commit2)
        git_client.get_changed_file_statuses = Mock(
            return_value=[("M", "EIPS/eip-1.md")]
        )

        reports = tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].new_status.value == "final"

    def test_no_change_same_commit_returns_empty(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {"EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"},
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        tracker.check(ProposalKind.EIP)
        reports2 = tracker.check(ProposalKind.EIP)
        assert len(reports2) == 0


class TestDeletedFile:
    def test_nonterminal_becomes_withdrawn(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Draft\n---\n\nBody\n"
            },
        )
        commit1 = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit1))
        tracker._clone_or_update = lambda config: repo_dir
        tracker.check(ProposalKind.EIP)

        _git(repo_dir, "rm", "EIPS/eip-1.md")
        _git(repo_dir, "commit", "-m", "delete eip")
        commit2 = _git(repo_dir, "rev-parse", "HEAD")

        git_client = tracker.git
        git_client.get_current_commit = Mock(return_value=commit2)
        git_client.get_changed_file_statuses = Mock(
            return_value=[("D", "EIPS/eip-1.md")]
        )

        reports = tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].new_status.value == "withdrawn"

    def test_terminal_no_status_change(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "EIPS/eip-1.md": "---\neip: 1\ntitle: Test EIP\nstatus: Final\n---\n\nBody\n"
            },
        )
        commit1 = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit1))
        tracker._clone_or_update = lambda config: repo_dir
        tracker.check(ProposalKind.EIP)

        _git(repo_dir, "rm", "EIPS/eip-1.md")
        _git(repo_dir, "commit", "-m", "delete eip")
        commit2 = _git(repo_dir, "rev-parse", "HEAD")

        git_client = tracker.git
        git_client.get_current_commit = Mock(return_value=commit2)
        git_client.get_changed_file_statuses = Mock(
            return_value=[("D", "EIPS/eip-1.md")]
        )

        reports = tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].new_status.value == "final"

    def test_unknown_file_returns_none(self, db, tmp_path: Path):
        repo_dir = _make_repo(tmp_path, {"README.md": "# Hello\n"})
        commit = _git(repo_dir, "rev-parse", "HEAD")

        state = ProposalTrackerState.create(kind="eip", last_seen_commit=commit)

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))

        from progress.contrib.proposal.parser import EIPParser

        result = tracker._handle_deleted(
            ProposalKind.EIP, state, EIPParser(), "EIPS/eip-999.md", commit
        )
        assert result is None


class TestErrorHandling:
    def test_parse_error_skipped_gracefully(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {
                "peps/pep-bad.rst": "PEP: TBD\nTitle: Bad\nStatus: Draft\n\nBody\n",
            },
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        tracker = _make_tracker(_mock_analyzer(), _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        reports = tracker.check(ProposalKind.PEP)
        assert len(reports) == 0

    def test_analysis_failure_does_not_block_check(self, db, tmp_path: Path):
        repo_dir = _make_repo(
            tmp_path,
            {"EIPS/eip-1.md": "---\neip: 1\ntitle: Test\nstatus: Draft\n---\n\nBody\n"},
        )
        commit = _git(repo_dir, "rev-parse", "HEAD")

        analyzer = _mock_analyzer(
            analyze=Mock(side_effect=Exception("AI service unavailable"))
        )
        tracker = _make_tracker(analyzer, _mock_git(tmp_path, commit))
        tracker._clone_or_update = lambda config: repo_dir

        reports = tracker.check(ProposalKind.EIP)
        assert len(reports) == 1
        assert reports[0].analysis_summary is None
