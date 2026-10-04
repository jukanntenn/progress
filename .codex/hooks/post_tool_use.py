#!/usr/bin/env python3
"""Codex PostToolUse (apply_patch): best-effort format via prek.

Codex edits files through one freeform ``apply_patch`` tool whose patch text
carries the edited paths (no structured ``file_path`` field). The V4A headers
``*** Update File:`` / ``*** Add File:`` are parsed — ``*** Move to:`` resolves
to the destination (the source is removed), ``*** Delete File:`` is skipped.
prek's ``format`` + ``lint`` groups then run on each path. Never blocks.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".agents" / "hooks"))
import _core  # ty:ignore[unresolved-import]

MOVE_TO_PREFIX = "*** Move to: "
PATCH_FILE_PREFIXES = (
    "*** Update File: ",
    "*** Add File: ",
)


def extract_edited_paths(command: str) -> list[str]:
    """Return the destination paths edited by a V4A ``apply_patch`` command."""
    paths: list[str] = []
    pending_update: str | None = None
    for raw in command.splitlines():
        line = raw.strip()
        if pending_update is not None and line.startswith(MOVE_TO_PREFIX):
            paths.append(line[len(MOVE_TO_PREFIX) :].strip())
            pending_update = None
            continue
        if pending_update is not None:
            paths.append(pending_update)
            pending_update = None
        if line.startswith(MOVE_TO_PREFIX):
            continue
        for prefix in PATCH_FILE_PREFIXES:
            if line.startswith(prefix):
                pending_update = line[len(prefix) :].strip()
                break
    if pending_update is not None:
        paths.append(pending_update)
    return paths


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return
    paths = extract_edited_paths(command)
    if paths:
        _core.format(paths)
        _core.lint(*paths)


if __name__ == "__main__":
    main()
    sys.exit(0)
