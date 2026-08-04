"""Commit tracking logic for the repo integration (spec repo §5).

The commit checkpoint and release checkpoint are intentionally orthogonal
(spec repo §2). This module owns only the commit side:

1. clone/fetch the repo (with 3 retries on clone failure, spec §5.1)
2. compute the diff decision tree (spec §5.2):
   - HEAD unchanged → no new commits
   - first run → range or recent strategy (spec §5.3)
   - incremental → checkpoint..HEAD diff, capped at MAX_INCREMENTAL_COMMITS (spec §5.4)
3. return a unified :class:`DiffResult` (or ``None`` for no new commits)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil

from progress.cli.git import (
    CommitMessage,
    RepoRef,
    build_authenticated_clone_url,
    cleanup_git_locks,
    clone,
    ensure_object,
    fetch,
    get_commit_count,
    get_commit_diff_range,
    get_commit_hash_at,
    get_commit_messages,
    get_diff,
    get_head_commit,
    get_recent_n_commit_hashes,
    get_total_commit_count,
    is_shallow_repository,
    reset_hard,
    unshallow,
)
from progress.errors import GitException, ProgressException
from progress.observability import record_business_event

logger = logging.getLogger(__name__)

CLONE_RETRIES: int = 3
CLONE_BACKOFF_BASE_SECONDS: float = 3.0
GIT_LOCK_RETRIES: int = 3
GIT_LOCK_BACKOFF_BASE_SECONDS: float = 2.0
MAX_INCREMENTAL_COMMITS: int = 50

_CORRUPT_HEAD_MARKER = ".invalid"


class CorruptHeadError(GitException):
    """Raised when HEAD is corrupt/empty, signaling clone_or_fetch to reclone."""


async def _remove_tree(path: Path) -> None:
    """Remove a directory tree off the event loop (mirrors proposal's _rmtree)."""

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, shutil.rmtree, str(path), True)


@dataclass
class DiffResult:
    """Unified diff result for one repo (spec repo §5.5)."""

    diff: str
    previous_commit: str
    commit_count: int
    commit_messages: list[CommitMessage] = field(default_factory=list)
    is_range_check: bool = True


async def clone_or_fetch(
    *,
    ref: RepoRef,
    dest: Path,
    branch: str,
    token: str,
    state_home: str,
    lookback: int = 3,
) -> None:
    """Clone (first time) or fetch+reset (subsequent runs) — spec repo §5.1.

    Uses full-history clones (``depth=None``) so the incremental diff
    checkpoint (``old_hash``) is always local and never garbage-collected.
    Incremental fetches are unbounded (no ``--depth``). This mirrors the
    proposal integration's clone strategy.

    Clone failures are retried up to :data:`CLONE_RETRIES` times with
    exponential backoff (3s, 6s, ...). If fetch+reset leaves a corrupt HEAD
    (mirroring the proposal integration's self-heal), the clone is removed and
    re-cloned. On final failure raises :class:`GitException`.
    """
    clone_url = build_authenticated_clone_url(ref.owner, ref.name, token)
    if dest.exists() and (dest / ".git").is_dir():
        try:
            await _fetch_and_reset(dest)
            return
        except CorruptHeadError:
            logger.warning("corrupt HEAD detected for %s; recloning", ref.slug)
            await _remove_tree(dest)
    last_error: Exception | None = None
    for attempt in range(CLONE_RETRIES):
        try:
            await clone(clone_url, dest, branch=branch or None, depth=None)
            return
        except (ProgressException, Exception) as e:
            last_error = e
            if attempt + 1 < CLONE_RETRIES:
                delay = CLONE_BACKOFF_BASE_SECONDS * (2**attempt)
                logger.warning(
                    "clone attempt %d/%d failed for %s: %s; retrying in %.1fs",
                    attempt + 1,
                    CLONE_RETRIES,
                    ref.slug,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
    raise GitException(f"clone failed for {ref.slug} after {CLONE_RETRIES} attempts: {last_error}")


async def _fetch_and_reset(dest: Path) -> None:
    """Fetch + reset to origin, with git lock + corrupt-HEAD self-heal.

    After a successful fetch+reset the HEAD is validated: an empty/garbage HEAD
    (e.g. a leftover ``.invalid`` placeholder from an interrupted clone, or a
    ``git rev-parse HEAD`` that fails outright) raises :class:`CorruptHeadError`
    so :func:`clone_or_fetch` can remove the clone and start fresh (mirroring
    the proposal integration's self-heal).
    """
    last_error: Exception | None = None
    for attempt in range(GIT_LOCK_RETRIES):
        try:
            await fetch(dest)
            await reset_hard(dest, "FETCH_HEAD")
        except (ProgressException, Exception) as e:
            last_error = e
            stringified = str(e).lower()
            if "lock" in stringified or ".git/*.lock" in stringified or "another git process" in stringified:
                await cleanup_git_locks(dest)
                if attempt + 1 < GIT_LOCK_RETRIES:
                    delay = GIT_LOCK_BACKOFF_BASE_SECONDS * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
            raise
        try:
            head = await get_head_commit(dest)
        except ProgressException as e:
            raise CorruptHeadError(f"HEAD unreadable after fetch+reset: {e}") from e
        if not head or _CORRUPT_HEAD_MARKER in head:
            raise CorruptHeadError(f"corrupt HEAD after fetch+reset: {head!r}")

        if await is_shallow_repository(dest):
            logger.info("shallow clone detected; unshallowing %s", dest.name)
            try:
                await unshallow(dest)
                record_business_event(
                    "progress.git.unshallow",
                    attributes={"repo": dest.name},
                )
            except (ProgressException, Exception) as e:
                logger.warning(
                    "unshallow failed for %s: %s; diff may fail on missing objects",
                    dest.name,
                    e,
                )
                record_business_event(
                    "progress.git.unshallow_failed",
                    attributes={"repo": dest.name, "reason": type(e).__name__},
                )
        return
    if last_error:
        raise GitException(f"fetch+reset failed after retries: {last_error}")


async def compute_diff(
    *,
    dest: Path,
    old_hash: str | None,
    lookback: int,
) -> DiffResult | None:
    """Compute the diff for one repo (spec repo §5.2 decision tree).

    Returns ``None`` when there are no new commits. Otherwise returns a
    :class:`DiffResult` with the diff text and metadata.
    """
    new_hash = await get_head_commit(dest)
    if not new_hash:
        return None
    if old_hash == new_hash:
        record_business_event(
            "progress.git.diff_decided",
            attributes={"strategy": "no_change", "old_hash": old_hash or "", "new_hash": new_hash},
        )
        return None
    if old_hash is None:
        record_business_event(
            "progress.git.diff_decided",
            attributes={"strategy": "first_run", "new_hash": new_hash, "lookback": str(lookback)},
        )
        return await _first_run_diff(dest=dest, lookback=lookback)
    record_business_event(
        "progress.git.diff_decided",
        attributes={"strategy": "incremental", "old_hash": old_hash, "new_hash": new_hash},
    )
    return await _incremental_diff(dest=dest, old_hash=old_hash, new_hash=new_hash, lookback=lookback)


async def _first_run_diff(*, dest: Path, lookback: int) -> DiffResult | None:
    """First-run strategy selection (spec repo §5.3).

    - total commits = 0 → return None
    - total > effective_lookback → range strategy (HEAD~N..HEAD)
    - total ≤ effective_lookback → recent strategy (last N commits)
    """
    total = await get_total_commit_count(dest)
    if total <= 0:
        return None
    effective_lookback = min(lookback, total)
    if total > effective_lookback:
        return await _range_strategy(dest=dest, lookback=effective_lookback, total=total)
    return await _recent_strategy(dest=dest, lookback=effective_lookback)


async def _range_strategy(*, dest: Path, lookback: int, total: int) -> DiffResult:
    """Range strategy: ``HEAD~N..HEAD`` (spec repo §5.3)."""
    start_rev = f"HEAD~{lookback}"
    start_hash = await get_commit_hash_at(dest, start_rev)
    if not start_hash:
        return await _recent_strategy(dest=dest, lookback=lookback)
    new_hash = await get_head_commit(dest)
    diff = await get_commit_diff_range(dest, start_hash, new_hash)
    messages = await get_commit_messages(dest, old_hash=start_hash, new_hash=new_hash)
    count = await get_commit_count(dest, start_hash, new_hash)
    return DiffResult(
        diff=diff,
        previous_commit=start_hash,
        commit_count=count,
        commit_messages=messages,
        is_range_check=True,
    )


async def _recent_strategy(*, dest: Path, lookback: int) -> DiffResult:
    """Recent strategy: most recent N commits (spec repo §5.3).

    Used when history is too short for ``HEAD~N`` to exist. The starting
    commit is the *oldest* of the N recent commits; ``is_range_check=False``.
    """
    hashes = await get_recent_n_commit_hashes(dest, count=lookback)
    if not hashes:
        new_hash = await get_head_commit(dest)
        return DiffResult(diff="", previous_commit=new_hash, commit_count=0)
    new_hash = hashes[0]
    oldest_hash = hashes[-1]
    diff = await get_commit_diff_range(dest, oldest_hash, new_hash)
    messages = await get_commit_messages(dest, old_hash=None, new_hash=new_hash, max_count=lookback)
    count = await get_commit_count(dest, None, new_hash)
    return DiffResult(
        diff=diff,
        previous_commit=oldest_hash,
        commit_count=count,
        commit_messages=messages,
        is_range_check=False,
    )


_BAD_OBJECT_MARKERS = (
    "bad object",
    "bad revision",
    "unknown revision",
    "could not get object info",
    "not our ref",
)


def _is_missing_object_error(exc: BaseException) -> bool:
    """True when ``exc`` indicates a git object missing from the local clone.

    After repeated shallow ``fetch --depth 1`` + ``reset --hard FETCH_HEAD`` the
    stored checkpoint (``old_hash``) can be garbage-collected, so
    ``git diff <old_hash>..HEAD`` fails with "bad object". Detecting this lets
    :func:`_incremental_diff` fall back to a HEAD-relative strategy that only
    needs objects reachable from the current tip (always local), self-healing
    the stuck checkpoint on the next run.
    """
    message = str(exc).lower()
    return any(marker in message for marker in _BAD_OBJECT_MARKERS)


async def _incremental_diff(
    *,
    dest: Path,
    old_hash: str,
    new_hash: str,
    lookback: int,
) -> DiffResult | None:
    """Incremental strategy: ``old_hash..HEAD`` capped at ``MAX_INCREMENTAL_COMMITS``.

    With full-history clones ``old_hash`` is always local. A missing-object
    error indicates a GC'd checkpoint (shallow legacy); we fetch the exact
    object on demand (GitHub allows reachable-SHA fetches) and retry. If the
    object is genuinely unreachable, raise so the caller advances the
    checkpoint. Transient network errors propagate unchanged.

    A burst that exceeds ``MAX_INCREMENTAL_COMMITS`` (e.g. a repo recovered
    after a long failure, or re-enabled after being disabled for months) is
    truncated to the most recent ``MAX_INCREMENTAL_COMMITS`` commits via
    ``HEAD~N..HEAD``; the checkpoint still advances to HEAD, accepting that
    older commits in the burst are skipped to bound AI cost and runtime.
    """
    try:
        diff = await get_diff(dest, old_hash, new_hash)
        messages = await get_commit_messages(dest, old_hash=old_hash, new_hash=new_hash)
        count = await get_commit_count(dest, old_hash, new_hash)
    except ProgressException as e:
        if not _is_missing_object_error(e):
            raise
        logger.warning("incremental diff missing old object %s; fetching on demand", old_hash)
        record_business_event(
            "progress.git.diff_failed",
            attributes={"reason": "bad_object_fetch_attempt", "old_hash": old_hash, "new_hash": new_hash},
        )
        present = await ensure_object(dest, old_hash)
        if not present:
            raise GitException(f"checkpoint object {old_hash} unreachable on remote; advancing checkpoint") from None
        diff = await get_diff(dest, old_hash, new_hash)
        messages = await get_commit_messages(dest, old_hash=old_hash, new_hash=new_hash)
        count = await get_commit_count(dest, old_hash, new_hash)

    if count <= MAX_INCREMENTAL_COMMITS:
        return DiffResult(
            diff=diff,
            previous_commit=old_hash,
            commit_count=count,
            commit_messages=messages,
            is_range_check=True,
        )

    logger.warning(
        "incremental diff for %s..%s has %d commits; capping to most recent %d",
        old_hash,
        new_hash,
        count,
        MAX_INCREMENTAL_COMMITS,
    )
    record_business_event(
        "progress.git.incremental_capped",
        attributes={
            "old_hash": old_hash,
            "new_hash": new_hash,
            "total_commits": str(count),
            "cap": str(MAX_INCREMENTAL_COMMITS),
        },
    )
    total = await get_total_commit_count(dest)
    effective = min(MAX_INCREMENTAL_COMMITS, max(total, 1))
    start_hash = await get_commit_hash_at(dest, f"HEAD~{effective}")
    if not start_hash:
        hashes = await get_recent_n_commit_hashes(dest, count=effective)
        if not hashes:
            return DiffResult(diff="", previous_commit=new_hash, commit_count=0)
        start_hash = hashes[-1]
    capped_diff = await get_commit_diff_range(dest, start_hash, new_hash)
    capped_messages = await get_commit_messages(dest, old_hash=start_hash, new_hash=new_hash)
    capped_count = await get_commit_count(dest, start_hash, new_hash)
    return DiffResult(
        diff=capped_diff,
        previous_commit=start_hash,
        commit_count=capped_count,
        commit_messages=capped_messages,
        is_range_check=True,
    )


def is_empty_diff(diff_result: DiffResult) -> bool:
    """Per spec repo §5.1, an empty diff (after strip) does not advance checkpoint."""
    return not (diff_result.diff or "").strip()


__all__ = [
    "CLONE_RETRIES",
    "MAX_INCREMENTAL_COMMITS",
    "DiffResult",
    "clone_or_fetch",
    "compute_diff",
    "is_empty_diff",
]
