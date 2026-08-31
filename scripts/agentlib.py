#!/usr/bin/env python3
"""Shared logic for the agent-instruction mirrors.

`AGENTS.md` and `CLAUDE.md` carry the same standing orders under the two
tool-side filenames; every pair in MIRROR_PAIRS lives in one directory.
A pair has no primary: direction is decided against git HEAD so the side
edited last wins, and both-sides-edited is a conflict the callers refuse
to guess through. mtime is the obvious alternative and is wrong — clone
and checkout reset it, leaving both sides equally "new".

The skills mirror is directional by contrast: `.agents/skills/` is the
single source (the agents.md ecosystem's standard path) and
`.zcode/skills/` a tool-specific load path that receives an exact copy.
"""

from __future__ import annotations

from dataclasses import dataclass
import filecmp
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent

MIRROR_PAIRS: list[tuple[str, str]] = [
    ("AGENTS.md", "CLAUDE.md"),
    ("web/AGENTS.md", "web/CLAUDE.md"),
]

SKILLS_SOURCE = ROOT / ".agents" / "skills"
SKILLS_MIRROR = ROOT / ".zcode" / "skills"

IN_SYNC = "in-sync"
FIXED = "fixed"
CONFLICT = "conflict"
DELETED = "deleted"


@dataclass(frozen=True)
class PairStatus:
    status: str
    newer: str | None
    older: str | None
    detail: str


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _head(path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path}"],
        capture_output=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def pair_status(agents: str, claude: str) -> PairStatus:
    disk = {agents: _read(ROOT / agents), claude: _read(ROOT / claude)}
    if disk[agents] is None and disk[claude] is None:
        return PairStatus(IN_SYNC, None, None, f"{agents} and {claude} both absent")

    head = {agents: _head(agents), claude: _head(claude)}
    changed = {p: disk[p] != head[p] for p in disk}

    if disk[agents] is not None and disk[claude] is not None:
        if disk[agents] == disk[claude]:
            return PairStatus(IN_SYNC, None, None, f"{agents} == {claude}")
        if changed[agents] and not changed[claude]:
            return PairStatus(FIXED, agents, claude, f"{agents} changed while {claude} stayed at HEAD")
        if changed[claude] and not changed[agents]:
            return PairStatus(FIXED, claude, agents, f"{claude} changed while {agents} stayed at HEAD")
        return PairStatus(CONFLICT, None, None, f"{agents} and {claude} each changed since HEAD and disagree")

    present, missing = (agents, claude) if disk[claude] is None else (claude, agents)
    if head[missing] is None:
        return PairStatus(FIXED, present, missing, f"{missing} is new; bootstrapped from {present}")
    if changed[present]:
        return PairStatus(CONFLICT, None, None, f"{missing} was deleted while {present} changed")
    return PairStatus(DELETED, None, None, f"{missing} was deleted while {present} stayed at HEAD")


def apply_fix(status: PairStatus) -> None:
    # Only the FIXED status carries a direction; callers gate on it.
    assert status.newer is not None and status.older is not None
    dst = ROOT / status.older
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / status.newer, dst)


def stage(path: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "add", path]).returncode == 0


def _collect(root: Path) -> dict[Path, Path]:
    return {p.relative_to(root): p for p in root.rglob("*") if p.is_file()}


def skills_drift() -> list[Path]:
    """Mirror-relative paths that differ from the source (missing, extra,
    or differing content) — empty means the mirror is an exact copy."""
    if not SKILLS_SOURCE.is_dir():
        return [Path()]
    source = _collect(SKILLS_SOURCE)
    mirror = _collect(SKILLS_MIRROR) if SKILLS_MIRROR.is_dir() else {}
    drift = sorted(set(source) ^ set(mirror))
    drift += [k for k in sorted(set(source) & set(mirror)) if not filecmp.cmp(source[k], mirror[k], shallow=False)]
    return drift


def sync_skills() -> None:
    if SKILLS_MIRROR.exists():
        shutil.rmtree(SKILLS_MIRROR)
    shutil.copytree(SKILLS_SOURCE, SKILLS_MIRROR)
