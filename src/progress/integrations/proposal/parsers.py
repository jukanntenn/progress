"""Proposal file parsers (spec proposal §9).

Five parser variants, each producing a :class:`ProposalParseResult`:

- EIP / ERC (shared parser) — Markdown + YAML frontmatter (uses the ``eip``
  key for historical reasons, even on ERC files).
- PEP — RST + field-list.
- RFC — Markdown with no frontmatter; extracts PR number + Feature Name for
  title fallback.
- DEP — auto-detects YAML vs RST.

Shared primitives (spec §9.7):
- YAML frontmatter parser (hand-rolled, no PyYAML dependency).
- RST field-list parser (bare RFC822 + RST ``:Field: value`` forms).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from pathlib import PurePath
import re

from progress.errors import ProposalParseException

logger = logging.getLogger(__name__)

_FRONTMATTER_MAX_LINES = 4000
_FRONTMATTER_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_RST_FIELDLIST_MAX_LINES = 40
_RST_UNDERSCORE_RE = re.compile(r"^[=\-~`'\"^_*+#]+$")
_RST_FIELD_RE = re.compile(r"^:?(?P<key>[A-Za-z][A-Za-z0-9 _\-]*?):\s*(?P<value>.*)$")
_EIP_FILENAME_RE = re.compile(r"(?:eip|erc)-(?P<num>\d+)\.md$", re.IGNORECASE)
_PEP_FILENAME_RE = re.compile(r"pep-(?P<num>\d+)\.rst$", re.IGNORECASE)
_RFC_FILENAME_RE = re.compile(r"^(?P<num>\d+)-", re.IGNORECASE)
_DEP_HEADER_NUM_RE = re.compile(r"\d+")
_NUMBER_RE = re.compile(r"\d+")


@dataclass
class ProposalParseResult:
    """One parsed proposal file (spec proposal §9.1)."""

    number: str
    title: str | None
    raw_status: str
    file_path: str
    full_text: str
    extra: dict[str, str | int | None] = field(default_factory=dict)


def parse_eiperc(text: str, file_path: str) -> ProposalParseResult:
    """Parse EIP / ERC files (spec proposal §9.3).

    Frontmatter key is ``eip`` even for ERC files (historical).
    Falls back to filename if ``eip`` is absent.
    """
    frontmatter = parse_yaml_frontmatter(text)
    number = _extract_eip_number(frontmatter, file_path)
    title = (frontmatter.get("title") or "").strip() or None
    raw_status = (frontmatter.get("status") or "").strip()
    extra: dict[str, str | int | None] = {}
    category = (frontmatter.get("category") or "").strip()
    if category:
        extra["category"] = category
    ptype = (frontmatter.get("type") or "").strip()
    if ptype:
        extra["type"] = ptype
    return ProposalParseResult(
        number=number,
        title=title,
        raw_status=raw_status,
        file_path=file_path,
        full_text=text,
        extra=extra,
    )


def _extract_eip_number(frontmatter: dict[str, str], file_path: str) -> str:
    raw = frontmatter.get("eip")
    if raw:
        match = _NUMBER_RE.search(raw)
        if match:
            return str(int(match.group(0)))
    match = _EIP_FILENAME_RE.search(PurePath(file_path).name)
    if match:
        return str(int(match.group("num")))
    return ""


def parse_pep(text: str, file_path: str) -> ProposalParseResult:
    """Parse PEP files (spec proposal §9.4).

    ``:PEP: TBD`` raises (the only parser that raises on bad header).
    """
    fields = parse_rst_fieldlist(text)
    raw_pep = (fields.get("pep") or "").strip()
    number = ""
    if raw_pep:
        match = _NUMBER_RE.search(raw_pep)
        if not match:
            raise ProposalParseException(f"PEP header value {raw_pep!r} has no parseable number")
        number = str(int(match.group(0)))
    else:
        match = _PEP_FILENAME_RE.search(PurePath(file_path).name)
        if match:
            number = str(int(match.group("num")))
    title = (fields.get("title") or "").strip() or None
    raw_status = (fields.get("status") or "").strip()
    extra: dict[str, str | int | None] = {}
    topic = (fields.get("topic") or "").strip()
    if topic:
        extra["topic"] = topic
    return ProposalParseResult(
        number=number,
        title=title,
        raw_status=raw_status,
        file_path=file_path,
        full_text=text,
        extra=extra,
    )


def parse_rfc(text: str, file_path: str) -> ProposalParseResult:
    """Parse Rust RFC files (spec proposal §9.5).

    No frontmatter; status is always empty (normalized to ACCEPTED).
    Number is extracted from the filename. Title is a fallback derived from
    the Feature Name line or the filename stem.
    """
    name = PurePath(file_path).name
    match = _RFC_FILENAME_RE.match(name)
    number = str(int(match.group("num"))) if match else ""

    head = "\n".join(text.splitlines()[:_FRONTMATTER_MAX_LINES][:200])
    pr_number = _extract_rfc_pr_number(head)
    feature_name = _extract_rfc_feature_name(head)
    fallback_title = _humanize_feature_name(feature_name) if feature_name else PurePath(file_path).stem
    extra: dict[str, str | int | None] = {"fallback_title": fallback_title}
    if pr_number is not None:
        extra["pr_number"] = pr_number
    return ProposalParseResult(
        number=number,
        title=fallback_title,
        raw_status="",
        file_path=file_path,
        full_text=text,
        extra=extra,
    )


_RFC_PR_LINK_RE = re.compile(
    r"RFC\s+PR\s*:?\s*\[[^\]]*?#(?P<num>\d+)\]",
    re.IGNORECASE,
)
_RFC_PR_BARE_RE = re.compile(r"RFC\s+PR\s*:?\s*#(?P<num>\d+)", re.IGNORECASE)
_FEATURE_NAME_RE = re.compile(r"^[-*]\s*Feature Name:\s*(?P<value>.+)$", re.IGNORECASE | re.MULTILINE)


def _extract_rfc_pr_number(head: str) -> int | None:
    for pattern in (_RFC_PR_LINK_RE, _RFC_PR_BARE_RE):
        match = pattern.search(head)
        if match:
            try:
                return int(match.group("num"))
            except (TypeError, ValueError):
                continue
    return None


def _extract_rfc_feature_name(head: str) -> str | None:
    match = _FEATURE_NAME_RE.search(head)
    if not match:
        return None
    value = match.group("value").strip()
    return value or None


def _humanize_feature_name(name: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", name).strip()
    if not cleaned:
        return name
    return cleaned[0].upper() + cleaned[1:]


def parse_dep(text: str, file_path: str) -> ProposalParseResult:
    """Parse Django DEP files (spec proposal §9.6).

    Auto-detects YAML (``---`` prefix) vs RST (field-list).
    """
    stripped = text.lstrip()
    if stripped.startswith("---"):
        return _parse_dep_yaml(text, file_path)
    return _parse_dep_rst(text, file_path)


def _parse_dep_yaml(text: str, file_path: str) -> ProposalParseResult:
    frontmatter = parse_yaml_frontmatter(text)
    number = _extract_dep_number(frontmatter, file_path)
    title = (frontmatter.get("title") or "").strip() or None
    raw_status = (frontmatter.get("status") or "").strip()
    return ProposalParseResult(
        number=number,
        title=title,
        raw_status=raw_status,
        file_path=file_path,
        full_text=text,
    )


def _parse_dep_rst(text: str, file_path: str) -> ProposalParseResult:
    fields = parse_rst_fieldlist(text)
    number = _extract_dep_number(fields, file_path)
    title = (fields.get("title") or "").strip() or None
    if title is None:
        title = _extract_dep_rst_title_from_heading(text, number)
    raw_status = (fields.get("status") or "").strip()
    return ProposalParseResult(
        number=number,
        title=title,
        raw_status=raw_status,
        file_path=file_path,
        full_text=text,
    )


_DEP_HEADING_RE = re.compile(r"^DEP\s+(?P<num>\d+)\s*(?P<sep>[:\-–—])?\s*(?P<rest>.*)$", re.IGNORECASE | re.MULTILINE)


def _extract_dep_rst_title_from_heading(text: str, number: str) -> str | None:
    head_lines = text.splitlines()[:40]
    for line in head_lines:
        match = _DEP_HEADING_RE.match(line.strip())
        if not match:
            continue
        rest = match.group("rest").strip()
        if rest:
            stripped = rest.lstrip(":").lstrip("-").lstrip("–").lstrip("—").strip()
            return stripped or rest
        return f"DEP {number}"
    return None


def _extract_dep_number(fields: dict[str, str], file_path: str) -> str:
    for key in ("dep", "DEP"):
        if key in fields:
            match = _NUMBER_RE.search(fields[key])
            if match:
                return str(int(match.group(0)))
    stem = PurePath(file_path).stem
    match = _DEP_HEADER_NUM_RE.search(stem)
    return str(int(match.group(0))) if match else ""


def parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Parse a YAML frontmatter block (spec proposal §9.7).

    Hand-rolled (no PyYAML dependency). Keys are lowercased; values are
    stripped of surrounding ``"``/``'``. Supports YAML block lists
    (``- item``) by joining with ``", "``. Nested mappings not supported.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    current_key: str | None = None
    current_items: list[str] = []
    line_count = 0
    for line in lines[1:]:
        line_count += 1
        if line_count > _FRONTMATTER_MAX_LINES:
            break
        stripped = line.strip()
        if stripped == "---":
            if current_key is not None and current_items:
                fields[current_key] = ", ".join(current_items)
            return fields
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_key is not None:
                current_items.append(stripped[2:].strip())
            continue
        if ":" not in line:
            continue
        if current_key is not None and current_items:
            fields[current_key] = ", ".join(current_items)
            current_items = []
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if not _FRONTMATTER_KEY_RE.match(key):
            current_key = None
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        fields[key] = value
        current_key = key
        current_items = []
    if current_key is not None and current_items:
        fields[current_key] = ", ".join(current_items)
    return fields


def parse_rst_fieldlist(text: str) -> dict[str, str]:
    """Parse an RST field-list or bare RFC822 header (spec proposal §9.7).

    Accepts both ``:Field: value`` (RST) and ``Field: value`` (bare RFC822).
    Keys lowercased and spaces → underscores (``Last Call`` → ``last_call``).
    Continuation lines (indented) append to the previous field.
    Stops at the first blank line after any field is seen.
    """
    lines = text.splitlines()[:_RST_FIELDLIST_MAX_LINES]
    fields: dict[str, str] = {}
    current_key: str | None = None
    seen_any_field = False
    for line in lines:
        if _RST_UNDERSCORE_RE.match(line.strip()):
            continue
        if not line.strip():
            if seen_any_field:
                break
            continue
        if line[:1].isspace():
            if current_key is not None and line.strip():
                fields[current_key] = (fields[current_key] + "\n" + line.strip()).strip()
            continue
        match = _RST_FIELD_RE.match(line)
        if not match:
            continue
        key = match.group("key").strip().lower().replace(" ", "_")
        value = match.group("value").strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        fields[key] = value
        current_key = key
        seen_any_field = True
    return fields


_PARSERS: dict[str, Callable[[str, str], ProposalParseResult]] = {
    "eip": parse_eiperc,
    "erc": parse_eiperc,
    "pep": parse_pep,
    "rfc": parse_rfc,
    "dep": parse_dep,
}


def get_parser(kind: str):
    """Return the parser for ``kind`` or raise ProposalParseException."""
    parser = _PARSERS.get(kind)
    if parser is None:
        raise ProposalParseException(f"unknown proposal kind: {kind!r}")
    return parser


__all__ = [
    "ProposalParseResult",
    "get_parser",
    "parse_dep",
    "parse_eiperc",
    "parse_pep",
    "parse_rfc",
    "parse_rst_fieldlist",
    "parse_yaml_frontmatter",
]
