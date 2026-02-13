import subprocess
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from progress.db import close_db, create_tables, init_db
from progress.contrib.proposal.models import EIP, ProposalEvent, ProposalTracker
from progress.contrib.proposal.proposal_tracking import ProposalTrackerManager
from progress.config import ProposalTrackerConfig


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


@pytest.fixture()
def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    create_tables()
    yield
    close_db()


def test_proposal_tracker_initial_and_incremental(db, tmp_path: Path):
    repo_dir = tmp_path / "proposal-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "test")

    eip_file = repo_dir / "eip-1.md"
    eip_file.write_text(
        """---
eip: 1
title: Test EIP
status: Draft
type: Standards Track
category: Core
author: Alice
created: 2024-01-02
---

# Body
""",
        encoding="utf-8",
    )
    _git(repo_dir, "add", "eip-1.md")
    _git(repo_dir, "commit", "-m", "add eip")
    first_commit = _git(repo_dir, "rev-parse", "HEAD")
    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")

    tracker = ProposalTracker.create(
        tracker_type="eip",
        repo_url=str(repo_dir),
        branch=branch,
        enabled=True,
        proposal_dir="",
        file_pattern="eip-*.md",
    )

    cfg = Mock()
    cfg.github = Mock(git_timeout=30)
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    analyzer = Mock()
    analyzer.analyze_proposal = Mock(return_value=("summary", "detail"))

    manager = ProposalTrackerManager(analyzer, cfg)
    manager.git.workspace_dir = tmp_path / "ws"

    reports = manager.check(tracker)
    assert reports
    assert analyzer.analyze_proposal.called
    eip = EIP.select().where(EIP.eip_number == 1).first()
    assert eip is not None
    assert eip.file_path == "eip-1.md"
    assert ProposalEvent.select().count() >= 1

    eip_file.write_text(
        """---
eip: 1
title: Test EIP
status: Final
type: Standards Track
category: Core
author: Alice
created: 2024-01-02
---

# Body changed
""",
        encoding="utf-8",
    )
    _git(repo_dir, "add", "eip-1.md")
    _git(repo_dir, "commit", "-m", "update status")
    second_commit = _git(repo_dir, "rev-parse", "HEAD")

    tracker.last_seen_commit = first_commit
    tracker.save()

    reports2 = manager.check(tracker)
    assert any(r.new_status == "Final" for r in reports2)
    assert tracker.last_seen_commit == second_commit


def test_initial_check_datetime_compare_is_timezone_safe(
    db, tmp_path: Path, monkeypatch
):
    repo_dir = tmp_path / "proposal-repo-dt"
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "test")

    f1 = repo_dir / "0001-a.md"
    f1.write_text("# A\nStatus: Draft\n", encoding="utf-8")
    _git(repo_dir, "add", "0001-a.md")
    _git(repo_dir, "commit", "-m", "add a")

    f2 = repo_dir / "0002-b.md"
    f2.write_text("# B\nStatus: Draft\n", encoding="utf-8")
    _git(repo_dir, "add", "0002-b.md")
    _git(repo_dir, "commit", "-m", "add b")

    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")

    tracker = ProposalTracker.create(
        tracker_type="rust_rfc",
        repo_url=str(repo_dir),
        branch=branch,
        enabled=True,
        proposal_dir="",
        file_pattern="*.md",
    )

    cfg = Mock()
    cfg.github = Mock(git_timeout=30)
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    analyzer = Mock()
    analyzer.analyze_proposal = Mock(return_value=("summary", "detail"))
    manager = ProposalTrackerManager(analyzer, cfg)
    manager.git.workspace_dir = tmp_path / "ws-dt"

    original = manager.git.get_file_creation_date

    def wrapped(repo_path: Path, file_path: str):
        if file_path.endswith("0001-a.md"):
            return "bad-date"
        return original(repo_path, file_path)

    monkeypatch.setattr(manager.git, "get_file_creation_date", wrapped)

    manager.check(tracker)


def test_initial_check_emits_single_example_event(db, tmp_path: Path):
    repo_dir = tmp_path / "proposal-repo-many"
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "test")

    for i in range(1, 6):
        p = repo_dir / f"{i:04d}-rfc.md"
        p.write_text(f"# RFC {i}\nStatus: Draft\n", encoding="utf-8")
        _git(repo_dir, "add", p.name)
        _git(repo_dir, "commit", "-m", f"add {i}")

    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")

    tracker = ProposalTracker.create(
        tracker_type="rust_rfc",
        repo_url=str(repo_dir),
        branch=branch,
        enabled=True,
        proposal_dir="",
        file_pattern="*.md",
    )

    cfg = Mock()
    cfg.github = Mock(git_timeout=30)
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    analyzer = Mock()
    analyzer.analyze_proposal = Mock(return_value=("summary", "detail"))
    manager = ProposalTrackerManager(analyzer, cfg)
    manager.git.workspace_dir = tmp_path / "ws-many"

    reports = manager.check(tracker)
    assert len(reports) == 1
    assert ProposalEvent.select().count() == 1


def test_pep_tracker_skips_invalid_pep_header_value(db, tmp_path: Path):
    repo_dir = tmp_path / "pep-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "test")

    peps_dir = repo_dir / "peps"
    peps_dir.mkdir()

    bad = peps_dir / "pep-9999.rst"
    bad.write_text(
        """PEP: TBD
Title: Bad PEP
Status: Draft

Body
""",
        encoding="utf-8",
    )
    good = peps_dir / "pep-0001.rst"
    good.write_text(
        """PEP: 1
Title: Good PEP
Status: Draft

Body
""",
        encoding="utf-8",
    )

    _git(repo_dir, "add", "peps/pep-9999.rst", "peps/pep-0001.rst")
    _git(repo_dir, "commit", "-m", "add peps")

    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    tracker = ProposalTracker.create(
        tracker_type="pep",
        repo_url=str(repo_dir),
        branch=branch,
        enabled=True,
        proposal_dir="peps",
        file_pattern="pep-*.rst",
    )

    cfg = Mock()
    cfg.github = Mock(git_timeout=30)
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    analyzer = Mock()
    analyzer.analyze_proposal = Mock(return_value=("summary", "detail"))
    manager = ProposalTrackerManager(analyzer, cfg)
    manager.git.workspace_dir = tmp_path / "ws-pep"

    reports = manager.check(tracker)
    assert len(reports) == 1
    assert reports[0].proposal_number == 1


def test_proposal_tracker_sync(db, tmp_path: Path):
    cfg = Mock()
    cfg.github = Mock(git_timeout=30)
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    analyzer = Mock()
    manager = ProposalTrackerManager(analyzer, cfg)

    trackers = [
        ProposalTrackerConfig(
            type="eip",
            repo_url="https://github.com/ethereum/EIPs.git",
            branch="master",
            enabled=True,
            proposal_dir="EIPS",
            file_pattern="eip-*.md",
        )
    ]
    result = manager.sync(trackers)
    assert result["created"] == 1
    assert ProposalTracker.select().count() == 1

    trackers2 = [
        ProposalTrackerConfig(
            type="eip",
            repo_url="https://github.com/ethereum/EIPs.git",
            branch="master",
            enabled=False,
            proposal_dir="EIPS",
            file_pattern="eip-*.md",
        )
    ]
    result2 = manager.sync(trackers2)
    assert result2["updated"] == 1
    assert ProposalTracker.select().count() == 1


def test_proposal_tracker_parse_error_logged(db, tmp_path: Path):
    repo_dir = tmp_path / "proposal-repo-bad"
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "test")

    eip_file = repo_dir / "eip-1.md"
    eip_file.write_text("---\neip: 1\n---\n", encoding="utf-8")
    _git(repo_dir, "add", "eip-1.md")
    _git(repo_dir, "commit", "-m", "add bad eip")
    first_commit = _git(repo_dir, "rev-parse", "HEAD")
    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")

    tracker = ProposalTracker.create(
        tracker_type="eip",
        repo_url=str(repo_dir),
        branch=branch,
        enabled=True,
        proposal_dir="",
        file_pattern="eip-*.md",
    )

    cfg = Mock()
    cfg.github = Mock(git_timeout=30)
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    analyzer = Mock()
    analyzer.analyze_proposal = Mock(return_value=("summary", "detail"))

    manager = ProposalTrackerManager(analyzer, cfg)
    manager.git.workspace_dir = tmp_path / "ws2"

    manager.check(tracker)

    eip_file.write_text("---\neip: 1\n---\ninvalid\n", encoding="utf-8")
    _git(repo_dir, "add", "eip-1.md")
    _git(repo_dir, "commit", "-m", "modify bad eip")
    tracker.last_seen_commit = first_commit
    tracker.save()

    before = ProposalEvent.select().count()
    manager.check(tracker)
    after = ProposalEvent.select().count()
    assert after >= before
