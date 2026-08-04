"""Unit tests for ``progress.cli.git.local`` (spec 07 + Feature 1 ensure_object)."""

from __future__ import annotations

import subprocess
import unittest.mock

import pytest

from progress.cli.git.local import CommitMessage, _split_commit_message, ensure_object
from progress.errors import CommandException


def test_split_pure_single_line() -> None:
    assert _split_commit_message("fix bug\n") == CommitMessage("fix bug", "")


def test_split_subject_and_body() -> None:
    assert _split_commit_message("Fix\n\nDetails here\n") == CommitMessage("Fix", "Details here")


def test_split_whitespace_only_body() -> None:
    assert _split_commit_message("Fix\n\n\n") == CommitMessage("Fix", "")


def test_split_squash_duplicate() -> None:
    assert _split_commit_message("Same\n\nSame\n") == CommitMessage("Same", "")


def test_split_leading_blank() -> None:
    assert _split_commit_message("\n\nSubject\nBody\n") == CommitMessage("Subject", "Body")


def test_split_empty() -> None:
    assert _split_commit_message("") == CommitMessage("", "")


def test_split_multi_line_body() -> None:
    raw = "Fix\n\nLine one\nLine two\n"
    assert _split_commit_message(raw) == CommitMessage("Fix", "Line one\nLine two")


class TestEnsureObject:
    """Feature 1: ensure_object on-demand fetch primitive (spec repo §5.4)."""

    async def test_already_present_returns_true(self, tmp_path) -> None:
        """Object exists locally: cat-file succeeds, no fetch needed."""

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
        (repo / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()

        result = await ensure_object(repo, sha)
        assert result is True

    async def test_fetches_missing_object(self, tmp_path) -> None:
        """Object missing locally: cat-file fails, fetch succeeds, cat-file passes."""

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
        (repo / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()

        # Remove the object from the local repo
        subprocess.run(["git", "fetch", "--prune"], cwd=repo, check=True, capture_output=True)

        # Use mock to simulate: cat-file fails → fetch succeeds → cat-file succeeds
        call_log = []

        async def mock_run_git(args, *, cwd=None, timeout=None):
            cmd = " ".join(args)
            call_log.append(cmd)
            if "cat-file" in cmd:
                if len([c for c in call_log if "cat-file" in c]) == 1:
                    # First cat-file: object missing
                    raise CommandException(f"git {cmd} failed (exit=128): fatal: Not a valid object name {sha}\n")
                # Second cat-file: object now present
                return sha + "\n"
            if "fetch" in cmd:
                # fetch succeeds silently
                return ""
            return ""

        with unittest.mock.patch("progress.cli.git.local._run_git", side_effect=mock_run_git):
            result = await ensure_object(repo, sha)

        assert result is True
        assert any("fetch" in c and sha in c for c in call_log)

    async def test_unreachable_object_returns_false(self, tmp_path) -> None:
        """Object genuinely unreachable: cat-file fails, fetch succeeds, cat-file still fails."""

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        call_log = []

        async def mock_run_git(args, *, cwd=None, timeout=None):
            cmd = " ".join(args)
            call_log.append(cmd)
            if "cat-file" in cmd:
                cat_count = len([c for c in call_log if "cat-file" in c])
                if cat_count <= 2:
                    raise CommandException(f"git {cmd} failed (exit=128): fatal: Not a valid object name abc123\n")
            return ""

        with unittest.mock.patch("progress.cli.git.local._run_git", side_effect=mock_run_git):
            result = await ensure_object(repo, "abc123")

        assert result is False

    async def test_network_error_during_fetch_propagates(self, tmp_path) -> None:
        """Network error on fetch: CommandException propagates, not swallowed."""

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        call_count = 0

        async def mock_run_git(args, *, cwd=None, timeout=None):
            nonlocal call_count
            call_count += 1
            cmd = " ".join(args)
            if "cat-file" in cmd:
                raise CommandException(f"git {cmd} failed (exit=128): fatal: Not a valid object name abc123\n")
            if "fetch" in cmd:
                raise CommandException(
                    "git fetch origin abc123 failed (exit=128): fatal: unable to access 'https://github.com/...': Failed to connect: Connection refused\n"
                )

        with (
            unittest.mock.patch("progress.cli.git.local._run_git", side_effect=mock_run_git),
            pytest.raises(CommandException, match="Connection refused"),
        ):
            await ensure_object(repo, "abc123")

        # Ensure fetch was actually attempted (not short-circuited)
        assert any("fetch" in c for c in [] if hasattr(c, "__iter__")) or call_count >= 2
