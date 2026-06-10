import fnmatch
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import NamedTuple

from progress.errors import ProposalParseError

from .types import ProposalKind

logger = logging.getLogger(__name__)

_RST_UNDERLINE_RE = re.compile(r"^[=\-`~^+*#]{3,}$")
_HEADER_RE = re.compile(r"^(?:\s*:\s*)?([A-Za-z][A-Za-z0-9\- ]+)\s*:\s*(.+)$")


class ParsedProposal(NamedTuple):
    number: str
    title: str | None
    raw_status: str
    file_path: str
    full_text: str
    extra: dict[str, str]


class ProposalParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> ParsedProposal: ...

    @abstractmethod
    def extract_number(self, file_path: str) -> str: ...

    @abstractmethod
    def matches_pattern(self, file_path: str, patterns: list[str]) -> bool: ...


def _read_text(file_path: str) -> str:
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.debug("Falling back to error-replace for %s", file_path)
        return Path(file_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise ProposalParseError(str(e)) from e


def _parse_yaml_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end_index = None
    for i in range(1, min(len(lines), 4000)):
        if lines[i].strip() == "---":
            end_index = i
            break

    if end_index is None:
        return {}

    fm_lines = lines[1:end_index]
    data: dict[str, str] = {}
    current_key: str | None = None
    current_list: list[str] = []

    for raw in fm_lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue

        if current_key and re.match(r"^\s+-\s+", line):
            current_list.append(re.sub(r"^\s+-\s+", "", line).strip())
            continue

        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not m:
            continue

        if current_key and current_list:
            data[current_key] = ", ".join(current_list)
            current_key = None
            current_list = []

        key = m.group(1).strip().lower()
        value = m.group(2).strip()
        if value == "":
            current_key = key
            current_list = []
            continue

        value = value.strip("\"'")
        data[key] = value

    if current_key and current_list:
        data[current_key] = ", ".join(current_list)

    return data


def _parse_rst_field_list(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    started = False
    found_field_list = False
    for raw in text.splitlines()[:40]:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not started:
            if not stripped:
                continue
            if _RST_UNDERLINE_RE.match(stripped):
                continue

            m = _HEADER_RE.match(stripped)
            if not m:
                continue
            started = True
        else:
            if not stripped:
                if found_field_list:
                    break
                continue
            if _RST_UNDERLINE_RE.match(stripped):
                continue
            if raw.startswith(" ") or raw.startswith("\t"):
                last_key = next(reversed(headers), None)
                if last_key is not None:
                    headers[last_key] += ", " + stripped
                continue
            m = _HEADER_RE.match(stripped)
            if not m:
                if found_field_list:
                    break
                continue

        key = m.group(1).strip().lower().replace(" ", "_")
        value = m.group(2).strip()
        headers[key] = value
        if stripped.lstrip().startswith(":"):
            found_field_list = True

    return headers


def _matches_any_pattern(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


class EIPParser(ProposalParser):
    def parse(self, file_path: str) -> ParsedProposal:
        text = _read_text(file_path)
        meta = _parse_yaml_frontmatter(text)

        eip_val = meta.get("eip")
        if eip_val:
            number = str(int(eip_val))
        else:
            number = self.extract_number(file_path)

        title = meta.get("title") or None
        if title is not None and not title:
            title = None

        raw_status = meta.get("status", "")

        extra: dict[str, str] = {}
        for key in ("category", "type"):
            val = meta.get(key)
            if val:
                extra[key] = val

        logger.debug("EIPParser: %s number=%s status=%s", file_path, number, raw_status)

        return ParsedProposal(
            number=number,
            title=title,
            raw_status=raw_status,
            file_path=file_path,
            full_text=text,
            extra=extra,
        )

    def extract_number(self, file_path: str) -> str:
        name = Path(file_path).name
        m = re.search(r"(?:eip|erc)-(\d+)\.md$", name, flags=re.IGNORECASE)
        if not m:
            return ""
        return str(int(m.group(1)))

    def matches_pattern(self, file_path: str, patterns: list[str]) -> bool:
        return _matches_any_pattern(Path(file_path).name, patterns)


class PEPParser(ProposalParser):
    def parse(self, file_path: str) -> ParsedProposal:
        text = _read_text(file_path)
        headers = _parse_rst_field_list(text)

        pep_value = headers.get("pep")
        if not pep_value:
            number = self.extract_number(file_path)
        else:
            m = re.search(r"\d+", pep_value)
            if not m:
                raise ProposalParseError(
                    f"Invalid PEP header value in {file_path}: {pep_value!r}"
                )
            number = str(int(m.group(0)))

        title = headers.get("title") or None
        raw_status = headers.get("status", "")

        extra: dict[str, str] = {}
        if headers.get("topic"):
            extra["topic"] = headers["topic"]

        logger.debug("PEPParser: %s number=%s status=%s", file_path, number, raw_status)

        return ParsedProposal(
            number=number,
            title=title,
            raw_status=raw_status,
            file_path=file_path,
            full_text=text,
            extra=extra,
        )

    def extract_number(self, file_path: str) -> str:
        name = Path(file_path).name
        m = re.search(r"pep-(\d+)\.rst$", name, flags=re.IGNORECASE)
        if not m:
            return ""
        return str(int(m.group(1)))

    def matches_pattern(self, file_path: str, patterns: list[str]) -> bool:
        return _matches_any_pattern(Path(file_path).name, patterns)


class RFCParser(ProposalParser):
    def parse(self, file_path: str) -> ParsedProposal:
        text = _read_text(file_path)
        number = self.extract_number(file_path)

        title = None
        for raw in text.splitlines()[:200]:
            line = raw.strip()
            if not title and line.startswith("#"):
                title = line.lstrip("#").strip()
                break

        if not title:
            title = Path(file_path).stem

        logger.debug("RFCParser: %s number=%s", file_path, number)

        return ParsedProposal(
            number=number,
            title=title,
            raw_status="",
            file_path=file_path,
            full_text=text,
            extra={},
        )

    def extract_number(self, file_path: str) -> str:
        name = Path(file_path).name
        m = re.match(r"^(\d+)", name)
        if not m:
            return ""
        return str(int(m.group(1)))

    def matches_pattern(self, file_path: str, patterns: list[str]) -> bool:
        return _matches_any_pattern(Path(file_path).name, patterns)


class DEPParser(ProposalParser):
    def parse(self, file_path: str) -> ParsedProposal:
        text = _read_text(file_path)
        name = Path(file_path).name

        if text.lstrip().startswith("---"):
            return self._parse_yaml(file_path, text, name)

        return self._parse_rst(file_path, text, name)

    def _parse_yaml(self, file_path: str, text: str, name: str) -> ParsedProposal:
        meta = _parse_yaml_frontmatter(text)

        dep_val = meta.get("dep")
        if dep_val:
            m = re.search(r"\d+", dep_val)
            number = str(int(m.group(0))) if m else ""
        else:
            number = self.extract_number(file_path)

        title = meta.get("title") or None
        raw_status = meta.get("status", "")

        logger.debug("DEPParser: %s number=%s status=%s", file_path, number, raw_status)

        return ParsedProposal(
            number=number,
            title=title,
            raw_status=raw_status,
            file_path=file_path,
            full_text=text,
            extra={},
        )

    def _parse_rst(self, file_path: str, text: str, name: str) -> ParsedProposal:
        headers = _parse_rst_field_list(text)

        dep_val = headers.get("dep")
        if dep_val:
            m = re.search(r"\d+", dep_val)
            number = str(int(m.group(0))) if m else ""
        else:
            number = self.extract_number(file_path)

        title = headers.get("title") or None
        if title is None:
            for raw in text.splitlines()[:40]:
                line = raw.strip()
                m = re.match(r"^DEP\s+(\d+)\s*:\s*(.+)$", line, flags=re.IGNORECASE)
                if m:
                    title = m.group(2).strip()
                    break
                m = re.match(r"^DEP\s+(\d+)\b(.+)$", line, flags=re.IGNORECASE)
                if m and m.group(2).strip():
                    title = m.group(2).strip().lstrip(":-–").strip()
                    break

        raw_status = headers.get("status", "")

        logger.debug("DEPParser: %s number=%s status=%s", file_path, number, raw_status)

        return ParsedProposal(
            number=number,
            title=title,
            raw_status=raw_status,
            file_path=file_path,
            full_text=text,
            extra={},
        )

    def extract_number(self, file_path: str) -> str:
        name = Path(file_path).stem
        m = re.search(r"(\d+)", name)
        if not m:
            return ""
        return str(int(m.group(1)))

    def matches_pattern(self, file_path: str, patterns: list[str]) -> bool:
        return _matches_any_pattern(Path(file_path).name, patterns)


def get_parser(kind: ProposalKind) -> ProposalParser:
    match kind:
        case ProposalKind.EIP | ProposalKind.ERC:
            return EIPParser()
        case ProposalKind.PEP:
            return PEPParser()
        case ProposalKind.RFC:
            return RFCParser()
        case ProposalKind.DEP:
            return DEPParser()
