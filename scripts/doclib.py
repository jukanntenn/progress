#!/usr/bin/env python3
"""Shared stdlib-only helpers for the Markdown verification gates.

Every helper preserves line structure: masked-out regions (fenced code
blocks, inline code spans, frontmatter) are replaced with filler of the
same shape so a character offset or line number computed on masked text
still addresses the original file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def collect(patterns: list[str]) -> list[Path]:
    """Repo-relative files matching the glob patterns, deduped, sorted."""
    seen: set[Path] = set()
    for pattern in patterns:
        seen.update(p for p in ROOT.glob(pattern) if p.is_file())
    return sorted(seen)


def expand_pairs(files: list[Path]) -> list[Path]:
    """Add each file's bilingual twin (.md <-> .zh.md) so a staged run
    that received only one side still checks the whole pair."""
    out: set[Path] = set(files)
    for path in files:
        if path.name.endswith(".zh.md"):
            out.add(path.with_name(path.name[: -len(".zh.md")] + ".md"))
        else:
            out.add(path.with_name(path.name[: -len(".md")] + ".zh.md"))
    return sorted(p for p in out if p.is_file())


def restrict(files: list[Path], given: list[str]) -> list[Path]:
    """Intersection of a gate's scope with explicitly requested paths."""
    wanted = {ROOT / g for g in given}
    return [f for f in files if f in wanted and f.is_file()]


def mask_source(text: str) -> str:
    """Blank out frontmatter, fenced code blocks, and inline code spans.

    Newlines are preserved everywhere, so line numbers derived from the
    masked text address the original file.
    """
    if text.startswith("---\n"):
        closing = text.find("\n---", 4)
        if closing != -1:
            end = text.find("\n", closing + 4)
            text = _filler(text, 0, end if end != -1 else len(text))

    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            out.append(_filler(line, 0, len(line)))
            in_fence = not in_fence
        elif in_fence:
            out.append(_filler(line, 0, len(line)))
        else:
            # Inline code spans may contain [x](y) examples that are not
            # links; blank their contents, keep the backticks.
            out.append(re.sub(r"`[^`]*`", lambda m: _filler(m.group(0), 1, -1), line))
    return "\n".join(out)


def _filler(original: str, start: int, end: int) -> str:
    """Copy of original whose [start:end] slice is spaces (newlines kept)."""
    chars = list(original)
    for i in range(max(start, 0), len(chars) if end == -1 else min(end, len(chars))):
        if chars[i] != "\n":
            chars[i] = " "
    return "".join(chars)


@dataclass
class Link:
    """One reference-style or inline link, image, or definition."""

    line: int
    url: str


_INLINE_LINK = re.compile(r"!?\\?\[([^\]]*)\]\(\s*(?:<([^<>]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\s*\)")
_DEFINITION = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(?:<([^<>]+)>|(\S+))", re.MULTILINE)
_REF_USE = re.compile(r"\[([^\]]+)\]\[([^\]]+)\]")


def extract_links(masked: str) -> list[Link]:
    """Links, images, and definition targets in document order.

    Reference-style uses ([text][label]) resolve through definitions
    defined anywhere in the same file; shortcut refs ([label]) are not
    guessed at.
    """
    out: list[Link] = []
    definitions: dict[str, str] = {}
    for m in _DEFINITION.finditer(masked):
        url = m.group(2) or m.group(3) or ""
        definitions[m.group(1).strip().lower()] = url
        out.append(Link(masked.count("\n", 0, m.start()) + 1, url))

    for m in _INLINE_LINK.finditer(masked):
        url = m.group(2) or m.group(3) or ""
        out.append(Link(masked.count("\n", 0, m.start()) + 1, url))

    for m in _REF_USE.finditer(masked):
        url = definitions.get(m.group(2).strip().lower())
        if url is not None:
            out.append(Link(masked.count("\n", 0, m.start()) + 1, url))

    out.sort(key=lambda link: link.line)
    return out


def is_external(url: str) -> bool:
    """Scheme-qualified, protocol-relative, or root-absolute targets."""
    if url.startswith(("//", "/")):
        return True
    return re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url) is not None


def _render_inline(text: str) -> str:
    """Approximate rendered heading text: keep text, drop syntax."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"</?[^>]+>", "", text)
    return re.sub(r"[*_~]+$|^[*_~]+", "", text.strip())


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HTML_ANCHOR = re.compile(r'<a\s+id="([^"]+)"')


def github_slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop non-word punctuation,
    spaces to hyphens (underscores survive, Unicode letters survive)."""
    slug = heading.lower()
    slug = re.sub(r"[^\w\- ]", "", slug, flags=re.UNICODE)
    return slug.replace(" ", "-")


def document_anchors(masked: str) -> set[str]:
    """Every fragment a Markdown document exposes: GitHub slugs for each
    heading (with -1/-2 collision suffixes) plus explicit <a id> values
    outside code and comments."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in masked.split("\n"):
        m = _HEADING.match(line)
        if m:
            base = github_slug(_render_inline(m.group(2)))
            candidate = base
            bump = seen.get(base, 0)
            while candidate in anchors:
                bump += 1
                candidate = f"{base}-{bump}"
            seen[base] = bump
            anchors.add(candidate)
        elif "<!--" not in line:
            anchors.update(_HTML_ANCHOR.findall(line))
    return anchors
