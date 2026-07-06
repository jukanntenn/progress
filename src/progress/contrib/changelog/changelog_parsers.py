from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import aiohttp
from lxml import html

from ...errors import ChangelogParseError
from typing import override


@dataclass(frozen=True, slots=True)
class VersionEntry:
    version: str
    description: str


class ChangelogParser(ABC):
    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    async def fetch(self, url: str) -> str:
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url, headers={"User-Agent": "progress"}
                ) as response:
                    response.raise_for_status()
                    raw = await response.read()
                    charset = (response.charset or "").strip().lower()
                    return self._decode_bytes(raw, charset)
        except aiohttp.ClientError as e:
            raise ChangelogParseError(
                f"Failed to fetch changelog from {url}: {e}"
            ) from e

    @staticmethod
    def _decode_bytes(raw: bytes, charset: str) -> str:
        candidates: list[str] = []
        if charset:
            candidates.append(charset)
        candidates.append("utf-8")

        bad_encodings = {"iso-8859-1", "latin-1", "windows-1252"}
        seen: set[str] = set()
        for enc in candidates:
            enc = (enc or "").strip().lower()
            if not enc or enc in seen:
                continue
            seen.add(enc)

            try:
                text = raw.decode(enc)
            except Exception:
                continue

            if enc in bad_encodings and (
                "â\x80" in text or "ã\x80" in text or "â€" in text or "ã€" in text
            ):
                continue

            return text

        return raw.decode("utf-8", errors="replace")

    @abstractmethod
    def parse(self, content: str) -> list[VersionEntry]:
        raise NotImplementedError

    def get_latest(self, content: str) -> VersionEntry | None:
        entries = self.parse(content)
        return entries[0] if entries else None


class MarkdownHeadingParser(ChangelogParser):
    _heading_re = re.compile(r"^##\s+(.+?)\s*$")

    @override
    def parse(self, content: str) -> list[VersionEntry]:
        lines = content.splitlines()

        headings: list[tuple[int, str]] = []
        for idx, line in enumerate(lines):
            match = self._heading_re.match(line)
            if match:
                headings.append((idx, match.group(1).strip()))

        if not headings:
            raise ChangelogParseError("No version headings found in markdown content")

        entries: list[VersionEntry] = []
        for i, (start_idx, heading_text) in enumerate(headings):
            end_idx = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
            description_lines = lines[start_idx + 1 : end_idx]
            description = "\n".join(description_lines).strip()
            version = self._extract_version(heading_text)
            entries.append(VersionEntry(version=version, description=description))

        return entries

    @staticmethod
    def _extract_version(heading_text: str) -> str:
        text = heading_text.strip()
        if text.startswith("[") and "]" in text:
            text = text[1 : text.index("]")].strip()

        if text and text[0] in {"v", "V"} and len(text) > 1 and text[1].isdigit():
            text = text[1:]

        text = re.split(r"\s+|[-–—]", text, maxsplit=1)[0].strip()
        if not text:
            raise ChangelogParseError("Empty version extracted from markdown heading")
        return text


class HTMLChineseVersionParser(ChangelogParser):
    _version_re = re.compile(r"uTools\s*v(\d+(?:\.\d+){1,3})", re.IGNORECASE)

    @override
    def parse(self, content: str) -> list[VersionEntry]:
        try:
            root = html.fromstring(content)
            text = root.text_content()
        except Exception as e:
            raise ChangelogParseError(f"Failed to parse HTML content: {e}") from e

        normalized = self._normalize_text(text)
        matches = list(self._version_re.finditer(normalized))
        if not matches:
            raise ChangelogParseError("No version patterns found in HTML content")

        entries: list[VersionEntry] = []
        for i, match in enumerate(matches):
            version = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
            description = normalized[start:end].strip()
            entries.append(VersionEntry(version=version, description=description))

        return entries

    @staticmethod
    def _normalize_text(text: str) -> str:
        lines = [line.strip() for line in text.replace("\r", "").split("\n")]
        lines = [line for line in lines if line]
        return "\n".join(lines)
