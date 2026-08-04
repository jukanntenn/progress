"""Unit tests for the repo commit diff decision tree (spec repo §5).

Covers the bad-object handling in ``_incremental_diff``: with full-history
clones ``old_hash`` is always local, so a missing-object error indicates a
corrupted clone and must propagate (not fall back to first-run, which would
pollute the checkpoint).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from progress.errors import CommandException
from progress.integrations.repo.commit import (
    MAX_INCREMENTAL_COMMITS,
    _fetch_and_reset,
    _incremental_diff,
)

if TYPE_CHECKING:
    from pathlib import Path


async def test_fetch_and_reset_unshallows_shallow_clone(tmp_path: Path) -> None:
    """_fetch_and_reset detects a shallow clone and calls unshallow."""
    dest = tmp_path / "repo"
    dest.mkdir()
    (dest / ".git").mkdir()

    with (
        patch("progress.integrations.repo.commit.fetch", new=AsyncMock()),
        patch("progress.integrations.repo.commit.reset_hard", new=AsyncMock()),
        patch("progress.integrations.repo.commit.get_head_commit", new=AsyncMock(return_value="abc123")),
        patch("progress.integrations.repo.commit.is_shallow_repository", new=AsyncMock(return_value=True)),
        patch("progress.integrations.repo.commit.unshallow", new=AsyncMock()) as unshallow_mock,
    ):
        await _fetch_and_reset(dest)

    unshallow_mock.assert_awaited_once_with(dest)


async def test_fetch_and_reset_skips_unshallow_for_full_clone(tmp_path: Path) -> None:
    """_fetch_and_reset does not call unshallow when the clone is already full-history."""
    dest = tmp_path / "repo"
    dest.mkdir()
    (dest / ".git").mkdir()

    with (
        patch("progress.integrations.repo.commit.fetch", new=AsyncMock()),
        patch("progress.integrations.repo.commit.reset_hard", new=AsyncMock()),
        patch("progress.integrations.repo.commit.get_head_commit", new=AsyncMock(return_value="abc123")),
        patch("progress.integrations.repo.commit.is_shallow_repository", new=AsyncMock(return_value=False)),
        patch("progress.integrations.repo.commit.unshallow", new=AsyncMock()) as unshallow_mock,
    ):
        await _fetch_and_reset(dest)

    unshallow_mock.assert_not_awaited()


async def test_fetch_and_reset_continues_when_unshallow_fails(tmp_path: Path) -> None:
    """If unshallow fails, _fetch_and_reset still returns (degrades, not crashes)."""
    dest = tmp_path / "repo"
    dest.mkdir()
    (dest / ".git").mkdir()

    with (
        patch("progress.integrations.repo.commit.fetch", new=AsyncMock()),
        patch("progress.integrations.repo.commit.reset_hard", new=AsyncMock()),
        patch("progress.integrations.repo.commit.get_head_commit", new=AsyncMock(return_value="abc123")),
        patch("progress.integrations.repo.commit.is_shallow_repository", new=AsyncMock(return_value=True)),
        patch(
            "progress.integrations.repo.commit.unshallow",
            new=AsyncMock(side_effect=CommandException("unshallow failed")),
        ),
    ):
        await _fetch_and_reset(dest)


async def test_incremental_diff_raises_on_bad_object_for_full_clone(tmp_path: Path) -> None:
    """A missing old object on a full clone indicates corruption; must raise."""
    dest = tmp_path / "repo"

    async def _boom(*args, **kwargs):
        raise CommandException("git diff abc..def failed (exit=128): fatal: bad object abc123")

    with (
        patch("progress.integrations.repo.commit.get_diff", new=_boom),
        patch(
            "progress.integrations.repo.commit._first_run_diff",
            new=AsyncMock(return_value=None),
        ) as first_run_mock,
        pytest.raises(CommandException),
    ):
        await _incremental_diff(
            dest=dest,
            old_hash="abc123",
            new_hash="newtip",
            lookback=5,
        )

    first_run_mock.assert_not_awaited()


async def test_incremental_diff_reraises_non_missing_object_errors(tmp_path: Path) -> None:
    """A generic git failure (not 'bad object') must propagate, not silently fall back."""
    dest = tmp_path / "repo"

    async def _boom(*args, **kwargs):
        raise CommandException("git diff failed (exit=1): some other error")

    with (
        patch("progress.integrations.repo.commit.get_diff", new=_boom),
        patch(
            "progress.integrations.repo.commit._first_run_diff",
            new=AsyncMock(return_value=None),
        ) as first_run_mock,
        pytest.raises(CommandException),
    ):
        await _incremental_diff(
            dest=dest,
            old_hash="abc123",
            new_hash="newtip",
            lookback=5,
        )

    first_run_mock.assert_not_awaited()


def test_max_incremental_commits_constant() -> None:
    assert MAX_INCREMENTAL_COMMITS == 50


async def test_incremental_diff_no_cap_when_within_limit(tmp_path: Path) -> None:
    """At or below MAX_INCREMENTAL_COMMITS the full old_hash..HEAD range is used."""
    dest = tmp_path / "repo"
    within = MAX_INCREMENTAL_COMMITS

    with (
        patch("progress.integrations.repo.commit.get_diff", new=AsyncMock(return_value="FULL")),
        patch(
            "progress.integrations.repo.commit.get_commit_messages",
            new=AsyncMock(return_value="messages"),
        ),
        patch(
            "progress.integrations.repo.commit.get_commit_count",
            new=AsyncMock(return_value=within),
        ) as count_mock,
        patch(
            "progress.integrations.repo.commit.get_total_commit_count",
            new=AsyncMock(),
        ) as total_mock,
        patch(
            "progress.integrations.repo.commit.get_commit_hash_at",
            new=AsyncMock(),
        ) as hash_at_mock,
    ):
        result = await _incremental_diff(
            dest=dest,
            old_hash="abc123",
            new_hash="newtip",
            lookback=5,
        )

    assert result is not None
    assert result.commit_count == within
    assert result.diff == "FULL"
    assert result.previous_commit == "abc123"
    count_mock.assert_awaited_once()
    total_mock.assert_not_awaited()
    hash_at_mock.assert_not_awaited()


async def test_incremental_diff_caps_burst_above_limit(tmp_path: Path) -> None:
    """A burst exceeding MAX_INCREMENTAL_COMMITS is truncated to the most recent N."""
    dest = tmp_path / "repo"
    burst = MAX_INCREMENTAL_COMMITS + 205
    start_hash = "start" + "0" * 10

    with (
        patch(
            "progress.integrations.repo.commit.get_diff",
            new=AsyncMock(return_value="FULL_RANGE_UNUSED"),
        ),
        patch(
            "progress.integrations.repo.commit.get_commit_messages",
            new=AsyncMock(return_value="full_messages"),
        ),
        patch(
            "progress.integrations.repo.commit.get_commit_count",
            new=AsyncMock(side_effect=[burst, MAX_INCREMENTAL_COMMITS]),
        ),
        patch(
            "progress.integrations.repo.commit.get_total_commit_count",
            new=AsyncMock(return_value=burst),
        ),
        patch(
            "progress.integrations.repo.commit.get_commit_hash_at",
            new=AsyncMock(return_value=start_hash),
        ) as hash_at_mock,
        patch(
            "progress.integrations.repo.commit.get_commit_diff_range",
            new=AsyncMock(return_value="CAPPED"),
        ) as range_diff_mock,
        patch("progress.integrations.repo.commit.record_business_event") as event_mock,
    ):
        result = await _incremental_diff(
            dest=dest,
            old_hash="abc123",
            new_hash="newtip",
            lookback=5,
        )

    assert result is not None
    assert result.commit_count == MAX_INCREMENTAL_COMMITS
    assert result.diff == "CAPPED"
    assert result.previous_commit == start_hash
    hash_at_mock.assert_awaited_once_with(dest, f"HEAD~{MAX_INCREMENTAL_COMMITS}")
    range_diff_mock.assert_awaited_once_with(dest, start_hash, "newtip")
    event_mock.assert_called_once()
    assert event_mock.call_args.args[0] == "progress.git.incremental_capped"
    assert event_mock.call_args.kwargs["attributes"]["total_commits"] == str(burst)
