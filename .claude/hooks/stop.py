#!/usr/bin/env python3
"""Claude Code Stop: repo-wide lint gate via prek.

Runs prek's ``lint`` group across the whole tree; if it exits nonzero (unfixable
lint remains), prints ``{"decision":"block","reason":...}`` so Claude is sent
back for another pass. Guarded by ``stop_hook_active`` to avoid infinite loops
(at most one block per turn); the authoritative lint verdict then belongs to CI.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REASON_TEMPLATE = """\
prek lint found errors that could not be auto-fixed. Resolve them before finishing.

Diagnostics:
<prek_output>
{diagnostics}
</prek_output>

Required:
1. Fix every diagnostic above with a real code change. Do not silence them with `# noqa`, inline rule disables, or `type: ignore` — only treat a diagnostic as a false positive if you can justify why.
2. After editing, verify with `uv run ruff check` (backend) and `pnpm --dir web lint` (frontend).
3. Only attempt to finish again once lint is clean.

This enforcement fires once per turn — the stop hook will not block a second time. If you stop again with lint errors remaining, they will slip through to CI. Verify before you finish."""

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".agents" / "hooks"))
import _core  # noqa: E402  # ty:ignore[unresolved-import]


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return
    if payload.get("stop_hook_active"):
        return
    result = _core.lint(all_files=True)
    if result.returncode == 0:
        return
    diagnostics = (result.stdout + result.stderr).strip()
    print(json.dumps({"decision": "block", "reason": REASON_TEMPLATE.format(diagnostics=diagnostics)}))


if __name__ == "__main__":
    main()
    sys.exit(0)
