"""Timezone helpers."""

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

_ISO_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S+00:00",
    "%Y-%m-%dT%H:%M:%S%z",
)


def parse_created_at(value: str | None) -> datetime | None:
    """Parse a GitHub ``created_at`` timestamp into a UTC datetime (spec repo §7.2)."""
    if not value:
        return None
    for fmt in _ISO_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)  # noqa: DTZ007
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def render_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    return dt.strftime(format_str)
