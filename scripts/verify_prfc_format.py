#!/usr/bin/env python3
# Every PRFC follows one format (see .agents/prfcs/README.md): filename
# yyyy-mm-dd-topic-title.md under a lifecycle directory, an `# PRFC:
# <title>` header with a Status line agreeing with that directory, a
# `## Problem` body opener, a mandatory `## Alternatives considered`
# section, and a bilingual .zh.md twin with the same skeleton (machine
# tokens and headings in English) linked from a header switcher.
# Proposal-era headings are spec-speak and rejected in implemented/.
# Part of doc_sync.py.
from __future__ import annotations

import re
import sys

from doclib import ROOT, collect, expand_pairs, restrict

LIFECYCLES = {"proposed", "implemented", "rejected"}
TREE_ROOT_FILES = {"README.md", "AGENTS.md", "README.zh.md"}
FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*(\.zh)?\.md$")
TITLE = re.compile(r"^# PRFC: \S.+")
STATUS = re.compile(r"^Status: (proposed|implemented|rejected)(\s+—\s*\S.*)?$")
PROPOSAL_SPEAK = ("## Proposal", "## Plan", "## Migration plan", "## Acceptance criteria")

PRFC_DIR = ".agents/prfcs"


def find_violations(path) -> list[str]:
    rel = path.relative_to(ROOT)
    parts = path.relative_to(ROOT / PRFC_DIR).parts
    lifecycle = parts[0]
    out: list[str] = []

    if lifecycle not in LIFECYCLES:
        return [f"{rel}: lifecycle directory must be one of {sorted(LIFECYCLES)}"]
    if not FILENAME.match(path.name):
        out.append(f"{rel}: filename must be yyyy-mm-dd-topic-title.md (lowercase slug)")
    if path.name.endswith(".zh.md"):
        twin = path.with_name(path.name[: -len(".zh.md")] + ".md")
    else:
        twin = path.with_name(path.name[: -len(".md")] + ".zh.md")
    if not twin.is_file():
        out.append(f"{rel}: every record is a bilingual pair; {twin.name} is missing beside it")
        return out

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not TITLE.match(lines[0]):
        out.append(f"{rel}: line 1 must be `# PRFC: <title>`")
        return out
    header = "\n".join(lines[:6])
    if f"]({twin.name})" not in header:
        out.append(f"{rel}: header must carry a language switcher linking {twin.name}")

    status: str | None = None
    status_has_reason = False
    sections: list[str] = []
    for line in lines[1:]:
        if line.startswith("Status: "):
            m = STATUS.match(line)
            if m:
                status = m.group(1)
                status_has_reason = m.group(2) is not None
            else:
                out.append(f"{rel}: malformed Status line: {line!r}")
                status = "malformed"
        elif line.startswith("## "):
            sections.append(line[3:].strip())

    if status is None:
        out.append(f"{rel}: missing `Status:` line in the header block")
    elif status not in (lifecycle, "malformed"):
        out.append(f"{rel}: Status is {status!r} but the file sits in {lifecycle}/")

    if not sections or sections[0] != "Problem":
        out.append(f"{rel}: body must open with `## Problem`")
    if "Alternatives considered" not in sections:
        out.append(f"{rel}: mandatory `## Alternatives considered` section is missing")

    if lifecycle == "implemented":
        if "Decision" not in sections:
            out.append(f"{rel}: implemented PRFCs need a present-tense `## Decision` section")
        out.extend(
            f"{rel}: {heading} is proposal-speak; an implemented PRFC states what shipped"
            for heading in PROPOSAL_SPEAK
            if heading[3:] in sections
        )
    elif lifecycle == "proposed":
        if "Proposal" not in sections:
            out.append(f"{rel}: proposed PRFCs need a `## Proposal` section")
        if "Acceptance criteria" not in sections:
            out.append(f"{rel}: proposed PRFCs need `## Acceptance criteria` (what observable state means done)")
    elif lifecycle == "rejected":
        if "Proposal" not in sections:
            out.append(f"{rel}: rejected PRFCs keep their `## Proposal` (the verdict lives on the Status line)")
        if status == "rejected" and not status_has_reason:
            out.append(f"{rel}: a rejected PRFC states its one-line reason on the Status line")
    return out


def main(argv: list[str]) -> int:
    files = collect(
        [
            f"{PRFC_DIR}/proposed/*.md",
            f"{PRFC_DIR}/implemented/*.md",
            f"{PRFC_DIR}/rejected/*.md",
        ]
    )
    files = [f for f in files if f.name not in TREE_ROOT_FILES]
    if argv[1:]:
        files = restrict(expand_pairs(files), argv[1:])

    strays = [
        str(p.relative_to(ROOT))
        for p in collect([f"{PRFC_DIR}/*.md", f"{PRFC_DIR}/**/*.md"])
        if p.name not in TREE_ROOT_FILES and (p.parent == ROOT / PRFC_DIR or p.parent.name not in LIFECYCLES)
    ]

    problems: list[str] = []
    for path in files:
        problems.extend(find_violations(path))
    problems += [f"{s}: PRFCs live directly under {PRFC_DIR}/{{proposed,implemented,rejected}}/" for s in strays]

    if problems:
        print(f"verify_prfc_format: format violations found (see {PRFC_DIR}/README.md):", file=sys.stderr)
        print("\n".join(f"  {p}" for p in problems), file=sys.stderr)
        return 1
    print(f"verify_prfc_format: {len(files)} PRFC(s) follow the format")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
