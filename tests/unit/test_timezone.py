"""Unit tests for ``progress.utils.timezone``."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from progress.utils.timezone import (
    from_utc,
    get_now,
    now_utc,
    render_datetime,
    to_utc,
)


class TestNowUtc:
    def test_returns_aware(self) -> None:
        dt = now_utc()
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0  # ty:ignore[unresolved-attribute]


class TestGetNow:
    def test_returns_in_timezone(self) -> None:
        tz = ZoneInfo("Asia/Shanghai")
        dt = get_now(tz)
        assert dt.tzinfo is not None


class TestToUtc:
    def test_converts(self) -> None:
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        utc = to_utc(dt)
        assert utc.utcoffset().total_seconds() == 0  # ty:ignore[unresolved-attribute]
        assert utc.hour == 4

    def test_naive_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            to_utc(datetime(2026, 1, 1, 12, 0, 0))


class TestFromUtc:
    def test_converts(self) -> None:
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        shanghai = from_utc(dt, ZoneInfo("Asia/Shanghai"))
        assert shanghai.hour == 8

    def test_naive_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            from_utc(datetime(2026, 1, 1, 0, 0, 0), ZoneInfo("UTC"))


class TestFormatDatetime:
    def test_default_format(self) -> None:
        dt = datetime(2026, 1, 15, 10, 30, 45, tzinfo=UTC)
        assert render_datetime(dt) == "2026-01-15 10:30:45"

    def test_custom_format(self) -> None:
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        assert render_datetime(dt, "%Y/%m/%d") == "2026/01/15"
