import fnmatch
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from progress.errors import ProposalParseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposalData:
    number: int
    title: str
    status: str
    type: str | None
    author: str | None
    created_date: datetime | None
    file_path: str
    full_text: str
    extra: dict[str, str]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            self.full_text.encode("utf-8", errors="ignore")
        ).hexdigest()


class ProposalParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> ProposalData: ...

    @abstractmethod
    def get_proposal_number(self, file_path: str) -> int: ...

    @abstractmethod
    def compare(
        self, old: ProposalData | None, new: ProposalData
    ) -> dict[str, bool]: ...

    @abstractmethod
    def matches_pattern(self, file_path: str, pattern: str) -> bool: ...


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None

    value = value.strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _read_text(file_path: str) -> str:
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
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


def _parse_rst_headers(text: str) -> dict[str, str]:
    header_re = re.compile(r"^:?\s*([A-Za-z][A-Za-z0-9\- ]+):\s*(.+)$")
    allowed_non_fieldlist_keys = {
        "pep",
        "dep",
        "title",
        "author",
        "status",
        "type",
        "topic",
        "created",
    }

    headers: dict[str, str] = {}
    started = False
    for raw in text.splitlines()[:400]:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not started:
            if not stripped:
                continue
            if re.match(r"^[=\-`~^+*#]{3,}$", stripped):
                continue

            m = header_re.match(stripped)
            if not m:
                continue

            key = m.group(1).strip().lower().replace(" ", "_")
            if not stripped.startswith(":") and key not in allowed_non_fieldlist_keys:
                continue

            started = True
        else:
            if not stripped:
                break
            m = header_re.match(stripped)
            if not m:
                break

        key = m.group(1).strip().lower().replace(" ", "_")
        value = m.group(2).strip()
        headers[key] = value

    return headers


class EIPParser(ProposalParser):
    def parse(self, file_path: str) -> ProposalData:
        text = _read_text(file_path)
        meta = _parse_yaml_frontmatter(text)
        try:
            number = int(meta.get("eip") or self.get_proposal_number(file_path))
        except Exception as e:
            raise ProposalParseError(str(e)) from e

        title = meta.get("title") or ""
        status = meta.get("status") or ""
        type_value = meta.get("type")
        author = meta.get("author")
        created_date = _parse_date(meta.get("created") or "")

        extra: dict[str, str] = {}
        if meta.get("category"):
            extra["category"] = meta.get("category") or ""

        if not title or not status:
            raise ProposalParseError(f"Missing required EIP fields in {file_path}")

        return ProposalData(
            number=number,
            title=title,
            status=status,
            type=type_value,
            author=author,
            created_date=created_date,
            file_path=file_path,
            full_text=text,
            extra=extra,
        )

    def get_proposal_number(self, file_path: str) -> int:
        name = Path(file_path).name
        m = re.search(r"(?:eip|erc)-(\d+)\.md$", name, flags=re.IGNORECASE)
        if not m:
            raise ProposalParseError(
                f"Could not extract EIP number from filename: {name}"
            )
        return int(m.group(1))

    def compare(self, old: ProposalData | None, new: ProposalData) -> dict[str, bool]:
        status_changed = old is not None and (old.status.strip() != new.status.strip())
        content_modified = old is not None and (old.content_hash != new.content_hash)
        return {
            "created": old is None,
            "status_changed": status_changed,
            "content_modified": content_modified,
        }

    def matches_pattern(self, file_path: str, pattern: str) -> bool:
        return fnmatch.fnmatch(Path(file_path).name, pattern)


class PEPParser(ProposalParser):
    def parse(self, file_path: str) -> ProposalData:
        text = _read_text(file_path)
        headers = _parse_rst_headers(text)
        pep_value = headers.get("pep")
        if not pep_value:
            raise ProposalParseError(f"Missing PEP header in {file_path}")

        m = re.search(r"\d+", pep_value)
        if not m:
            raise ProposalParseError(
                f"Invalid PEP header value in {file_path}: {pep_value!r}"
            )
        try:
            number = int(m.group(0))
        except Exception as e:
            raise ProposalParseError(
                f"Invalid PEP number in {file_path}: {pep_value!r}"
            ) from e
        title = headers.get("title") or ""
        status = headers.get("status") or ""
        type_value = headers.get("type")
        author = headers.get("author")
        created_date = _parse_date(headers.get("created") or "")

        extra: dict[str, str] = {}
        if headers.get("topic"):
            extra["topic"] = headers.get("topic") or ""

        if not title or not status:
            raise ProposalParseError(f"Missing required PEP fields in {file_path}")

        return ProposalData(
            number=number,
            title=title,
            status=status,
            type=type_value,
            author=author,
            created_date=created_date,
            file_path=file_path,
            full_text=text,
            extra=extra,
        )

    def get_proposal_number(self, file_path: str) -> int:
        name = Path(file_path).name
        m = re.search(r"pep-(\d+)\.rst$", name, flags=re.IGNORECASE)
        if not m:
            raise ProposalParseError(
                f"Could not extract PEP number from filename: {name}"
            )
        return int(m.group(1))

    def compare(self, old: ProposalData | None, new: ProposalData) -> dict[str, bool]:
        status_changed = old is not None and (old.status.strip() != new.status.strip())
        content_modified = old is not None and (old.content_hash != new.content_hash)
        return {
            "created": old is None,
            "status_changed": status_changed,
            "content_modified": content_modified,
        }

    def matches_pattern(self, file_path: str, pattern: str) -> bool:
        return fnmatch.fnmatch(Path(file_path).name, pattern)


class RustRFCParser(ProposalParser):
    def parse(self, file_path: str) -> ProposalData:
        text = _read_text(file_path)
        number = self.get_proposal_number(file_path)

        title = ""
        status = "unknown"
        author = None

        for raw in text.splitlines()[:200]:
            line = raw.strip()
            if not title and line.startswith("#"):
                title = line.lstrip("#").strip()
                continue
            m = re.match(r"^(status|state)\s*:\s*(.+)$", line, flags=re.IGNORECASE)
            if m:
                status = m.group(2).strip()
                continue
            m = re.match(r"^author\s*:\s*(.+)$", line, flags=re.IGNORECASE)
            if m:
                author = m.group(1).strip()
                continue

        if not title:
            title = Path(file_path).stem

        return ProposalData(
            number=number,
            title=title,
            status=status,
            type=None,
            author=author,
            created_date=None,
            file_path=file_path,
            full_text=text,
            extra={},
        )

    def get_proposal_number(self, file_path: str) -> int:
        name = Path(file_path).name
        m = re.match(r"^(\d+)", name)
        if not m:
            raise ProposalParseError(
                f"Could not extract RFC number from filename: {name}"
            )
        return int(m.group(1))

    def compare(self, old: ProposalData | None, new: ProposalData) -> dict[str, bool]:
        status_changed = old is not None and (old.status.strip() != new.status.strip())
        content_modified = old is not None and (old.content_hash != new.content_hash)
        return {
            "created": old is None,
            "status_changed": status_changed,
            "content_modified": content_modified,
        }

    def matches_pattern(self, file_path: str, pattern: str) -> bool:
        return fnmatch.fnmatch(Path(file_path).name, pattern)


class DjangoDEPParser(ProposalParser):
    def parse(self, file_path: str) -> ProposalData:
        text = _read_text(file_path)
        headers = _parse_rst_headers(text)
        dep_value = headers.get("dep")
        if not dep_value:
            number = self.get_proposal_number(file_path)
        else:
            m = re.search(r"\d+", dep_value)
            if not m:
                raise ProposalParseError(
                    f"Invalid DEP header value in {file_path}: {dep_value!r}"
                )
            try:
                number = int(m.group(0))
            except Exception as e:
                raise ProposalParseError(
                    f"Invalid DEP number in {file_path}: {dep_value!r}"
                ) from e

        title = headers.get("title") or ""
        status = headers.get("status") or ""
        type_value = headers.get("type")
        created_date = _parse_date(headers.get("created") or "")

        if not title:
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

        if not title or not status:
            raise ProposalParseError(f"Missing required DEP fields in {file_path}")

        return ProposalData(
            number=number,
            title=title,
            status=status,
            type=type_value,
            author=headers.get("author"),
            created_date=created_date,
            file_path=file_path,
            full_text=text,
            extra={},
        )

    def get_proposal_number(self, file_path: str) -> int:
        name = Path(file_path).stem
        m = re.search(r"(\d+)", name)
        if not m:
            raise ProposalParseError(
                f"Could not extract DEP number from filename: {name}"
            )
        return int(m.group(1))

    def compare(self, old: ProposalData | None, new: ProposalData) -> dict[str, bool]:
        status_changed = old is not None and (old.status.strip() != new.status.strip())
        content_modified = old is not None and (old.content_hash != new.content_hash)
        return {
            "created": old is None,
            "status_changed": status_changed,
            "content_modified": content_modified,
        }

    def matches_pattern(self, file_path: str, pattern: str) -> bool:
        return fnmatch.fnmatch(Path(file_path).name, pattern)
