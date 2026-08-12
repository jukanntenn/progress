#!/usr/bin/env python3
"""ZCode PostToolUse (Edit|Write): best-effort format via prek.

Reads ``toolInput.file_path`` (ZCode uses camelCase payload keys) and runs
prek's ``format`` + ``lint`` groups on it. Never blocks — the real gate is the
Stop hook. The prek operations (agent-agnostic) live in ``.agents/hooks/_core.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".agents" / "hooks"))
import _core  # ty:ignore[unresolved-import]


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return
    file_path = (payload.get("toolInput") or {}).get("file_path")
    if isinstance(file_path, str):
        _core.format([file_path])
        _core.lint(file_path)


if __name__ == "__main__":
    main()
    sys.exit(0)
