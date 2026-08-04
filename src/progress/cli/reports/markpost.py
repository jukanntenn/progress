"""Async MarkPost publishing client (spec 09).

MarkPost is an external service that hosts rendered markdown reports. The
pipeline uploads batched content to MarkPost and stores the returned URLs on
``Batch`` rows so notifications can link back to the full report.

Uses the official ``markpost`` Python SDK (post_key auth, no login required).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from markpost import AsyncMarkpost, MarkpostError

from progress.config.root import MarkpostConfig
from progress.errors import ProgressException
from progress.utils.http import retry_async

logger = logging.getLogger(__name__)


class MarkpostClient:
    """Async client for uploading content to a MarkPost service."""

    def __init__(self, config: MarkpostConfig) -> None:
        full_url = str(config.url.get_secret_value()) if config.url else ""
        if not full_url:
            raise ProgressException("markpost url is not configured")
        parsed = urlparse(full_url)
        if not parsed.scheme or not parsed.netloc:
            raise ProgressException(f"invalid markpost url: missing scheme or netloc ({full_url})")
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        if not path:
            raise ProgressException(f"invalid markpost url: missing path ({full_url})")
        self._post_key = path.lstrip("/")
        self._max_batch_size = config.max_batch_size

    @property
    def max_batch_size(self) -> int:
        return self._max_batch_size

    async def upload(self, content: str, title: str = "") -> str:
        """Upload ``content`` and return the published URL."""

        async def _do() -> str:
            if not content:
                raise ProgressException("markpost upload: content cannot be empty")
            async with AsyncMarkpost(self._base_url, post_key=self._post_key) as client:
                result = await client.create_post(title, content)
            return f"{self._base_url}/{result.id}"

        try:
            return await retry_async(_do, retry_on=(MarkpostError,))
        except Exception as e:
            raise ProgressException(f"markpost upload failed: {e}") from e


def split_batches(content: str, max_size: int) -> list[str]:
    """Split ``content`` into batches of at most ``max_size`` bytes.

    Splits on markdown ``---`` separators first; if a single section exceeds
    ``max_size`` it is emitted as its own batch (even if oversized). An empty
    list is returned for empty content.
    """
    if not content:
        return []
    if max_size <= 0 or len(content.encode("utf-8")) <= max_size:
        return [content]
    sections: list[str] = []
    current: list[str] = []
    current_size = 0
    for part in content.split("\n---\n"):
        part_size = len(part.encode("utf-8"))
        if current and current_size + part_size > max_size:
            sections.append("\n---\n".join(current))
            current = []
            current_size = 0
        current.append(part)
        current_size += part_size
    if current:
        sections.append("\n---\n".join(current))
    return sections


def split_sections[T](sections: list[T], max_size: int, *, size_fn=None) -> list[list[T]]:
    """Split ``sections`` into batches by byte size.

    Each section's size is determined by ``size_fn(section)`` (defaults to
    ``len(section.content.encode("utf-8"))``). A single section that exceeds
    ``max_size`` is emitted as its own batch (even if oversized). An empty
    list is returned for empty input.
    """
    if not sections:
        return []
    if size_fn is None:
        size_fn = lambda s: len(s.content.encode("utf-8"))  # noqa: E731
    total_size = sum(size_fn(s) for s in sections)
    if max_size <= 0 or total_size <= max_size:
        return [sections]
    batches: list[list[T]] = []
    current: list[T] = []
    current_size = 0
    for section in sections:
        section_size = size_fn(section)
        if current and current_size + section_size > max_size:
            batches.append(current)
            current = []
            current_size = 0
        current.append(section)
        current_size += section_size
    if current:
        batches.append(current)
    return batches


__all__ = ["MarkpostClient", "MarkpostError", "split_batches", "split_sections"]
