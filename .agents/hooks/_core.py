"""Agent-agnostic formatter/gate operations, delegating to prek.

The per-agent hook shells (Claude/Codex/ZCode ``post_tool_use.py`` /
``stop.py`` here, plus the OpenCode TypeScript plugin) each parse their own
payload and speak their own stdout protocol. They share ONLY these two
operations, which depend on no agent's wire format:

  format(paths)            -> ``prek run --group format --files <paths>``  (best-effort)
  lint(*paths, all_files=) -> ``prek run --group lint   --files/--all-files``

``prek.toml`` is the single source of truth for which hooks format vs lint
(the ``format`` and ``lint`` groups); the function names mirror the group
names 1:1. PostToolUse shells ignore the exit code (best-effort formatting);
the Stop shell reads it as the lint gate verdict. Generated files are exempted
in ``prek.toml``, so neither operation ever touches them.

prek always runs from the repo root (resolved from this file's location) so it
finds ``prek.toml`` and ``--files`` paths resolve consistently regardless of
the agent process's cwd.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
FORMAT_GROUP = "format"
LINT_GROUP = "lint"


def _rel(path: str) -> str:
    """Make ``path`` relative to the repo root (pass through if outside)."""
    try:
        return str(Path(path).resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return path


def _prek(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["prek", "run", *args], cwd=str(_REPO_ROOT), capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("[agent-hook] prek not found on PATH; skipping", file=sys.stderr)
        return subprocess.CompletedProcess(["prek"], 0)


def format(paths: list[str]) -> subprocess.CompletedProcess[str]:  # noqa: A001 - mirrors the prek group name
    """Run prek's ``format`` group on ``paths`` (best-effort; never raises)."""
    rel = [_rel(p) for p in paths if p]
    if not rel:
        return subprocess.CompletedProcess(["prek"], 0)
    return _prek("--group", FORMAT_GROUP, "--files", *rel)


def lint(*paths: str, all_files: bool = False) -> subprocess.CompletedProcess[str]:
    """Run prek's ``lint`` group.

    With ``all_files=True`` runs across the whole repo (the Stop gate); the
    returncode is nonzero when lint cannot be auto-fixed. Note prek also treats
    "a fixer modified a file" as nonzero — in a CI-gated clean tree nothing
    modifies at Stop, so nonzero cleanly means unfixable lint remains.
    Otherwise lints the given ``paths`` (best-effort, PostToolUse).
    """
    if all_files:
        return _prek("--group", LINT_GROUP, "--all-files")
    rel = [_rel(p) for p in paths if p]
    if not rel:
        return subprocess.CompletedProcess(["prek"], 0)
    return _prek("--group", LINT_GROUP, "--files", *rel)
