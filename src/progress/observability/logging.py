"""structlog configuration bridged to stdlib rotating file handler (spec 04).

Layout (per spec 04, source-verified against structlog ``stdlib.py:1010``):

* ``structlog.configure`` sets the processor chain for structlog loggers.
* A stdlib ``TimedRotatingFileHandler`` owns the file (daily rotation, N days
  retained) and holds a ``ProcessorFormatter`` as its formatter.
* ``ProcessorFormatter`` runs the same structlog processors on records emitted
  via stdlib ``logging`` (third-party libs), so output is uniform.
* A custom ``inject_trace_context`` processor reads
  ``opentelemetry.trace.get_current_span()`` and adds ``trace_id``/``span_id``
  to every event dict (structlog docs recipe).
* ``scrub_secrets`` runs as the final processor before rendering.

Two independent level thresholds: the console sink defaults to INFO (quiet
interactive use) while the file sink defaults to DEBUG (full detail, local
timezone ``yyyy-mm-dd HH:MM:SS`` timestamps for human reading; trace_id /
span_id still cross-reference across timezones).
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any
import warnings

from opentelemetry import trace
import structlog

from progress.observability.scrub import scrub_secrets_processor

LOG_BACKUP_COUNT: int = 14
LOG_FORMAT: str = "%(message)s"


def inject_trace_context(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add ``trace_id`` and ``span_id`` from the active OTel span (if any)."""
    span = trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is not None and ctx.is_valid:
        trace_id = f"{ctx.trace_id:032x}"
        span_id = f"{ctx.span_id:016x}"
        event_dict.setdefault("trace_id", trace_id)
        event_dict.setdefault("span_id", span_id)
    return event_dict


class ConsoleRenderer:
    """Human-readable single-line renderer for the stderr console handler.

    Emits ``2026-07-31 05:55:23 [LEVEL] event  key=value ...`` so the terminal
    shows progress without drowning in JSON. Mirrors structlog's built-in
    :class:`~structlog.dev.ConsoleRenderer` but without color codes (so it is
    safe for piped/redirected output).
    """

    def __call__(self, _logger: Any, _name: str, event_dict: dict[str, Any]) -> str:
        timestamp = event_dict.pop("timestamp", "")
        level = event_dict.pop("level", "info").upper()
        event = event_dict.pop("event", "")
        prefix = f"{timestamp} [{level}]" if timestamp else f"[{level}]"
        parts = [f"{prefix} {event}"]
        for key in sorted(event_dict):
            if key in ("logger", "_record", "_from_structlog"):
                continue
            val = event_dict[key]
            if isinstance(val, str) and len(val) > 120:
                val = val[:117] + "..."
            parts.append(f"{key}={val}")
        return "  ".join(parts)


def configure_structlog(
    log_dir: Path,
    *,
    backup_count: int = LOG_BACKUP_COUNT,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> None:
    """Configure structlog + stdlib logging.

    Logs go to **two** sinks simultaneously:
    - **stderr** (console, ``console_level``): human-readable for interactive CLI observation.
    - **file** (``<log_dir>/progress.log``, ``file_level``): JSON for machine consumption,
      rotated daily, ``backup_count`` days retained. Default DEBUG so file keeps full detail
      while console stays quiet.

    Timestamp format is local timezone ``yyyy-mm-dd HH:MM:SS`` (for human reading);
    trace_id/span_id still cross-reference across timezones.

    ``log_dir`` is created if missing.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "progress.log"

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        inject_trace_context,
        scrub_secrets_processor,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    console_processors: list[Any] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        ConsoleRenderer(),
    ]
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=console_processors,
        foreign_pre_chain=shared_processors,
    )

    file_handler = TimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)

    # root 放最低,让各 handler 各自过滤(file 收全量,console 仅 INFO+)。
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # HTTP 请求日志降级:不进 console(console=INFO),但仍进 file(file=DEBUG)。
    for noisy in ("uvicorn.access", "aiohttp.server", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.DEBUG)

    # Suppress noisy third-party loggers that emit large payloads (SQL INSERT with
    # full report content, complete AI prompts) which have no operational value.
    logging.getLogger("tortoise").setLevel(logging.WARNING)
    logging.getLogger("pydantic_ai").setLevel(logging.WARNING)

    # Third-party libraries emit chatty DEBUG/trace logs with no operational value
    # (httpx connection lifecycle, markdown-it parser internals, openai request
    # payloads). They drown out business DEBUG logs in the file sink, so raise
    # them to WARNING while keeping the root logger at DEBUG for our own code.
    for noisy in ("httpx", "httpcore", "openai", "markdown_it", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # aiosqlite logs every SQL statement + connection repr at DEBUG ("executing
    # functools.partial(<...Connection...>, 'SELECT ...')" / "operation ...
    # completed"). tortoise is already raised to WARNING above; without this the
    # raw-driver noise dominates the file sink and buries business logs.
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    logging.captureWarnings(True)
    # aiohttp emits a misleading RuntimeWarning about TLS-in-TLS being disabled
    # on Python <3.11 even on 3.12+ where it works fine (the warning text checks
    # a transport flag, not the runtime version). It fires for every proxied
    # HTTPS request and floods the file sink. Suppress it explicitly.
    warnings.filterwarnings(
        "ignore",
        message="An HTTPS request is being sent through an HTTPS proxy",
        category=RuntimeWarning,
    )


__all__ = ["LOG_BACKUP_COUNT", "ConsoleRenderer", "configure_structlog", "inject_trace_context"]
