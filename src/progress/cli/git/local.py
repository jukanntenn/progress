"""Local git operations via ``asyncio`` subprocess (spec 07).

Per spec 07, all local git interactions shell out via ``asyncio.create_subprocess_exec``
instead of using GitPython (sync + index.lock fragility) or dulwich (sync).
Each subprocess is independent, so there is no in-process library state to
manage, and timeouts/cancellation behave cleanly.

Code constants (spec 02): ``GIT_TIMEOUT`` (1800s) and the ``git`` binary name
are not configurable.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil

from progress.errors import CommandException
from progress.observability import observe_span, report_severe

logger = logging.getLogger(__name__)

GIT_BINARY: str = "git"
GIT_TIMEOUT: int = 1800

_DIFF_SAFETY_CAP: int = 5_000_000

_GIT_PROXY: str | None = None


def set_git_proxy(proxy: str | None) -> None:
    """Set the HTTP(S) proxy used by all subsequent git subprocess calls.

    Set once per process from the merged ``CoreConfig.github.proxy`` (CLI/API
    lifespan). Git honours ``HTTPS_PROXY``/``HTTP_PROXY`` env vars, so the value
    is injected into each subprocess's environment by :func:`_run_git`.
    """
    global _GIT_PROXY
    _GIT_PROXY = proxy or None


async def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = GIT_TIMEOUT,
) -> str:
    """Run ``git <args>`` and return stdout (text).

    Raises :class:`CommandException` on non-zero exit, timeout, or missing git.
    stderr is captured and included in the exception message (never logged at
    info level since git writes progress to stderr).
    """
    binary = shutil.which(GIT_BINARY)
    if binary is None:
        raise CommandException(f"git binary not found on PATH ({GIT_BINARY!r})")

    cmd = [binary, *args]
    env: dict[str, str] | None = None
    if _GIT_PROXY:
        env = {**os.environ, "HTTPS_PROXY": _GIT_PROXY, "HTTP_PROXY": _GIT_PROXY}
    cmd_name = args[0] if args else "git"
    async with observe_span(
        "progress.git.op",
        attributes={"command": cmd_name},
    ):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            raise CommandException(f"failed to spawn git: {e}") from e

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as e:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise CommandException(f"git {' '.join(args)} timed out after {timeout}s") from e

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise CommandException(f"git {' '.join(args)} failed (exit={proc.returncode}): {stderr.strip()}")

    return stdout


async def clone(
    url: str,
    dest: Path,
    *,
    branch: str | None = None,
    depth: int | None = 1,
    single_branch: bool = False,
    timeout: int | None = None,
) -> None:
    """Clone ``url`` into ``dest``.

    Defaults match the original shallow single-clone behavior (``depth=1``).
    Pass ``depth=None`` for a full-history clone (used by proposal per spec
    proposal §5.2 — proposal tracking needs the full history to compute
    incremental diffs across runs). ``single_branch=True`` adds
    ``--single-branch`` so only the requested branch is fetched (spec proposal).

    If ``dest`` exists it is removed first (an existing repo would block the
    clone). This is safe because we only ever clone into per-repo directories
    under ``<state_home>/repos/``.
    """
    if dest.exists():
        await _rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)

    args = ["clone"]
    if depth is not None:
        args += ["--depth", str(depth)]
    if single_branch:
        args.append("--single-branch")
    if branch:
        args += ["--branch", branch]
    args += [url, str(dest)]

    logger.debug("git clone %s -> %s", url, dest)
    await _run_git(args, timeout=timeout if timeout is not None else GIT_TIMEOUT)


async def fetch(
    repo_path: Path,
    *,
    timeout: int | None = None,
) -> None:
    """Fetch updates for an existing clone (unbounded — full history kept).

    Calls :func:`cleanup_git_locks` first to self-heal stale ``.git/*.lock``
    files left behind by an interrupted fetch (spec repo §5.6, spec proposal §5.2).
    No ``--depth``: clones are full-history so the incremental diff checkpoint
    (``old_hash``) is always local and never GC'd.
    """
    await cleanup_git_locks(repo_path)
    await _run_git(
        ["fetch"],
        cwd=repo_path,
        timeout=timeout if timeout is not None else GIT_TIMEOUT,
    )


async def reset_hard(repo_path: Path, ref: str = "FETCH_HEAD", *, timeout: int | None = None) -> None:
    """Reset the working tree to ``ref`` (defaults to ``FETCH_HEAD``).

    Used together with :func:`fetch` to update an existing clone to its
    upstream tip (spec repo §5.6, spec proposal §5.2).
    """
    await _run_git(
        ["reset", "--hard", ref],
        cwd=repo_path,
        timeout=timeout if timeout is not None else GIT_TIMEOUT,
    )


async def cleanup_git_locks(repo_path: Path) -> None:
    """Remove stale ``.git/*.lock`` files before fetch (spec repo §5.6).

    Left by interrupted git operations; their presence causes spurious
    "Another git process seems to be running" errors. Safe to call any time.
    """
    git_dir = repo_path / ".git"
    if not git_dir.is_dir():
        return
    loop = asyncio.get_running_loop()

    def _clean() -> None:
        with contextlib.suppress(OSError):
            for lock in git_dir.glob("*.lock"):
                lock.unlink()
        for subdir in ("refs", "logs"):
            sub = git_dir / subdir
            if sub.is_dir():
                with contextlib.suppress(OSError):
                    for lock in sub.rglob("*.lock"):
                        lock.unlink()

    await loop.run_in_executor(None, _clean)


async def get_head_commit(repo_path: Path) -> str:
    """Return the SHA of ``HEAD`` in ``repo_path``."""
    out = await _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    return out.strip()


async def get_default_branch(repo_path: Path) -> str:
    """Return the upstream default branch name (e.g. ``main``)."""
    out = await _run_git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=repo_path)
    return out.strip().replace("origin/", "")


async def get_diff(
    repo_path: Path,
    old_hash: str,
    new_hash: str,
    *,
    max_bytes: int = _DIFF_SAFETY_CAP,
) -> str:
    """Return ``git diff old_hash new_hash`` output.

    No analytical truncation is applied — callers (e.g. ``truncate_diff``) own
    the analytical cap so the true original length is preserved and reported.
    ``max_bytes`` is a high safety cap against runaway subprocess output only;
    it slices without appending any marker so it never pollutes the length.
    """
    out = await _run_git(["diff", old_hash, new_hash], cwd=repo_path)
    return out[:max_bytes]


async def get_log(
    repo_path: Path,
    old_hash: str | None,
    new_hash: str,
    *,
    max_count: int | None = None,
) -> str:
    """Return ``git log --oneline old_hash..new_hash`` (or up to ``new_hash``)."""
    args = ["log", "--oneline"]
    if max_count is not None:
        args += ["-n", str(max_count)]
    if old_hash:
        args.append(f"{old_hash}..{new_hash}")
    else:
        args.append(new_hash)
    return await _run_git(args, cwd=repo_path)


async def get_commit_count(
    repo_path: Path,
    old_hash: str | None,
    new_hash: str,
) -> int:
    """Count commits between ``old_hash`` (exclusive) and ``new_hash``."""
    rev_range = f"{old_hash}..{new_hash}" if old_hash else new_hash
    out = await _run_git(["rev-list", "--count", rev_range], cwd=repo_path)
    try:
        return int(out.strip())
    except ValueError as e:
        report_severe(e)
        return 0


async def get_first_n_commits(
    repo_path: Path,
    *,
    count: int,
) -> str:
    """Return ``count`` most recent commit messages (used for first-run lookback)."""
    if count <= 0:
        return ""
    return await _run_git(["log", f"-n{count}", "--pretty=format:%h %s"], cwd=repo_path)


async def _rmtree(path: Path) -> None:
    """Remove a directory tree asynchronously via a thread-pool executor.

    ``shutil.rmtree`` is blocking; we run it in the default executor so the
    event loop is not stalled. There is no async-native equivalent in stdlib.
    """
    if not path.exists():
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, shutil.rmtree, str(path))


async def get_parent_commit(repo_path: Path, ref: str = "HEAD") -> str:
    """Return the first-parent commit of ``ref`` (spec repo §5.6).

    Used as a fallback when ``HEAD~N`` does not exist (insufficient history).
    Raises :class:`CommandException` if ``ref`` has no parent (root commit).
    """
    out = await _run_git(["rev-parse", f"{ref}^"], cwd=repo_path)
    return out.strip()


async def get_commit_hash_at(repo_path: Path, rev: str) -> str | None:
    """Resolve ``rev`` (e.g. ``HEAD~3``) to a SHA.

    Returns ``None`` when the rev does not exist (used to detect range vs.
    recent strategy choice in spec repo §5.3).
    """
    try:
        out = await _run_git(["rev-parse", "--verify", "--quiet", rev], cwd=repo_path)
    except CommandException:
        return None
    sha = out.strip()
    return sha or None


async def get_recent_n_commit_hashes(repo_path: Path, *, count: int) -> list[str]:
    """Return the ``count`` most recent commit SHAs (newest first)."""
    if count <= 0:
        return []
    out = await _run_git(["log", f"-n{count}", "--pretty=format:%H"], cwd=repo_path)
    return [line.strip() for line in out.splitlines() if line.strip()]


@dataclass(frozen=True)
class CommitMessage:
    """A structured commit message: ``subject`` (first non-empty line) + ``body``.

    ``body`` is the remaining non-empty lines joined by ``\\n``; ``""`` when the
    commit has no body. When the squash-duplicated body equals the subject
    (after stripping), ``body`` is set to ``""`` so the template renders the
    subject exactly once.
    """

    subject: str
    body: str


def _split_commit_message(raw: str) -> CommitMessage:
    """Split a git ``%B`` raw message into (subject, body).

    1. Split on newlines; the first non-empty line is the ``subject`` (``""`` if none).
    2. Remaining non-empty lines are joined by ``\\n`` into ``body``.
    3. If ``body.strip() == subject.strip()`` the message is a squash duplicate
       (body echoes the subject); set ``body = ""`` so it renders once.
    """
    subject = ""
    body_lines: list[str] = []
    subject_found = False
    for ln in raw.splitlines():
        if not subject_found:
            if ln.strip():
                subject = ln.strip()
                subject_found = True
        elif ln.strip():
            body_lines.append(ln.strip())
    body = "\n".join(body_lines)
    if body and body.strip() == subject.strip():
        body = ""
    return CommitMessage(subject=subject, body=body)


async def get_commit_messages(
    repo_path: Path,
    *,
    old_hash: str | None = None,
    new_hash: str = "HEAD",
    max_count: int | None = None,
) -> list[CommitMessage]:
    """Return structured commit messages (subject + body) for the range.

    ``%B`` yields the raw body (subject + body + trailing newline); ``%x00``
    inserts a NUL separator between commits so multi-line bodies survive the
    split (``%s`` would only capture the subject line, and ``splitlines()``
    would fragment multi-line messages). Each raw message is split into
    ``(subject, body)`` via :func:`_split_commit_message`, so callers no longer
    have to guess single- vs multi-line from a bare ``"\\n" in message`` check.
    """
    args = ["log", "--pretty=format:%B%x00"]
    if max_count is not None:
        args += ["-n", str(max_count)]
    if old_hash:
        args.append(f"{old_hash}..{new_hash}")
    else:
        args.append(new_hash)
    out = await _run_git(args, cwd=repo_path)
    return [_split_commit_message(msg) for msg in out.split("\x00") if msg.strip()]


async def get_commit_diff_range(
    repo_path: Path,
    old_hash: str,
    new_hash: str,
    *,
    max_bytes: int = _DIFF_SAFETY_CAP,
) -> str:
    """Return ``git diff old_hash new_hash`` (delegates to :func:`get_diff`)."""
    return await get_diff(repo_path, old_hash, new_hash, max_bytes=max_bytes)


async def get_diff_name_status(
    repo_path: Path,
    old_hash: str,
    new_hash: str,
) -> list[tuple[str, str]]:
    """Return ``git diff --name-status old new`` as ``[(status, path), ...]``.

    Used by proposal incremental tracking (spec proposal §16).
    """
    out = await _run_git(["diff", "--name-status", f"{old_hash}..{new_hash}"], cwd=repo_path)
    result: list[tuple[str, str]] = []
    for raw_line in out.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            status, path = parts
            result.append((status, path))
        else:
            result.append((parts[0], ""))
    return result


async def get_file_diff(
    repo_path: Path,
    old_hash: str,
    new_hash: str,
    file_path: str,
    *,
    max_bytes: int = _DIFF_SAFETY_CAP,
) -> str:
    """Return ``git diff old new -- <file>`` output.

    Used by proposal content_modified analysis (spec proposal §16). No
    analytical truncation here — the caller applies ``truncate_diff`` so the
    true length is preserved. ``max_bytes`` is a runaway-output safety cap only.
    """
    out = await _run_git(["diff", f"{old_hash}..{new_hash}", "--", file_path], cwd=repo_path)
    return out[:max_bytes]


async def get_file_creation_time(repo_path: Path, file_path: str) -> str:
    """Return the ISO datetime when ``file_path`` was first added (spec proposal §16).

    Used in proposal first-run check to pick the newest-created file.
    """
    out = await _run_git(
        ["log", "--diff-filter=A", "--format=%ai", "-1", "--", file_path],
        cwd=repo_path,
    )
    return out.strip()


async def get_total_commit_count(repo_path: Path, *, ref: str = "HEAD") -> int:
    """Return the total commit count reachable from ``ref`` (spec repo §5.3)."""
    out = await _run_git(["rev-list", "--count", ref], cwd=repo_path)
    try:
        return int(out.strip())
    except ValueError as e:
        report_severe(e)
        return 0


async def is_shallow_repository(repo_path: Path) -> bool:
    """Return True if ``repo_path`` is a shallow clone (``--depth`` was used).

    Uses ``git rev-parse --is-shallow-repository`` which prints ``true`` or
    ``false``. If the command fails, returns ``False`` (safe default: do not
    attempt unshallow on an unknown state).
    """
    try:
        out = await _run_git(
            ["rev-parse", "--is-shallow-repository"],
            cwd=repo_path,
        )
        return out.strip() == "true"
    except CommandException as e:
        report_severe(e)
        return False


async def unshallow(repo_path: Path, *, timeout: int = 1800) -> None:
    """Convert a shallow clone to a full-history clone.

    Runs ``git fetch --unshallow``. This is a one-time operation: after it
    succeeds, the repository is no longer shallow and subsequent fetches
    fetch full history. The default timeout is 1800s (30 minutes) to handle
    large repositories like apache/airflow on slow networks.
    """
    await _run_git(
        ["fetch", "--unshallow"],
        cwd=repo_path,
        timeout=timeout,
    )


async def ensure_object(repo_path: Path, sha: str, *, timeout: int = GIT_TIMEOUT) -> bool:
    """Ensure a git object is present locally, fetching it on demand.

    Used before ``git diff <old> <new>`` to recover from a checkpoint
    (``old``) that was garbage-collected from a shallow clone. GitHub enables
    ``uploadpack.allowReachableSHA1InWant``, so ``git fetch origin <sha>``
    succeeds for any commit reachable from a ref.

    Returns ``True`` if the object is local (either already present or fetched
    on demand). Returns ``False`` if the object is genuinely unreachable on the
    remote (e.g. force-pushed away) — the caller should then advance the
    checkpoint. Transient network errors propagate as
    :class:`CommandException` so the run aborts for this repo and retries on
    the next run (network恢复后从上次 checkpoint 继续).
    """
    try:
        await _run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_path, timeout=timeout)
        return True
    except CommandException:
        pass

    await _run_git(["fetch", "origin", sha], cwd=repo_path, timeout=timeout)

    try:
        await _run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_path, timeout=timeout)
        return True
    except CommandException:
        return False


__all__ = [
    "GIT_BINARY",
    "GIT_TIMEOUT",
    "CommitMessage",
    "cleanup_git_locks",
    "clone",
    "ensure_object",
    "fetch",
    "get_commit_count",
    "get_commit_diff_range",
    "get_commit_hash_at",
    "get_commit_messages",
    "get_default_branch",
    "get_diff",
    "get_diff_name_status",
    "get_file_creation_time",
    "get_file_diff",
    "get_first_n_commits",
    "get_head_commit",
    "get_log",
    "get_parent_commit",
    "get_recent_n_commit_hashes",
    "get_total_commit_count",
    "is_shallow_repository",
    "reset_hard",
    "set_git_proxy",
    "unshallow",
]
