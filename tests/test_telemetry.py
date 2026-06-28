"""OpenTelemetry + Bugsink observability setup tests."""

import json

import pytest

from progress import telemetry
from progress.config import BugsinkConfig, ObservabilityConfig, OTelConfig


@pytest.fixture(autouse=True)
def _reset_telemetry():
    telemetry.shutdown_observability()
    yield
    telemetry.shutdown_observability()


def test_disabled_is_noop(tmp_path):
    cfg = ObservabilityConfig(
        otel=OTelConfig(enabled=False, export_dir=str(tmp_path)),
        bugsink=BugsinkConfig(dsn=None),
    )

    telemetry.setup_observability(cfg, component="cli")

    assert telemetry.is_enabled() is False
    assert not (tmp_path / "traces.jsonl").exists()
    assert not (tmp_path / "metrics.jsonl").exists()


def test_recorders_are_noop_when_disabled():
    telemetry.record_repo_checked(status="success")
    telemetry.record_analysis(provider="claude_code", duration_s=1.0, ok=True)
    telemetry.record_analysis(
        provider="codex", duration_s=2.0, ok=False, reason="timeout"
    )
    telemetry.record_notification_sent(channel="feishu")
    telemetry.record_report_generated(storage="db")


def test_compact_json_is_single_line():
    pretty = '{\n  "name": "span",\n  "duration": 12\n}'

    compact = telemetry._compact_json(pretty)

    assert compact.endswith("\n")
    assert compact.count("\n") == 1
    assert json.loads(compact) == {"name": "span", "duration": 12}


def test_before_send_scrubs_known_secret_keys():
    event = {
        "request": {
            "headers": {"authorization": "Bearer abc", "x-github-token": "ghp_x"}
        },
        "extra": {"gh_token": "ghp_secret", "kept": "visible"},
        "tags": {"dsn": "http://key@host/1"},
    }

    scrubbed = telemetry._before_send(event, {})

    assert scrubbed["request"]["headers"]["authorization"] == telemetry._REDACTED
    assert scrubbed["request"]["headers"]["x-github-token"] == telemetry._REDACTED
    assert scrubbed["extra"]["gh_token"] == telemetry._REDACTED
    assert scrubbed["extra"]["kept"] == "visible"
    assert scrubbed["tags"]["dsn"] == telemetry._REDACTED


def test_enabled_writes_traces_and_metrics(tmp_path):
    cfg = ObservabilityConfig(otel=OTelConfig(enabled=True, export_dir=str(tmp_path)))

    telemetry.setup_observability(cfg, component="cli")
    assert telemetry.is_enabled() is True

    tracer = telemetry.get_tracer("test")
    with tracer.start_as_current_span(
        "progress.check", attributes={"progress.repo_count": 1}
    ):
        with tracer.start_as_current_span("repo.sync", attributes={"repo.name": "a/b"}):
            pass

    telemetry.record_repo_checked(status="success")
    telemetry.shutdown_observability()

    lines = (tmp_path / "traces.jsonl").read_text().splitlines()
    assert len(lines) >= 2
    spans = {json.loads(line)["name"]: json.loads(line) for line in lines}
    assert "progress.check" in spans
    assert "repo.sync" in spans
    root_span_id = spans["progress.check"]["context"]["span_id"]
    assert spans["repo.sync"]["parent_id"] == root_span_id

    metric_lines = (tmp_path / "metrics.jsonl").read_text().splitlines()
    assert metric_lines
    names = {
        m["name"]
        for line in metric_lines
        for rm in json.loads(line)["resource_metrics"]
        for sm in rm["scope_metrics"]
        for m in sm["metrics"]
    }
    assert "progress.repos.checked" in names


def test_shutdown_clears_provider_references():
    # Regression: shutdown must clear stale provider references, otherwise a
    # later disabled setup would flip is_enabled() back to True (found in
    # acceptance testing). Probes state directly to avoid the OTel global
    # provider "set once" constraint across tests.
    telemetry._STATE.tracer_provider = object()
    telemetry._STATE.meter_provider = object()
    telemetry._STATE.enabled = True

    telemetry.shutdown_observability()

    assert telemetry._STATE.tracer_provider is None
    assert telemetry._STATE.meter_provider is None
    assert telemetry.is_enabled() is False

    telemetry.setup_observability(ObservabilityConfig(), component="cli")
    assert telemetry.is_enabled() is False
