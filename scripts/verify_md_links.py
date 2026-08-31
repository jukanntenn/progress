#!/usr/bin/env python3
# Verify that relative Markdown links, images, and definitions resolve:
# the target file must exist, and a #fragment onto a Markdown target
# (including a same-file #anchor) must name a real heading slug or an
# explicit <a id>. URL and root-absolute targets are excluded. The
# checker never rewrites. Part of doc_sync.py.
from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import unquote

from doclib import ROOT, collect, document_anchors, expand_pairs, extract_links, is_external, mask_source, restrict

# The .zcode/skills mirror (sync_agent_instructions.py) is never scanned;
# .agents/skills is the source and is scanned. CLAUDE.md files are byte
# copies of their AGENTS.md twins and stay unchecked by the same rule.
# The app's own i18n catalogs (src/progress/locales) are gettext content
# owned by check_translations.py, not documentation.
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


def path_part(url: str) -> str:
    return unquote(url.split("#", 1)[0].split("?", 1)[0])


def fragment_part(url: str) -> str | None:
    if "#" not in url:
        return None
    return unquote(url.split("#", 1)[1].split("?", 1)[0])


class AnchorCache:
    """Memoized anchor sets so each target parses once per run."""

    def __init__(self) -> None:
        self._cache: dict[Path, set[str]] = {}

    def anchors(self, abs_path: Path) -> set[str]:
        hit = self._cache.get(abs_path)
        if hit is None:
            hit = document_anchors(mask_source(abs_path.read_text(encoding="utf-8")))
            self._cache[abs_path] = hit
        return hit


def find_violations(abs_path: Path, anchors_of: AnchorCache) -> list[tuple[int, str, str]]:
    """(line, url, reason) per broken link, in document order."""
    masked = mask_source(abs_path.read_text(encoding="utf-8"))
    out: list[tuple[int, str, str]] = []
    for link in extract_links(masked):
        if is_external(link.url):
            continue
        target = path_part(link.url)
        resolved = abs_path if target == "" else (abs_path.parent / target).resolve()
        if not resolved.exists():
            out.append((link.line, link.url, "target does not exist"))
            continue
        fragment = fragment_part(link.url)
        if fragment is None or resolved.suffix != ".md":
            continue
        if fragment not in anchors_of.anchors(resolved):
            out.append((link.line, link.url, "no such anchor in target"))
    return out


def main(argv: list[str]) -> int:
    files = collect(PATTERNS)
    if len(argv) > 1:
        files = restrict(expand_pairs(files), argv[1:])
    if not files:
        print("verify_md_links: no files in scope, nothing to check")
        return 0

    anchors_of = AnchorCache()
    violations: list[str] = []
    for path in files:
        for line, url, reason in find_violations(path, anchors_of):
            violations.append(f"  {path.relative_to(ROOT)}:{line}  {url}  ({reason})")

    if violations:
        print("verify_md_links: broken relative cross-links found:", file=sys.stderr)
        print("\n".join(violations), file=sys.stderr)
        return 1
    print(f"verify_md_links: {len(files)} file(s) checked, all relative cross-links and fragments resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
