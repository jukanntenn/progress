#!/usr/bin/env python3
# Reject Markdown prose paragraphs spanning multiple physical lines —
# write one line per paragraph and let the editor soft-wrap. Tables,
# code blocks, and list structure keep their formatting. Part of
# doc_sync.py.
from __future__ import annotations

import re
import sys

from doclib import ROOT, collect, expand_pairs, mask_source, restrict

PATTERNS = [
    "README.md",
    "README_zh.md",
    "PRINCIPLES.md",
    "AGENTS.md",
    "web/AGENTS.md",
    "docs/*.md",
    "specs/redesign/*.md",
    ".agents/prfcs/*.md",
    ".agents/prfcs/**/*.md",
    ".agents/skills/*.md",
    ".agents/skills/**/*.md",
    "web/e2e/*.md",
]

_STRUCTURAL = re.compile(
    r"""^(?:
        \#{1,6}\s |                  # ATX heading
        [-*+]\s |                    # bullet item
        \d+[\.\)]\s |                # ordered item
        \> |                         # blockquote
        \| |                         # table row
        =+ \s* $ | -{2,} \s* $ |     # setext underline
        \[                           # link definition / bracket opener
    )""",
    re.VERBOSE,
)


def is_plain_prose(line: str) -> bool:
    """A line that continues or starts a plain paragraph: non-blank, not
    indented (indentation marks list continuation or code), and not any
    block-structural prefix."""
    if not line.strip() or line.startswith(("  ", "\t", "http")):
        return False
    return _STRUCTURAL.match(line) is None


def find_violations(path) -> list[tuple[int, str]]:
    original = path.read_text(encoding="utf-8")
    masked = mask_source(original)
    out: list[tuple[int, str]] = []
    run_start = 0
    run_length = 0
    for number, (line, source) in enumerate(zip(masked.split("\n"), original.split("\n"), strict=True), start=1):
        if is_plain_prose(line):
            if run_length == 0:
                run_start = number
            run_length += 1
        else:
            if run_length >= 2:
                out.append((run_start, source.strip()))
            run_length = 0
    if run_length >= 2:
        out.append((run_start, original.split("\n")[run_start - 1].strip()))
    return out


def main(argv: list[str]) -> int:
    files = collect(PATTERNS)
    if len(argv) > 1:
        files = restrict(expand_pairs(files), argv[1:])
    if not files:
        print("verify_md_wrap: no files in scope, nothing to check")
        return 0

    violations: list[str] = []
    for path in files:
        for line, text in find_violations(path):
            clipped = text[:80] + ("…" if len(text) > 80 else "")
            violations.append(f"  {path.relative_to(ROOT)}:{line}  {clipped}")

    if violations:
        print(
            "verify_md_wrap: hard-wrapped prose paragraphs found (write one physical line per paragraph):",
            file=sys.stderr,
        )
        print("\n".join(violations), file=sys.stderr)
        return 1
    print(f"verify_md_wrap: {len(files)} file(s) checked, no hard-wrapped prose paragraphs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
