"""OpenTelemetry + Bugsink (Sentry) observability setup.

Observability is opt-in *infrastructure*: providers are configured only when
``[observability]`` is present in the config. When disabled (the default, and in
tests) every OTel API is a no-op, no files are written and no network calls are
made. Traces and metrics export as JSON-Lines to files under ``export_dir`` for
human/AI inspection; errors and crashes are sent to Bugsink via ``sentry-sdk``.

The dedicated ``opentelemetry-exporter-otlp-json-file`` is not yet installable
from PyPI (its ``opentelemetry-proto-json`` dependency is unpublished), so we
write the SDK's own JSON (``ReadableSpan.to_json`` / ``MetricsData.to_json``)
through the Console exporters pointed at per-signal files. The result is the
same human-readable, greppable JSON-Lines artifact.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sentry_sdk
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased

from . import __version__ as PROGRESS_VERSION

if TYPE_CHECKING:
    from .config import ObservabilityConfig

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"
_SECRET_KEYS = frozenset(
    {
        "gh_token",
        "token",
        "password",
        "secret",
        "authorization",
        "webhook_url",
        "dsn",
        "api_key",
        "apikey",
        "private_key",
        "x-github-token",
        "set-cookie",
    }
)


@dataclass
class _TelemetryState:
    enabled: bool = False
    bugsink_enabled: bool = False
    component: str = ""
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    metric_reader: PeriodicExportingMetricReader | None = None
    files: list[Any] = field(default_factory=list)
    instruments: dict[str, Any] = field(default_factory=dict)


_STATE = _TelemetryState()


class _ThreadSafeLineFile:
    """Append-only UTF-8 file whose ``write`` is atomic and flushed per line.

    Console exporters call ``out.write`` from processor threads (and, with
    ``SimpleSpanProcessor``, from worker threads); this wrapper keeps each JSON
    line intact and durable so short-lived CLI runs never lose telemetry.
    """

    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(path, "a", encoding="utf-8")

    def write(self, text: str) -> int:
        with self._lock:
            written = self._fp.write(text)
            self._fp.flush()
            return written

    def flush(self) -> None:
        with self._lock:
            self._fp.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fp.closed:
                self._fp.close()


def _build_sampler(rate: float):
    if rate >= 1.0:
        return ALWAYS_ON
    return ParentBased(TraceIdRatioBased(rate))


def _compact_json(text: str) -> str:
    """Re-serialize the SDK's pretty JSON as one compact JSON-Lines record."""
    return json.dumps(json.loads(text), separators=(",", ":")) + "\n"


def _scrub_secret_values(value: Any) -> None:
    """Recursively replace values of known secret keys in a Sentry event."""
    if isinstance(value, dict):
        for key, val in list(value.items()):
            if isinstance(key, str) and key.lower() in _SECRET_KEYS:
                value[key] = _REDACTED
            else:
                _scrub_secret_values(val)
    elif isinstance(value, list):
        for item in value:
            _scrub_secret_values(item)


def _before_send(event: dict, _hint: dict) -> dict:
    _scrub_secret_values(event)
    return event


def _setup_otel(
    cfg: "ObservabilityConfig", *, component: str, environment: str
) -> None:
    otel = cfg.otel
    if not otel.enabled:
        return

    export_dir = Path(otel.export_dir)
    resource = Resource.create(
        {
            "service.name": "progress",
            "service.version": PROGRESS_VERSION,
            "service.namespace": "progress",
            "deployment.environment": environment,
        }
    )

    if otel.traces:
        traces_file = _ThreadSafeLineFile(export_dir / "traces.jsonl")
        _STATE.files.append(traces_file)
        exporter = ConsoleSpanExporter(
            out=traces_file, formatter=lambda span: _compact_json(span.to_json())
        )
        processor_cls = (
            SimpleSpanProcessor if component == "cli" else BatchSpanProcessor
        )
        tracer_provider = TracerProvider(
            resource=resource, sampler=_build_sampler(otel.sampling_rate)
        )
        tracer_provider.add_span_processor(processor_cls(exporter))
        trace.set_tracer_provider(tracer_provider)
        _STATE.tracer_provider = tracer_provider

    if otel.metrics:
        metrics_file = _ThreadSafeLineFile(export_dir / "metrics.jsonl")
        _STATE.files.append(metrics_file)
        export_interval = 5_000 if component == "cli" else 60_000
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(
                out=metrics_file, formatter=lambda md: _compact_json(md.to_json())
            ),
            export_interval_millis=export_interval,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)
        _STATE.meter_provider = meter_provider
        _STATE.metric_reader = reader
        _register_business_metrics()

    try:
        LoggingInstrumentor().instrument(inject_trace_context=True)
    except Exception as e:
        logger.warning("Logging instrumentation failed: %s", e)

    try:
        SQLite3Instrumentor().instrument()
    except Exception as e:
        logger.warning("SQLite instrumentation failed: %s", e)

    try:
        RequestsInstrumentor().instrument()
    except Exception as e:
        logger.warning("Requests instrumentation failed: %s", e)


def _register_business_metrics() -> None:
    meter = metrics.get_meter("progress", PROGRESS_VERSION)
    _STATE.instruments["repos_checked"] = meter.create_counter(
        "progress.repos.checked",
        unit="1",
        description="Repositories processed by the check pipeline",
    )
    _STATE.instruments["analysis_duration"] = meter.create_histogram(
        "progress.analysis.duration",
        unit="s",
        description="AI analyzer call wall-clock duration",
    )
    _STATE.instruments["analysis_failures"] = meter.create_counter(
        "progress.analysis.failures",
        unit="1",
        description="AI analyzer calls that failed",
    )
    _STATE.instruments["notifications_sent"] = meter.create_counter(
        "progress.notifications.sent",
        unit="1",
        description="Notifications dispatched",
    )
    _STATE.instruments["reports_generated"] = meter.create_counter(
        "progress.reports.generated",
        unit="1",
        description="Reports generated",
    )


def _setup_bugsink(cfg: "ObservabilityConfig", *, component: str) -> None:
    dsn = cfg.bugsink.dsn
    if not dsn:
        return
    environment = cfg.bugsink.environment
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=f"progress@{PROGRESS_VERSION}",
            traces_sample_rate=0,
            auto_session_tracking=False,
            send_client_reports=False,
            send_default_pii=False,
            before_send=_before_send,
        )
        sentry_sdk.set_tag("component", component)
        _STATE.bugsink_enabled = True
        logger.info("Bugsink error reporting enabled (environment=%s)", environment)
    except Exception as e:
        logger.warning("Bugsink initialization failed: %s", e)


def setup_observability(cfg: "ObservabilityConfig", *, component: str) -> None:
    """Configure OTel (traces/metrics to files) and Bugsink error reporting.

    Safe to call once per process; a second call is a no-op. When neither
    ``otel.enabled`` nor ``bugsink.dsn`` is set this does nothing.
    """
    if _STATE.enabled:
        return

    _STATE.component = component
    _setup_otel(cfg, component=component, environment=cfg.bugsink.environment)
    _setup_bugsink(cfg, component=component)

    if _STATE.tracer_provider or _STATE.meter_provider or cfg.bugsink.dsn:
        _STATE.enabled = True
        import atexit

        atexit.register(shutdown_observability)


def instrument_fastapi_app(app: Any) -> None:
    """Instrument a FastAPI app for tracing (no-op when telemetry is disabled)."""
    if not _STATE.enabled:
        return
    try:
        FastAPIInstrumentor.instrument_app(app)
    except Exception as e:
        logger.warning("FastAPI instrumentation failed: %s", e)


def is_enabled() -> bool:
    return _STATE.enabled


def shutdown_observability() -> None:
    """Flush and shut down all providers; close telemetry files."""
    if not _STATE.enabled:
        return

    if _STATE.tracer_provider is not None:
        try:
            _STATE.tracer_provider.force_flush(timeout_millis=5_000)
            _STATE.tracer_provider.shutdown()
        except Exception as e:
            logger.debug("Tracer shutdown error: %s", e)

    if _STATE.meter_provider is not None:
        try:
            _STATE.meter_provider.force_flush(timeout_millis=5_000)
            _STATE.meter_provider.shutdown()
        except Exception as e:
            logger.debug("Meter shutdown error: %s", e)

    try:
        sentry_sdk.flush(timeout=5)
    except Exception as e:
        logger.debug("Sentry flush error: %s", e)

    for telemetry_file in _STATE.files:
        try:
            telemetry_file.close()
        except Exception as e:
            logger.debug("Telemetry file close error: %s", e)

    _STATE.files.clear()
    _STATE.instruments.clear()
    _STATE.tracer_provider = None
    _STATE.meter_provider = None
    _STATE.metric_reader = None
    _STATE.bugsink_enabled = False
    _STATE.enabled = False


def get_tracer(name: str = "progress"):
    """Return a tracer; a no-op tracer when telemetry is not configured."""
    return trace.get_tracer(name, PROGRESS_VERSION)


def record_repo_checked(*, status: str) -> None:
    counter = _STATE.instruments.get("repos_checked")
    if counter is not None:
        counter.add(1, {"status": status})


def record_analysis(
    *, provider: str, duration_s: float, ok: bool, reason: str = ""
) -> None:
    histogram = _STATE.instruments.get("analysis_duration")
    if histogram is not None:
        histogram.record(duration_s, {"provider": provider})
    failures = _STATE.instruments.get("analysis_failures")
    if failures is not None and not ok:
        failures.add(1, {"provider": provider, "reason": reason or "error"})


def record_notification_sent(*, channel: str) -> None:
    counter = _STATE.instruments.get("notifications_sent")
    if counter is not None:
        counter.add(1, {"channel": channel})


def record_report_generated(*, storage: str = "") -> None:
    counter = _STATE.instruments.get("reports_generated")
    if counter is not None:
        counter.add(1, {"storage": storage or "default"})


def record_analysis_failure(*, provider: str, reason: str = "error") -> None:
    """Increment the analysis-failure counter only (no duration histogram).

    Use at sites where ``run_tool`` already returned ``ok=True`` but a later
    step (e.g. JSON parsing) failed, so the failure is still counted without
    double-recording the call duration that ``record_analysis`` already logged.
    """
    failures = _STATE.instruments.get("analysis_failures")
    if failures is not None:
        failures.add(1, {"provider": provider, "reason": reason})


def report_error(exc: BaseException | None = None, **tags: Any) -> None:
    """Forward a swallowed exception to Bugsink; no-op when not configured.

    Call this from ``except`` blocks that intentionally degrade to a warning
    and continue, so the otherwise-invisible failure still reaches Bugsink.
    ``tags`` are scoped to this single event (via ``push_scope``) so they aid
    grouping/filtering without leaking onto subsequent events. Pass ``exc``
    explicitly, or call with no args inside an ``except`` to capture the
    active exception.
    """
    if not _STATE.bugsink_enabled:
        return
    with sentry_sdk.push_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, value)
        sentry_sdk.capture_exception(exc)


__all__ = [
    "get_tracer",
    "instrument_fastapi_app",
    "is_enabled",
    "record_analysis",
    "record_analysis_failure",
    "record_notification_sent",
    "record_report_generated",
    "record_repo_checked",
    "report_error",
    "setup_observability",
    "shutdown_observability",
]
