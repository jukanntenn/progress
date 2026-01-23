"""Utility functions for Progress application"""

import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Tuple, Type
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


def run_command(
    cmd: List[str],
    cwd: Optional[Path] = None,
    timeout: Optional[float] = None,
    check: bool = True,
    input: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    """Run subprocess command and return stdout.

    Args:
        cmd: Command and arguments to execute
        cwd: Working directory (optional)
        timeout: Command timeout in seconds (optional)
        check: If True, raise CalledProcessError for non-zero exit codes
        input: Input string to pass to stdin (optional)
        env: Environment variables (optional)

    Returns:
        Command stdout output

    Raises:
        CommandException: If command fails (CalledProcessError, TimeoutExpired)
        FileNotFoundError: If command executable not found
    """
    logger.debug(f"Executing: {cwd}$ {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            input=input,
            env=env,
        )

        if result.stderr:
            logger.warning(f"Command stderr: {result.stderr}")

        return result.stdout

    except subprocess.CalledProcessError as e:
        err = f"command failed: {e}\n"
        err += f"command: {' '.join(cmd)}\n"
        if e.stdout:
            err += f"Stdout:\n{e.stdout.strip()}\n"
        if e.stderr:
            err += f"Stderr:\n{e.stderr.strip()}\n"

        from .errors import CommandException
        raise CommandException(err) from e

    except subprocess.TimeoutExpired:
        from .errors import CommandException
        raise CommandException("Command timeout") from None

    except subprocess.SubprocessError as e:
        from .errors import CommandException
        raise CommandException("Failed to run command") from e


@dataclass
class ReportBatch:
    """A batch of repository reports."""

    reports: list
    total_size: int
    batch_index: int
    total_batches: int


def create_report_batches(reports: list, max_batch_size: int) -> list[ReportBatch]:
    """Split repository reports into batches by size.

    Args:
        reports: List of RepositoryReport objects
        max_batch_size: Maximum size per batch in bytes

    Returns:
        List of ReportBatch objects

    Notes:
        - Each batch contains at least 1 report
        - If a single report exceeds max_batch_size, it gets its own batch (will be skipped during upload)
        - Batch size is calculated based on rendered report content
        - Uses 0.8 factor to reserve space for summary/title
    """
    if not reports:
        return []

    effective_limit = int(max_batch_size * 0.8)
    logger.info(f"Batch size limit: {effective_limit} bytes (0.8 * {max_batch_size})")

    batches = []
    current_batch = []
    current_size = 0

    for report in reports:
        report_size = len(report.content.encode("utf-8"))

        if report_size > effective_limit:
            if current_batch:
                batches.append(
                    ReportBatch(
                        reports=current_batch,
                        total_size=current_size,
                        batch_index=len(batches),
                        total_batches=0,
                    )
                )
                current_batch = []
                current_size = 0

            logger.warning(
                f"Report for {report.repo_name} ({report_size} bytes) exceeds "
                f"effective_limit ({effective_limit} bytes)"
            )
            batches.append(
                ReportBatch(
                    reports=[report],
                    total_size=report_size,
                    batch_index=len(batches),
                    total_batches=0,
                )
            )
            continue

        if current_batch and current_size + report_size > effective_limit:
            batches.append(
                ReportBatch(
                    reports=current_batch,
                    total_size=current_size,
                    batch_index=len(batches),
                    total_batches=0,
                )
            )
            current_batch = []
            current_size = 0

        current_batch.append(report)
        current_size += report_size

    if current_batch:
        batches.append(
            ReportBatch(
                reports=current_batch,
                total_size=current_size,
                batch_index=len(batches),
                total_batches=0,
            )
        )

    total_batches = len(batches)
    for batch in batches:
        batch.total_batches = total_batches

    logger.info(
        f"Created {total_batches} batch(es) from {len(reports)} report(s), "
        f"effective_limit={effective_limit} bytes"
    )

    return batches
