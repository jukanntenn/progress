#!/usr/bin/env python3
# Fixer for the agent-instruction mirrors: copies the newer side of each
# AGENTS.md/CLAUDE.md pair over the older (direction detection against
# git HEAD in scripts/agentlib.py) and refreshes .zcode/skills/ from
# .agents/skills/. Refuses both-sides-changed conflicts instead of
# guessing. Run after editing either side of a pair or the skills source.
# Checked by the prek agent-instructions-sync hook.
from __future__ import annotations

import sys

from agentlib import (
    CONFLICT,
    DELETED,
    FIXED,
    MIRROR_PAIRS,
    SKILLS_MIRROR,
    SKILLS_SOURCE,
    apply_fix,
    pair_status,
    sync_skills,
)


def main() -> int:
    failures = 0
    for agents, claude in MIRROR_PAIRS:
        status = pair_status(agents, claude)
        if status.status == FIXED:
            apply_fix(status)
            print(f"fixed: {status.detail} — copied {status.newer} -> {status.older}")
        elif status.status == CONFLICT:
            failures += 1
            print(f"ERROR: mirror conflict — {status.detail}.", file=sys.stderr)
            print("Refusing to guess which side to keep.", file=sys.stderr)
            print(
                f"Reconcile manually: write the content you want to BOTH {agents} and {claude}, then re-run:",
                file=sys.stderr,
            )
            print("  uv run python scripts/sync_agent_instructions.py", file=sys.stderr)
        elif status.status == DELETED:
            failures += 1
            print(f"ERROR: {status.detail}.", file=sys.stderr)
            print(
                "Restore the deleted file, or remove the pair entirely by updating MIRROR_PAIRS in scripts/agentlib.py",
                file=sys.stderr,
            )
            print("and scripts/doc_budgets.manifest.json in the same change.", file=sys.stderr)
    sync_skills()
    print(f"Synced {SKILLS_MIRROR} <- {SKILLS_SOURCE}")
    if failures:
        return 1
    print(f"agent instructions in sync: {len(MIRROR_PAIRS)} pair(s) + skills mirror")
    return 0


if __name__ == "__main__":
    sys.exit(main())
