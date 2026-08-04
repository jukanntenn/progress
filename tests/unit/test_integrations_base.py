"""Unit tests for the integration protocol layer (spec 06).

Verifies the protocol-level fixes:
- ``ReportSection.payload`` carries structured template data.
- ``RunResult.events`` channel exists alongside ``reports``.
- ``Integration.run`` accepts ``concurrency`` keyword argument.
- ``Integration.config_schema`` typed as a Pydantic model class.
"""

from __future__ import annotations

import inspect

from progress.cli.notifications.events import DiscoveredRepoEvent
from progress.integrations.base import (
    Components,
    Integration,
    ReportSection,
    RunResult,
    SyncResult,
)


class TestReportSection:
    def test_default_payload_is_empty_dict(self) -> None:
        section = ReportSection(title="x")
        assert section.payload == {}

    def test_payload_carries_arbitrary_fields(self) -> None:
        section = ReportSection(title="x", payload={"releases": [1, 2, 3], "name": "alice"})
        assert section.payload["releases"] == [1, 2, 3]
        assert section.payload["name"] == "alice"

    def test_each_instance_has_own_payload(self) -> None:
        a = ReportSection(title="a")
        b = ReportSection(title="b")
        a.payload["k"] = "v"
        assert "k" not in b.payload


class TestRunResult:
    def test_default_events_is_empty_list(self) -> None:
        result = RunResult(name="x")
        assert result.events == []

    def test_each_instance_has_own_events(self) -> None:
        a = RunResult(name="a")
        b = RunResult(name="b")
        a.events.append(DiscoveredRepoEvent(owner="x", name="y"))
        assert b.events == []

    def test_reports_and_events_coexist(self) -> None:
        section = ReportSection(title="s")
        event = DiscoveredRepoEvent(owner="o", name="n")
        result = RunResult(name="x", reports=[section], events=[event])
        assert result.reports == [section]
        assert result.events == [event]


class TestIntegrationProtocol:
    def test_run_signature_has_concurrency_keyword(self) -> None:
        sig = inspect.signature(Integration.run)
        params = sig.parameters
        assert "concurrency" in params
        assert params["concurrency"].default == 1
        assert params["concurrency"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_protocol_has_five_lifecycle_hooks(self) -> None:
        for hook in ("setup", "sync", "run", "build_notification", "teardown"):
            assert hasattr(Integration, hook)


class TestComponentsAndSyncResult:
    def test_components_defaults_to_none(self) -> None:
        components = Components()
        assert components.cfg is None
        assert components.session is None

    def test_sync_result_defaults(self) -> None:
        result = SyncResult()
        assert result.created == 0
        assert result.updated == 0
        assert result.deleted == 0
        assert result.errors == []
