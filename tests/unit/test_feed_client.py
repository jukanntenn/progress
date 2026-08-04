"""Unit tests for the Miniflux client entry parsing (spec feed §9.3).

Covers the pure parsing helpers in :mod:`progress.integrations.feed.client`.
The async bridge (``sync_to_async``) is exercised in the component tests with a
stubbed miniflux client; here we focus on the deterministic JSON→RawEntry path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from progress.errors import ExternalServiceException
from progress.integrations.feed.client import MINIFLUX_TIMEOUT, _parse_entry, _parse_published_at


def _raw_entry(**overrides):
    base = {
        "id": 42,
        "feed_id": 7,
        "title": "Entry",
        "url": "https://example.com/42",
        "published_at": "2026-07-25T10:00:00+00:00",
        "content": "body",
        "feed": {"id": 7, "title": "Feed", "site_url": "https://feed.example"},
    }
    base.update(overrides)
    return base


class TestParseEntry:
    def test_basic_fields(self) -> None:
        e = _parse_entry(_raw_entry())
        assert e.id == 42
        assert e.feed_id == 7
        assert e.title == "Entry"
        assert e.url == "https://example.com/42"
        assert e.content == "body"
        assert e.feed["title"] == "Feed"

    def test_string_ids_coerced(self) -> None:
        e = _parse_entry(_raw_entry(id="42", feed={"id": "7", "title": "F"}))
        assert e.id == 42
        assert e.feed_id == 7

    def test_missing_feed_object_falls_back_to_feed_id(self) -> None:
        e = _parse_entry(_raw_entry(feed_id=7, feed=None))
        assert e.feed_id == 7
        assert e.feed == {}

    def test_published_at_iso(self) -> None:
        e = _parse_entry(_raw_entry(published_at="2026-07-25T10:00:00+00:00"))
        assert e.published_at == datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC)

    def test_published_at_offset_normalised_to_utc(self) -> None:
        e = _parse_entry(_raw_entry(published_at="2026-07-25T18:00:00+08:00"))
        assert e.published_at == datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC)

    def test_published_at_epoch(self) -> None:
        e = _parse_entry(_raw_entry(published_at=1785984000))
        assert e.published_at.tzinfo is not None

    def test_published_at_garbage_falls_back_to_now(self) -> None:
        e = _parse_entry(_raw_entry(published_at="not-a-date"))
        # exact value is now(); just assert it is an aware UTC datetime
        assert e.published_at.tzinfo is not None

    def test_missing_required_id_raises(self) -> None:

        bad = _raw_entry(id=None)
        bad.pop("feed")
        with pytest.raises(ExternalServiceException):
            _parse_entry(bad)


class TestParsePublishedAt:
    def test_empty_returns_aware_now(self) -> None:
        dt = _parse_published_at("")
        assert dt.tzinfo is not None

    def test_none_returns_aware_now(self) -> None:
        dt = _parse_published_at(None)
        assert dt.tzinfo is not None


class TestTimeoutConstant:
    def test_miniflux_timeout_is_30(self) -> None:
        assert MINIFLUX_TIMEOUT == 30
