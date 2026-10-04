"""OpenTelemetry provider/exporter setup + auto-instrumentation (spec 04).

Single OTel instrumentation layer: traces + metrics via OTel, errors via
Bugsink (sentry-sdk) with ``traces_sample_rate=0`` so the two never fight.

Defaults are code constants (spec 02): sampling rate, exporter switch, etc.
The exporter mode is also a code constant (``"file"`` JSONL by default); if
``OTEL_EXPORTER_OTLP_ENDPOINT`` env var is set, OTLP HTTP is used instead.
"""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.json.file.metric_exporter import FileMetricExporter
from opentelemetry.exporter.otlp.json.file.trace_exporter import FileSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
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
_logger = logging.getLogger(__name__)


def _build_resource(environment: str) -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": PROGRESS_VERSION,
            "deployment.environment.name": environment,
        }
    )


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


def setup_telemetry(observability_dir: Path, *, environment: str = ENVIRONMENT) -> None:
    """Initialize global TracerProvider + MeterProvider + auto-instrumentation.

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
    global _tracer_provider, _meter_provider
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
    """Force-export buffered spans/metrics without tearing the globals down.

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


def shutdown_telemetry() -> None:
    """Flush + shutdown providers; safe to call multiple times."""
    global _tracer_provider, _meter_provider
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


__all__ = [
    "ENVIRONMENT",
    "PROGRESS_VERSION",
    "SAMPLING_RATE",
    "SERVICE_NAME",
    "flush_telemetry",
    "instrument_fastapi_app",
    "setup_telemetry",
    "shutdown_telemetry",
]
