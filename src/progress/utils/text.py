"""Text helpers (truncation, slug, etc.).

Per spec 09 these are pure helpers used by the reports pipeline and other
layers; no I/O, no globals. Domain-specific constants such as
``MAX_DIFF_LENGTH`` / ``TRUNCATE_CHARS`` live in ``cli/reports/pipeline.py``
(spec 02); the generic :func:`truncate` here takes an explicit ``max_length``
so callers bind to the constants they care about.
"""

from __future__ import annotations

from urllib.parse import quote


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate ``text`` to ``max_length`` chars, appending ``suffix`` if cut."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + suffix


def slugify(value: str, max_length: int = 64) -> str:
    """Produce an ASCII-safe slug for use in URLs / filenames."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in value.lower())
    slug = "-".join(part for part in cleaned.split("-") if part)
    return slug[:max_length].rstrip("-") or "x"


def url_safe(value: str) -> str:
    """Percent-encode ``value`` for safe inclusion in a URL path segment."""
    return quote(value, safe="")


__all__ = ["slugify", "truncate", "url_safe"]
