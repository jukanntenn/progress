"""Miniflux async client wrapper (spec feed §9).

Wraps the official **synchronous** ``miniflux`` PyPI client (based on
``requests``) behind an async facade using :func:`asgiref.sync.sync_to_async`.

Why ``asgiref.sync_to_async`` over ``loop.run_in_executor`` / ``asyncio.to_thread``:

- ``thread_sensitive=True`` (the default) serialises all synchronous calls onto
  a single worker thread. The miniflux client holds a ``requests.Session``,
  which is **not** thread-safe; serialising access keeps that Session safe.
- It propagates ``contextvars`` across the sync boundary (OTel trace context,
  structlog context) so telemetry is not lost on the miniflux call.
- It is the community-standard async↔sync bridge (Django / Starlette).

Authentication uses an API key (the Miniflux-recommended method). Timeout is the
fixed code constant :data:`MINIFLUX_TIMEOUT` (spec feed §9.5, spec 02 P4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

from asgiref.sync import sync_to_async
import miniflux

from progress.errors import ExternalServiceException
from progress.observability import report_severe
from progress.utils.http import retry_async

logger = logging.getLogger(__name__)

#: Fixed HTTP timeout for every Miniflux call (spec feed §9.5, spec 02 P4).
MINIFLUX_TIMEOUT: int = 30

#: Miniflux entry status we consume.
_UNREAD_STATUS = "unread"


@dataclass(frozen=True)
class RawEntry:
    """A raw Miniflux entry as returned by ``get_entries``.

    ``feed`` carries the nested Miniflux feed object (``id`` / ``title`` /
    ``site_url``) so the fetcher can group entries by feed without a second
    round-trip.
    """

    id: int
    feed_id: int
    title: str
    url: str
    published_at: datetime
    content: str
    feed: dict[str, Any]


def _coerce_int(value: Any) -> int:
    """Coerce a Miniflux JSON value to ``int`` (ids come back as ints or strs)."""
    if isinstance(value, bool):  # guard: bool is a subclass of int
        raise ValueError(f"unexpected bool for int field: {value!r}")
    return int(value)


def _parse_entry(raw: dict[str, Any]) -> RawEntry:
    """Build a :class:`RawEntry` from one Miniflux entry JSON dict.

    Raises :class:`KeyError`-ish ``ValueError`` via :func:`_coerce_int` if a
    required id is missing / non-numeric — the caller wraps that into an
    :class:`ExternalServiceException`.
    """
    try:
        entry_id = _coerce_int(raw["id"])
        feed_obj = raw.get("feed") or {}
        feed_id = _coerce_int(feed_obj.get("id") or raw.get("feed_id"))
    except (KeyError, ValueError, TypeError) as e:
        raise ExternalServiceException(f"miniflux entry missing required id field: {e}") from e

    published_raw = raw.get("published_at") or raw.get("created_at") or ""
    published_at = _parse_published_at(published_raw)

    return RawEntry(
        id=entry_id,
        feed_id=feed_id,
        title=str(raw.get("title") or ""),
        url=str(raw.get("url") or ""),
        published_at=published_at,
        content=str(raw.get("content") or ""),
        feed=feed_obj if isinstance(feed_obj, dict) else {},
    )


def _parse_published_at(value: Any) -> datetime:
    """Parse a Miniflux timestamp into an aware UTC ``datetime``.

    Miniflux returns ISO-8601 strings with a timezone offset (e.g.
    ``"2026-07-25T10:00:00+08:00"``) or, for some fields, a Unix epoch int.
    On any parse failure we fall back to ``now(UTC)`` rather than dropping the
    entry — the timestamp is display metadata, not a dedup key.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return datetime.now(tz=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value), tz=UTC)
            except (OverflowError, OSError, ValueError):
                pass
    return datetime.now(tz=UTC)


class MinifluxClient:
    """Async wrapper over the synchronous ``miniflux.Client`` (spec feed §9.3).

    Construct with a non-empty ``base_url`` + ``api_key``. Each method bridges
    the synchronous client call through :func:`asgiref.sync.sync_to_async`
    (``thread_sensitive=True``), which serialises onto one worker thread —
    keeping the client's internal ``requests.Session`` thread-safe.
    """

    def __init__(self, base_url: str, api_key: str) -> None:

        self._client = miniflux.Client(base_url, api_key=api_key, timeout=MINIFLUX_TIMEOUT)

    async def get_unread_entries(self) -> list[RawEntry]:
        """Fetch all unread entries from Miniflux (spec feed §5.1).

        One bulk call to ``get_entries(status="unread", ...)``; the caller
        groups the result by feed in memory. Retried via :func:`retry_async`
        on ``ExternalServiceException`` so a single Miniflux hiccup no longer
        fails the whole feed run.
        """

        async def _get() -> dict[str, Any]:
            try:
                return await sync_to_async(self._client.get_entries, thread_sensitive=True)(
                    status=_UNREAD_STATUS,
                    order="published_at",
                    direction="desc",
                )
            except Exception as e:
                raise ExternalServiceException(f"miniflux get_entries failed: {e}") from e

        raw = await retry_async(_get, retry_on=ExternalServiceException)
        entries_raw = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries_raw, list):
            return []
        out: list[RawEntry] = []
        for item in entries_raw:
            if not isinstance(item, dict):
                continue
            try:
                out.append(_parse_entry(item))
            except ExternalServiceException as e:
                logger.warning("skipping malformed miniflux entry: %s", e)
                report_severe(e)
        return out

    async def get_feeds(self) -> list[dict[str, Any]]:
        """Fetch the full feed list from Miniflux (used for FeedTracker GC).

        Retried via :func:`retry_async` on ``ExternalServiceException``.
        """

        async def _get() -> list[dict[str, Any]]:
            try:
                return await sync_to_async(self._client.get_feeds, thread_sensitive=True)()
            except Exception as e:
                raise ExternalServiceException(f"miniflux get_feeds failed: {e}") from e

        feeds = await retry_async(_get, retry_on=ExternalServiceException)
        return feeds if isinstance(feeds, list) else []

    async def close(self) -> None:
        """Close the underlying ``requests.Session`` (spec feed §9.3)."""
        try:
            await sync_to_async(self._client.close, thread_sensitive=True)()
        except Exception as e:  # pragma: no cover - best-effort cleanup
            logger.debug("miniflux client close failed: %s", e)


__all__ = ["MINIFLUX_TIMEOUT", "MinifluxClient", "RawEntry"]
