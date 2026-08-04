"""Markdown → HTML rendering with nh3 sanitize (spec 09).

``markdown-it-py`` parses CommonMark with ``html=True`` (so AI-generated inline
HTML survives the parser), then ``nh3.clean`` enforces an allowlist so the
result is safe to inject into Jinja2 templates via ``|safe`` (after sanitize).

``bleach`` is deprecated (2026-06-05) and explicitly avoided per spec 09.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
import nh3

_md = MarkdownIt("commonmark", {"breaks": True, "html": True})

_ALLOWED_TAGS: set[str] = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "del",
    "details",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "q",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "abbr": {"title"},
    "details": {"open"},
    "img": {"src", "alt", "title", "width", "height"},
    "th": {"align"},
    "td": {"align"},
    "span": {"class"},
    "code": {"class"},
}

_ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto", "tel"}


def render_markdown(text: str) -> str:
    """Render ``text`` as CommonMark → HTML, then nh3-sanitize the output."""
    if not text:
        return ""
    raw_html = _md.render(text)
    return nh3.clean(
        raw_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
    )


def render_inline(text: str) -> str:
    """Render a single-line markdown snippet (no paragraph wrapping) + sanitize."""
    if not text:
        return ""
    raw_html = _md.renderInline(text)
    return nh3.clean(
        raw_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
    )


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def _scan_fence_state(lines: list[str]) -> list[bool]:
    """Return a per-line mask: True if the line is inside a fenced code block."""
    in_fence = [False] * len(lines)
    cur = False
    marker = ""
    for idx, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if m:
            ch = m.group(1)[0]
            if not cur:
                cur = True
                marker = ch
            elif line.lstrip().startswith(marker * 3):
                cur = False
                marker = ""
            in_fence[idx] = True
            continue
        in_fence[idx] = cur
    return in_fence


def downgrade_headings(text: str) -> str:
    """Downgrade markdown ATX headings so the highest level becomes at most h3.

    Skips lines inside fenced code blocks (`` ``` `` / ``~~~``) so comment-style
    ``#`` lines are not mistaken for headings. If the resulting minimum level
    would exceed h6, the text is returned unchanged (no partial downgrade).
    """
    if not text:
        return text
    lines = text.split("\n")
    in_fence = _scan_fence_state(lines)
    levels: list[int] = []
    for idx, line in enumerate(lines):
        if in_fence[idx]:
            continue
        m = _ATX_HEADING_RE.match(line)
        if m:
            levels.append(len(m.group(1)))
    if not levels:
        return text
    max_level = min(levels)
    shift = 3 - max_level
    if shift <= 0:
        return text
    min_level = max(levels)
    if min_level + shift > 6:
        return text
    out: list[str] = []
    for idx, line in enumerate(lines):
        if in_fence[idx]:
            out.append(line)
            continue
        m = _ATX_HEADING_RE.match(line)
        if m:
            hashes = m.group(1)
            new_hashes = "#" * (len(hashes) + shift)
            out.append(new_hashes + line[len(hashes) :])
        else:
            out.append(line)
    return "\n".join(out)


__all__ = ["downgrade_headings", "render_inline", "render_markdown"]
