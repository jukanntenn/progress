"""Markdown rendering for the API layer (spec 09 + 12).

Thin facade over :mod:`progress.utils.markdown` so API routes don't reach
across layer boundaries. The implementation lives in ``utils/`` because both
the CLI (report pipeline) and the API need to render markdown identically.
"""

from __future__ import annotations

from progress.utils.markdown import render_inline, render_markdown

__all__ = ["render_inline", "render_markdown"]
