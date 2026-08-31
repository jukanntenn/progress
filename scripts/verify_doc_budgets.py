#!/usr/bin/env python3
# Word ceilings for the standing agent-instruction files: every file in
# scripts/doc_budgets.manifest.json must exist and stay at or under its
# wc -w ceiling — a budgeted file that has gone missing fails the gate,
# so a rename cannot silently orphan its budget. On red: relocate the
# content to its owning tier, condense, raise the ceiling last with the
# manifest diff justified in the PR.
# Part of doc_sync.py.
from __future__ import annotations

import json
from pathlib import Path
import sys

from doclib import ROOT, restrict

MANIFEST = ROOT / "scripts" / "doc_budgets.manifest.json"


def main(argv: list[str]) -> int:
    budgets: dict[str, int] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths: list[Path] = [ROOT / p for p in budgets]
    if argv[1:]:
        paths = restrict(paths, argv[1:])

    violations: list[str] = []
    for path in paths:
        rel = path.relative_to(ROOT)
        if not path.is_file():
            violations.append(
                f"{rel}: budgeted file is missing — rename or removal must update the manifest in the same change"
            )
            continue
        words = len(path.read_text(encoding="utf-8").split())
        if words > budgets[rel.as_posix()]:
            violations.append(
                f"{rel}: {words} words over the {budgets[rel.as_posix()]}-word ceiling — relocate to the owning tier, then condense; raise the ceiling last with a justified manifest diff"
            )

    if violations:
        print("verify_doc_budgets: ceiling violations found (see docs/AGENTS.md):", file=sys.stderr)
        print("\n".join(f"  {v}" for v in violations), file=sys.stderr)
        return 1
    print(f"verify_doc_budgets: {len(paths)} budgeted file(s) within their ceilings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
