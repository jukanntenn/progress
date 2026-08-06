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


def format_now_local(timezone: str) -> str:
    """Format ``now`` in the given IANA timezone (e.g. ``Asia/Shanghai``).

    Unified helper for every "generated at" timestamp rendered into report
    footers and notification cards. Returns ``now`` in the requested zone via
    ``strftime("%Y-%m-%d %H:%M:%S %Z")``. Falls back to the same format in UTC
    when the timezone string is invalid.
    """
    try:
        local_now = now_utc().astimezone(ZoneInfo(timezone))
    except Exception:  # pragma: no cover - defensive against bad tz strings
        return now_utc().strftime("%Y-%m-%d %H:%M:%S %Z")
    return local_now.strftime("%Y-%m-%d %H:%M:%S %Z")


def format_now_utc() -> str:
    """Format ``now`` in UTC for the notification-card footer.

    Used where no configured timezone is reachable: the console card renders
    without ``CoreConfig``, and ``JinjaRenderer`` falls back here when it was
    constructed without one (e.g. unit tests). Precision to the second; ``%Z``
    yields ``UTC``.
    """
    return now_utc().strftime("%Y-%m-%d %H:%M:%S %Z")
