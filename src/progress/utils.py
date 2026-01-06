"""Utility functions for Progress application"""

import logging
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Callable, Literal, Optional, Tuple, Type
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


BackoffStrategy = Literal["exponential", "fixed"]


def canonicalify(p: Path | str) -> Path:
    return Path(p).expanduser().resolve()


def ensure_path(p: Path | str) -> Path:
    path = canonicalify(p)
    path.mkdir(parents=True, exist_ok=True)
    return path


def retry(
    times: int,
    initial_delay: int = 1,
    backoff: BackoffStrategy = "exponential",
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[tuple, dict, Exception, int], None]] = None,
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay

            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    is_last_attempt = attempt == times - 1
                    error_msg = str(e)[:100]

                    if is_last_attempt:
                        logger.error(f"Command failed, max retries ({times}) reached")
                        raise

                    logger.warning(
                        f"Command failed (attempt {attempt + 1}/{times}), "
                        f"retrying in {delay}s. Error: {error_msg}"
                    )

                    if on_retry:
                        on_retry(args, kwargs, e, attempt + 1)

                    time.sleep(delay)

                    if backoff == "exponential":
                        delay *= 2

        return wrapper

    return decorator


def sanitize(sensitive: str | None, keep_chars: int = 2) -> str:
    """Mask sensitive information for logging.

    Args:
        sensitive: The sensitive string to mask (e.g., token, password, URL)
        keep_chars: Number of leading and trailing characters to keep

    Returns:
        Masked string with middle characters replaced by asterisks.

    Examples:
        >>> sanitize("ghp_abc123def456xyz789")
        'gh***89'
        >>> sanitize("my_secret_password", keep_chars=3)
        'my***ord'
        >>> sanitize(None)
        '***'
    """
    if not sensitive:
        return "***"

    if len(sensitive) <= keep_chars * 2:
        return "***"

    return f"{sensitive[:keep_chars]}***{sensitive[-keep_chars:]}"


def get_now(timezone: ZoneInfo) -> datetime:
    """Get current time in specified timezone

    Args:
        timezone: Timezone object

    Returns:
        Current time with timezone info
    """
    return datetime.now(timezone)


def to_utc(dt: datetime) -> datetime:
    """Convert timezone-aware datetime to UTC

    Args:
        dt: Timezone-aware datetime object

    Returns:
        UTC time
    """
    if dt.tzinfo is None:
        raise ValueError("Input datetime must contain timezone info")
    return dt.astimezone(ZoneInfo("UTC"))


def from_utc(dt: datetime, timezone: ZoneInfo) -> datetime:
    """Convert UTC time to specified timezone

    Args:
        dt: UTC time (must contain timezone info)
        timezone: Target timezone

    Returns:
        Converted time

    Raises:
        ValueError: If input datetime does not contain timezone info
    """
    if dt.tzinfo is None:
        raise ValueError("Input datetime must contain timezone info")
    return dt.astimezone(timezone)


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format datetime

    Args:
        dt: Datetime object
        format_str: Format string

    Returns:
        Formatted string
    """
    return dt.strftime(format_str)
