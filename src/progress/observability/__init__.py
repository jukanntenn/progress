"""Observability facade (spec 04).

Single entry: :func:`setup_observability` initializes OTel + structlog +
Bugsink in the right order; :func:`shutdown_observability` flushes everything.

Order matters (spec 04):

1. structlog is configured first so subsequent steps can log through it.
2. OTel providers are created and ``AioHttpClientInstrumentor`` is installed
   **before** any code constructs an ``aiohttp.ClientSession``.
3. Bugsink (sentry-sdk) is initialized last with ``traces_sample_rate=0`` so
   its own trace plumbing never overlaps with OTel.

Per spec 02, all OTel knobs (sampling rate, exporter mode) are code constants.
Bugsink DSN + environment come from ``CoreConfig`` (Web-class).

Note: the local ``logging`` submodule shadows stdlib ``logging`` inside this
package, so we bind stdlib logging eagerly before importing the submodule.
"""

from __future__ import annotations

import logging as _stdlib_logging
from pathlib import Path

import sentry_sdk

from progress.observability.logging import configure_structlog
from progress.observability.metrics import mark_span_outcome, observe_span, observed, record_business_event
from progress.observability.scrub import scrub_event, scrub_secrets
from progress.observability.telemetry import (
    instrument_fastapi_app,
    setup_telemetry,
    shutdown_telemetry,
)

_logger = _stdlib_logging.getLogger(__name__)

_initialized: bool = False


def setup_observability(
    state_home: str,
    *,
    component: str = "cli",
    bugsink_dsn: str = "",
    bugsink_environment: str = "production",
    version: str = "0.0.1",
) -> None:
    """Initialize all observability subsystems for one entry point.

    ``state_home`` is the spec 02 derived root: logs go to
    ``<state_home>/logs/``, OTel JSONL to ``<state_home>/observability/``.
    Safe to call once per process; subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return

    root = Path(state_home)
    configure_structlog(root / "logs")
    setup_telemetry(root / "observability", environment=bugsink_environment)

    if bugsink_dsn:
        try:
            sentry_sdk.init(
                dsn=bugsink_dsn,
                environment=bugsink_environment,
                release=f"progress@{version}",
                traces_sample_rate=0,
                auto_session_tracking=False,
                send_default_pii=False,
                before_send=scrub_event,  # ty:ignore[invalid-argument-type]
            )
            sentry_sdk.set_tag("component", component)
        except Exception as e:
            _logger.warning("bugsink initialization failed; error events will not be sent: %s", e)
    else:
        _logger.warning("bugsink dsn empty; error reporting disabled")

    _initialized = True


def shutdown_observability() -> None:
    """Flush + shutdown all observability subsystems."""
    global _initialized
    if not _initialized:
        return
    shutdown_telemetry()
    try:
        sentry_sdk.flush(timeout=5)
    except Exception as e:
        _logger.debug("sentry flush failed: %s", e)
    _initialized = False


__all__ = [
    "instrument_fastapi_app",
    "mark_span_outcome",
    "observe_span",
    "observed",
    "record_business_event",
    "scrub_event",
    "scrub_secrets",
    "setup_observability",
    "shutdown_observability",
]
