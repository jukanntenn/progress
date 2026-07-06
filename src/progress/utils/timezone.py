"""Timezone helpers."""

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(UTC)


def get_now(timezone: tzinfo) -> datetime:
    return datetime.now(timezone)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Input datetime must contain timezone info")
    return dt.astimezone(ZoneInfo("UTC"))


def from_utc(dt: datetime, timezone: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Input datetime must contain timezone info")
    return dt.astimezone(timezone)


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    return dt.strftime(format_str)
