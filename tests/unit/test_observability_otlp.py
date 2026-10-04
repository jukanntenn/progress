"""OTLP observability wiring: env-var identity precedence + the structlog→OTel log bridge."""

from __future__ import annotations

import logging
import sys
from typing import Any

import pytest

from progress.observability import logging as obs_logging
from progress.observability.logging import OtelLogHandler, configure_structlog
from progress.observability.telemetry import (
    _build_resource,
    effective_environment,
    otlp_mode,
)


class _RecordingLogger:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


@pytest.fixture
def recording_logger(monkeypatch: pytest.MonkeyPatch) -> _RecordingLogger:
    recorder = _RecordingLogger()
    monkeypatch.setattr(obs_logging, "get_otel_logger", lambda: recorder)
    return recorder


def _emit_record(msg: Any, level: int, name: str = "test.bridge") -> None:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )
    OtelLogHandler().emit(record)


def test_bridge_noop_without_otel_logger():
    _emit_record({"event": "e", "level": "error"}, logging.ERROR)  # must not raise


def test_bridge_ships_info_and_above(recording_logger: _RecordingLogger):
    _emit_record({"event": "info event", "level": "info", "integration": "repo"}, logging.INFO)
    _emit_record({"event": "debug event", "level": "debug"}, logging.DEBUG)
    _emit_record({"event": "error event", "level": "error"}, logging.ERROR)
    bodies = [r["body"] for r in recording_logger.records]
    assert bodies == ["info event", "error event"]
    assert recording_logger.records[0]["severity_text"] == "INFO"
    assert recording_logger.records[1]["severity_text"] == "ERROR"
    assert recording_logger.records[0]["attributes"] == {"integration": "repo"}


def test_bridge_drops_reserved_and_non_scalar_attributes(recording_logger: _RecordingLogger):
    _emit_record(
        {
            "event": "e",
            "level": "warning",
            "timestamp": "2026-10-04 12:00:00",
            "trace_id": "0" * 32,
            "span_id": "0" * 16,
            "logger": "x",
            "_record": object(),
            "ratio": 0.5,
            "count": 2,
            "payload": {"nested": "dict"},
        },
        logging.WARNING,
    )
    (record,) = recording_logger.records
    assert record["attributes"] == {"ratio": 0.5, "count": 2}


def test_bridge_renders_exception_into_attributes(recording_logger: _RecordingLogger):
    try:
        raise ValueError("kaputt")
    except ValueError:
        _emit_record({"event": "e", "level": "error", "exc_info": sys.exc_info()}, logging.ERROR)
    (record,) = recording_logger.records
    assert "ValueError: kaputt" in record["attributes"]["exception"]


def test_bridge_handles_stdlib_records(recording_logger: _RecordingLogger):
    _emit_record("plain %s message", logging.WARNING, name="plainlib")
    (record,) = recording_logger.records
    assert record["body"] == "plain %s message"
    assert record["severity_text"] == "WARNING"


def test_bridge_passes_current_context(recording_logger: _RecordingLogger):
    _emit_record({"event": "e", "level": "info"}, logging.INFO)
    assert recording_logger.records[0]["context"] is not None


def test_configure_structlog_attaches_single_bridge_handler(tmp_path):
    configure_structlog(tmp_path)
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, OtelLogHandler)]
    assert len(handlers) == 1
    configure_structlog(tmp_path)
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, OtelLogHandler)]
    assert len(handlers) == 1  # reconfigure removes the stale bridge, no duplication


def test_effective_environment_env_var_beats_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    assert effective_environment("production") == "production"
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=staging")
    assert effective_environment("production") == "staging"


def test_resource_merge_env_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    plain = _build_resource("production")
    assert plain.attributes["service.name"] == "progress"
    assert plain.attributes["deployment.environment.name"] == "production"

    monkeypatch.setenv("OTEL_SERVICE_NAME", "progress-staging")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=staging")
    overridden = _build_resource("production")
    assert overridden.attributes["service.name"] == "progress-staging"
    assert overridden.attributes["deployment.environment.name"] == "staging"


def test_otlp_mode_follows_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otlp_mode() is False
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert otlp_mode() is True
