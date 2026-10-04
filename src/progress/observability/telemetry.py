"""OpenTelemetry provider/exporter setup + auto-instrumentation (spec 04).

Single OTel instrumentation layer: traces + metrics + logs via OTel, errors
via Bugsink (sentry-sdk) with ``traces_sample_rate=0`` so the two never fight.

Defaults are code constants (spec 02): sampling rate, exporter switch, etc.
The exporter mode is also a code constant (``"file"`` JSONL by default); if
``OTEL_EXPORTER_OTLP_ENDPOINT`` env var is set, OTLP HTTP is used instead
(logs have no file-mode OTel exporter — the rotating structlog file is the
local sink for logs in every mode, so remote logs are OTLP-only).

Environment identity: standard OTel env vars win over code defaults —
``OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=<env>`` and
``OTEL_SERVICE_NAME`` override the constants here, so container deploys
inject identity without config-schema changes.
"""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path
from typing import Any

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.json.file.metric_exporter import FileMetricExporter
from opentelemetry.exporter.otlp.json.file.trace_exporter import FileSpanExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

PROGRESS_VERSION: str = "0.0.1"
SERVICE_NAME: str = "progress"
SAMPLING_RATE: float = 1.0
ENVIRONMENT: str = "production"

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_logger_provider: LoggerProvider | None = None
_otel_logger: _logs.Logger | None = None
_logger = logging.getLogger(__name__)


def effective_environment(fallback: str) -> str:
    """Resolve ``deployment.environment.name``: OTel env vars beat the config value.

    Reads the two standard env vars the same way the SDK's env detector does,
    so the value here and the value on the emitted resource can never
    disagree (``Resource.create({})`` is not used because it fabricates
    ``service.name="unknown_service"`` when the var is unset). Both the OTel
    resource and the Bugsink ``environment`` tag must be fed from this one
    resolver, or Grafana and Bugsink would label the same deploy differently.
    """
    return _env_resource_overrides().get("deployment.environment.name") or fallback


def otlp_mode() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _env_resource_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    if service_name := os.environ.get("OTEL_SERVICE_NAME"):
        overrides["service.name"] = service_name
    if raw_attributes := os.environ.get("OTEL_RESOURCE_ATTRIBUTES"):
        for pair in raw_attributes.split(","):
            key, sep, value = pair.partition("=")
            if sep:
                overrides[key.strip()] = value.strip().strip('"')
    return overrides


def _build_resource(environment: str) -> Resource:
    # Standard OTel env vars (deployment-time identity) win over code
    # constants, mirroring how a bare SDK deployment behaves.
    attributes = {
        "service.name": SERVICE_NAME,
        "service.version": PROGRESS_VERSION,
        "deployment.environment.name": environment,
    }
    attributes.update(_env_resource_overrides())
    return Resource.create(attributes)


def _build_span_exporter(observability_dir: Path) -> FileSpanExporter | OTLPSpanExporter:
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        return OTLPSpanExporter(endpoint=otlp_endpoint)
    return FileSpanExporter(str(observability_dir / "traces.jsonl"))


def _build_metric_exporter(observability_dir: Path) -> FileMetricExporter | OTLPMetricExporter:
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        return OTLPMetricExporter(endpoint=otlp_endpoint)
    return FileMetricExporter(str(observability_dir / "metrics.jsonl"))


def get_otel_logger() -> _logs.Logger | None:
    """The OTel log emitter, or ``None`` outside OTLP mode.

    ``observability.logging.OtelLogHandler`` calls this per record; ``None``
    turns the remote log path into a no-op (file logging is unaffected).
    """
    return _otel_logger


def setup_telemetry(observability_dir: Path, *, environment: str = ENVIRONMENT) -> None:
    """Initialize global providers + auto-instrumentation.

    CRITICAL (spec 04): ``AioHttpClientInstrumentor().instrument()`` MUST be
    called before any ``aiohttp.ClientSession`` is constructed, otherwise that
    session has no TraceConfig and its calls won't be traced. We instrument
    aiohttp here, before the CLI / API build their sessions.

    The providers are process-global singletons, so setup is idempotent and
    shutdown is deferred to process exit (``atexit``): the OTel global APIs
    refuse a second ``set_tracer_provider``, so a hot-reloaded row (L0) must
    re-enter this as a no-op instead of tearing the globals down and trying
    to re-create them.
    """
    global _tracer_provider, _meter_provider, _logger_provider, _otel_logger
    if _tracer_provider is not None:
        return

    observability_dir.mkdir(parents=True, exist_ok=True)
    resource = _build_resource(environment)
    sampler = ParentBased(TraceIdRatioBased(SAMPLING_RATE))

    provider = TracerProvider(resource=resource, sampler=sampler)
    provider.add_span_processor(BatchSpanProcessor(_build_span_exporter(observability_dir)))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    metric_reader = PeriodicExportingMetricReader(
        exporter=_build_metric_exporter(observability_dir),
        export_interval_millis=60_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter_provider = meter_provider

    if otlp_mode():
        _logger_provider = LoggerProvider(resource=resource)
        _logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]))
        )
        _logs.set_logger_provider(_logger_provider)
        _otel_logger = _logger_provider.get_logger("progress")

    SystemMetricsInstrumentor().instrument()
    AioHttpClientInstrumentor().instrument()
    SQLite3Instrumentor().instrument()
    LoggingInstrumentor(inject_trace_context=True).instrument()
    atexit.register(shutdown_telemetry)


def instrument_fastapi_app(app: Any) -> None:
    """Instrument a FastAPI app. Call AFTER ``setup_telemetry`` and AFTER the
    app is created, so spans cover request handling (spec 04 fixes prior
    ordering bug where ``instrument_app`` ran before telemetry was enabled).
    Idempotent: a restart of the webserver row (L0) must not re-instrument."""
    if getattr(app.state, "otel_instrumented", False):
        return
    FastAPIInstrumentor.instrument_app(app)
    app.state.otel_instrumented = True


def flush_telemetry() -> None:
    """Force-export buffered spans/logs/metrics without tearing the globals down.

    The restart-safe counterpart of :func:`shutdown_telemetry`: a fiber
    disposer can run while the process keeps serving, so it may only flush.
    """
    if _tracer_provider is not None:
        try:
            _tracer_provider.force_flush()
        except Exception as e:
            _logger.debug("tracer provider flush failed: %s", e)
    if _meter_provider is not None:
        try:
            _meter_provider.force_flush()
        except Exception as e:
            _logger.debug("meter provider flush failed: %s", e)
    if _logger_provider is not None:
        try:
            _logger_provider.force_flush()
        except Exception as e:
            _logger.debug("logger provider flush failed: %s", e)


def shutdown_telemetry() -> None:
    """Flush + shutdown providers; safe to call multiple times."""
    global _tracer_provider, _meter_provider, _logger_provider, _otel_logger
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
        except Exception as e:
            _logger.debug("tracer provider shutdown failed: %s", e)
        _tracer_provider = None
    if _meter_provider is not None:
        try:
            _meter_provider.shutdown()
        except Exception as e:
            _logger.debug("meter provider shutdown failed: %s", e)
        _meter_provider = None
    if _logger_provider is not None:
        try:
            _logger_provider.shutdown()
        except Exception as e:
            _logger.debug("logger provider shutdown failed: %s", e)
        _logger_provider = None
    _otel_logger = None


__all__ = [
    "ENVIRONMENT",
    "PROGRESS_VERSION",
    "SAMPLING_RATE",
    "SERVICE_NAME",
    "effective_environment",
    "flush_telemetry",
    "get_otel_logger",
    "instrument_fastapi_app",
    "otlp_mode",
    "setup_telemetry",
    "shutdown_telemetry",
]
