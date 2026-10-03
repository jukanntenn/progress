"""Telemetry hub + otel/bugsink/logfile backends (PRFC 2026-08-31 phase 3).

``ctx.telemetry`` is a hub seam, not a single backend: backends register
sinks, redaction runs as a waterfall (``telemetry/scrub``) with
``observability.scrub.scrub_secrets`` as the innermost default, and the
``metrics.py`` function surface is untouched — the hub installs itself as
the business-event funnel through a lifecycle-managed active pointer, so
third parties add sinks or scrub rules without any call site migrating.

The one ordering invariant that inject cannot derive: the OTel aiohttp
instrumentor must arm before any session is created, so the otel backend
provides the ``telemetryOtel`` marker and ``http`` injects it by name.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import sentry_sdk

from progress import __version__
from progress.kernel import Definition, Entry, declare_event
from progress.observability.logging import configure_structlog
from progress.observability.metrics import set_active_hub
from progress.observability.scrub import scrub_event, scrub_secrets
from progress.observability.telemetry import flush_telemetry, setup_telemetry

if TYPE_CHECKING:
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)

declare_event("telemetry/scrub", mode="waterfall", replace=True)


class TelemetryService(Definition):
    service_name = "telemetry"


class TelemetryOtel(Definition):
    service_name = "telemetryOtel"


class TelemetrySink(Protocol):
    """Sync sink contract; write failures are contained by the hub."""

    def write(self, kind: str, payload: dict[str, Any]) -> None: ...


class TelemetryHub:
    """Sink registry + redaction chain + the async ``emit`` observation point."""

    def __init__(self) -> None:
        self.sinks: list[TelemetrySink] = []
        self.scrub_policies: list[Any] = []

    def add_sink(self, sink: TelemetrySink) -> Any:
        self.sinks.append(sink)

        async def _remove() -> None:
            if sink in self.sinks:
                self.sinks.remove(sink)

        return _remove

    def add_scrub_policy(self, policy: Any) -> Any:
        self.scrub_policies.append(policy)

        async def _remove() -> None:
            if policy in self.scrub_policies:
                self.scrub_policies.remove(policy)

        return _remove

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        """Sync funnel path (business events): default scrub + policies + sinks."""
        scrubbed = dict(payload)
        scrubbed["attributes"] = scrub_secrets(dict(payload.get("attributes") or {}))
        for policy in self.scrub_policies:
            try:
                result = policy(scrubbed)
                if isinstance(result, dict):
                    scrubbed = result
            except Exception:
                logger.exception("scrub policy failed; keeping previous payload")
        self._write(kind, scrubbed)

    async def emit(self, ctx: Any, kind: str, payload: dict[str, Any]) -> None:
        """Async path: the ``telemetry/scrub`` waterfall wraps default redaction."""

        async def _default() -> None:
            payload["attributes"] = scrub_secrets(dict(payload.get("attributes") or {}))

        await ctx.waterfall_default("telemetry/scrub", payload, default=_default)
        self._write(kind, payload)

    def _write(self, kind: str, payload: dict[str, Any]) -> None:
        for sink in self.sinks:
            try:
                sink.write(kind, payload)
            except Exception:
                logger.exception("telemetry sink failed")

    def flush(self) -> None:
        for sink in self.sinks:
            close = getattr(sink, "flush", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    logger.exception("telemetry sink flush failed")


def init_bugsink(dsn: str, environment: str, version: str, component: str) -> None:
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=f"progress@{version}",
        traces_sample_rate=0,
        auto_session_tracking=False,
        send_default_pii=False,
        before_send=scrub_event,  # ty:ignore[invalid-argument-type]
    )
    sentry_sdk.set_tag("component", component)


class _OtelBusinessEventSink:
    """Route hub business events into the OTel meter (direct, no recursion)."""

    def write(self, kind: str, payload: dict[str, Any]) -> None:
        from progress.observability.metrics import record_business_event_direct  # noqa: PLC0415

        record_business_event_direct(
            payload.get("name", kind),
            value=payload.get("value", 1),
            attributes=payload.get("attributes") or {},
        )


def make_telemetry_entry() -> Entry:
    """The hub: owns sink registry, scrub chain, and the metrics funnel."""

    async def _apply(ctx: Any, config: Any) -> None:
        from progress.kernel.events import set_background_error_handler  # noqa: PLC0415

        hub = TelemetryHub()
        previous_hub = set_active_hub(hub)
        set_background_error_handler(lambda event, exc: _capture(exc))
        ctx.provide(TelemetryService, hub)

        async def _teardown() -> None:
            set_active_hub(previous_hub)
            set_background_error_handler(None)
            hub.flush()

        ctx.effect(_teardown)

    return Entry(id="telemetry", plugin=_apply)


def make_telemetry_otel_entry() -> Entry:
    """OTel traces/metrics + auto-instrumentation; provides ``telemetryOtel``."""

    async def _apply(ctx: Any, config: Any) -> None:
        cfg: CoreConfig = ctx.config
        setup_telemetry(Path(cfg.state_home) / "observability", environment=cfg.observability.bugsink.environment)
        ctx.provide(TelemetryOtel, True)
        undo_sink = ctx.telemetry.add_sink(_OtelBusinessEventSink())
        ctx.effect(undo_sink)

        async def _flush() -> None:
            flush_telemetry()

        ctx.effect(_flush)

    return Entry(id="telemetry-otel", plugin=_apply, inject=["config", "telemetry"])


def make_telemetry_bugsink_entry(component: str = "cli") -> Entry:
    """Bugsink error reporting (sentry-sdk) with scrubbed ``before_send``."""

    async def _apply(ctx: Any, config: Any) -> None:
        cfg: CoreConfig = ctx.config
        dsn = cfg.observability.bugsink.dsn.get_secret_value()
        if dsn:
            try:
                init_bugsink(dsn, cfg.observability.bugsink.environment, __version__, component)
            except Exception as e:
                logger.warning("bugsink initialization failed; error events will not be sent: %s", e)
        else:
            logger.warning("bugsink dsn empty; error reporting disabled")

        async def _flush_sentry() -> None:
            try:
                sentry_sdk.flush(timeout=5)
            except Exception as e:
                logger.debug("sentry flush failed: %s", e)

        ctx.effect(_flush_sentry)

    return Entry(id="telemetry-bugsink", plugin=_apply, inject=["config", "telemetry"])


def make_telemetry_logfile_entry() -> Entry:
    """Rotating structured file logs under ``<state_home>/logs``."""

    async def _apply(ctx: Any, config: Any) -> None:
        cfg: CoreConfig = ctx.config
        configure_structlog(Path(cfg.state_home) / "logs")

    return Entry(id="telemetry-logfile", plugin=_apply, inject=["config", "telemetry"])


def _capture(exc: BaseException) -> None:
    from contextlib import suppress  # noqa: PLC0415

    with suppress(Exception):
        sentry_sdk.capture_exception(exc)


__all__ = [
    "TelemetryHub",
    "TelemetryOtel",
    "TelemetryService",
    "TelemetrySink",
    "init_bugsink",
    "make_telemetry_bugsink_entry",
    "make_telemetry_entry",
    "make_telemetry_logfile_entry",
    "make_telemetry_otel_entry",
]
