"""Universal changelog parser (spec changelog §8).

Deterministic-first parsing chain with AI fallback that learns reusable rules.

- markdown_heading: Keep-a-Changelog ``## [x.y.z]`` line-state machine.
- html_generic: lxml heuristic — find heading elements (h1-h4) containing a
  version number, slice version blocks by document order.
- AI fallback: analyze structure, emit a deterministic ChangelogRule when
  possible (persisted to ChangelogTracker.learned_rule), else emit versions.

Each parser returns a list of ChangelogVersion in document order.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

import lxml.html
from pydantic import BaseModel, ConfigDict

from progress.errors import ChangelogParseException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangelogVersion:
    """A single parsed changelog version (spec §8.1)."""

    version: str
    description: str

    @property
    def body(self) -> str:
        return self.description


class ChangelogRule(BaseModel):
    """A reusable deterministic parsing rule (serialized to JSON in DB).

    - version_selector: CSS selector (HTML) locating version heading elements;
      None for markdown (line-based, uses version_pattern on headings).
    - version_pattern: regex with named group ``version`` extracting the version
      number from the matched element's text / heading line.
    - body_selector: CSS selector (HTML) for the version's body block; None =
      markdown (body = text until next version heading).
    - category_selector / item_selector: optional structured sub-selectors.
    """

    model_config = ConfigDict(extra="forbid")
    version_selector: str | None = None
    version_pattern: str
    body_selector: str | None = None
    category_selector: str | None = None
    item_selector: str | None = None


# ---------------------------------------------------------------------------
# Markdown heading parser (Keep-a-Changelog ## [x.y.z])
# ---------------------------------------------------------------------------

_MARKDOWN_HEADING_RE = re.compile(r"^##\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_DATE_SEPARATORS_RE = re.compile(r"[\s\-–—]")


def _extract_version_number(heading: str) -> str:
    """Apply the three-step version extraction (spec changelog §8.3).

    1. Strip brackets: ``[…]`` → content between first ``[`` and first ``]``.
    2. Strip ``v``/``V`` prefix if followed by a digit.
    3. Drop date suffix: split on space / ASCII hyphen / en-dash / em-dash,
       take the first segment.
    Raises :class:`ValueError` if the final result is empty.
    """
    text = heading.strip()
    if text.startswith("[") and "]" in text:
        text = text[text.index("[") + 1 : text.index("]")]
    if text and text[0] in ("v", "V") and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    parts = _DATE_SEPARATORS_RE.split(text, maxsplit=1)
    text = parts[0].strip() if parts else text
    if not text:
        raise ValueError(f"could not extract version from heading {heading!r}")
    return text


def parse_markdown_heading(text: str) -> list[ChangelogVersion]:
    """Parse Keep-a-Changelog Markdown ``## [x.y.z]`` headings (spec §8.3).

    Only two-hash headings (``## ``) match; one-hash (``# ``) does not.
    Raises :class:`ChangelogParseException` if no headings are found or all
    headings fail version extraction.
    """
    matches = list(_MARKDOWN_HEADING_RE.finditer(text))
    if not matches:
        raise ChangelogParseException("no markdown version headings found")

    versions: list[ChangelogVersion] = []
    for idx, match in enumerate(matches):
        heading = match.group("heading")
        try:
            version = _extract_version_number(heading)
        except ValueError:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        description = text[start:end].strip()
        versions.append(ChangelogVersion(version=version, description=description))
    if not versions:
        raise ChangelogParseException("no markdown version headings yielded a version")
    return versions


# ---------------------------------------------------------------------------
# HTML generic heuristic parser
# ---------------------------------------------------------------------------

_VERSION_NUMBER_RE = re.compile(r"\d+\.\d+(?:\.\d+){0,2}")


def parse_html_generic(text: str) -> list[ChangelogVersion]:
    """Heuristic HTML parse: find heading elements (h1-h4) whose text contains a
    version number, slice version blocks by document order.

    Raises ChangelogParseException if lxml missing or no version-bearing headings.
    """
    try:
        pass
    except ImportError as e:
        raise ChangelogParseException("lxml is required for html_generic parser") from e
    if not text.strip():
        raise ChangelogParseException("empty html input")
    try:
        root = lxml.html.fromstring(text)
    except Exception as e:
        raise ChangelogParseException(f"failed to parse html: {e}") from e
    # find all h1-h4 whose text contains a version number → version-block entry
    candidates: list[tuple[Any, str]] = []
    for el in root.iter():
        if el.tag in ("h1", "h2", "h3", "h4"):
            el_text = (el.text_content() or "").strip()
            m = _VERSION_NUMBER_RE.search(el_text)
            if m:
                candidates.append((el, m.group(0)))
    if not candidates:
        raise ChangelogParseException("no version-bearing heading elements found in html")
    versions: list[ChangelogVersion] = []
    for idx, (el, version) in enumerate(candidates):
        # body = sibling nodes between this entry and the next version entry
        next_el = candidates[idx + 1][0] if idx + 1 < len(candidates) else None
        body_parts: list[str] = []
        node: Any = el.getnext()
        while node is not None and node is not next_el:
            txt = (node.text_content() or "").strip()
            if txt:
                body_parts.append(txt)
            node = node.getnext()
        description = "\n".join(body_parts)
        versions.append(ChangelogVersion(version=version, description=description))
    return versions


# ---------------------------------------------------------------------------
# Apply a learned/builtin rule (deterministic)
# ---------------------------------------------------------------------------


def apply_rule(text: str, rule: ChangelogRule) -> list[ChangelogVersion]:
    """Apply a ChangelogRule deterministically. Raises ChangelogParseException on failure."""
    pattern = re.compile(rule.version_pattern)
    if rule.version_selector is None:
        # markdown line-based: match headings, extract version via version_pattern
        heading_re = re.compile(r"^#{1,6}\s+(?P<heading>.+?)\s*$", re.MULTILINE)
        matches = list(heading_re.finditer(text))
        if not matches:
            raise ChangelogParseException("rule: no headings found")
        versions: list[ChangelogVersion] = []
        for idx, match in enumerate(matches):
            heading = match.group("heading")
            m = pattern.search(heading)
            if not m:
                continue
            version = m.group("version")
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            versions.append(ChangelogVersion(version=version, description=text[start:end].strip()))
        if not versions:
            raise ChangelogParseException("rule: no version matched")
        return versions
    # HTML CSS-selector based
    try:
        pass
    except ImportError as e:
        raise ChangelogParseException("lxml is required for html rule") from e
    try:
        root = lxml.html.fromstring(text)
    except Exception as e:
        raise ChangelogParseException(f"rule: failed to parse html: {e}") from e
    elements = root.cssselect(rule.version_selector)
    if not elements:
        raise ChangelogParseException(f"rule: version_selector {rule.version_selector!r} matched nothing")
    versions = []
    for idx, el in enumerate(elements):
        el_text = (el.text_content() or "").strip()
        m = pattern.search(el_text)
        if not m:
            continue
        version = m.group("version")
        next_el: Any = elements[idx + 1] if idx + 1 < len(elements) else None
        body_parts: list[str] = []
        if rule.body_selector:
            # find the nearest following container matching body_selector
            container: Any = el.getnext()
            body_el: Any = None
            while container is not None and container is not next_el:
                found = container.cssselect(rule.body_selector) if hasattr(container, "cssselect") else []
                if found:
                    body_el = found[0]
                    break
                container = container.getnext()
            if body_el is not None:
                body_parts.append((body_el.text_content() or "").strip())
        else:
            node: Any = el.getnext()
            while node is not None and node is not next_el:
                txt = (node.text_content() or "").strip()
                if txt:
                    body_parts.append(txt)
                node = node.getnext()
        versions.append(ChangelogVersion(version=version, description="\n".join(body_parts)))
    if not versions:
        raise ChangelogParseException("rule: no element yielded a version")
    return versions


# ---------------------------------------------------------------------------
# Universal parser (orchestrator) — built-in strategies only here; the async
# AI-fallback orchestrator lives in tracker.py (needs Components / AI deps).
# ---------------------------------------------------------------------------

_BUILTIN_STRATEGIES = {
    "markdown_heading": parse_markdown_heading,
    "html_generic": parse_html_generic,
}


__all__ = [
    "ChangelogRule",
    "ChangelogVersion",
    "apply_rule",
    "parse_html_generic",
    "parse_markdown_heading",
]
