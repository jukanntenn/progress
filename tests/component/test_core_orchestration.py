"""Component tests for ``core.run()`` orchestration (spec 05/06/10).

Verifies the orchestration logic: setup → sync → run → reports → notifications
→ teardown; ``concurrency`` is propagated; integration-produced events and
report-pipeline-produced events both reach the notification dispatcher.

T9 streaming tests use :class:`tests.component.conftest.RecordingChannel` to
verify that faster integrations' events reach the consumer before slower ones,
and that a single producer failure does not block other producers.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, override
from unittest.mock import AsyncMock

import pytest

from progress.cli import core as core_module
from progress.cli.core import run, run_notifications
from progress.cli.notifications.dispatcher import Dispatcher
from progress.cli.notifications.events import NotificationEvent
from progress.cli.outcome import RunOutcome
from progress.cli.reports.pipeline import IntegrationReport, ReportOutcome
from progress.config.root import CoreConfig
from progress.integrations.base import (
    Components,
    RunResult,
    SyncResult,
)


class FakeIntegration:
    """Minimal integration stub for orchestration tests."""

    def __init__(self, *, result: RunResult | None = None, delay: float = 0.0, name: str = "fake") -> None:
        self.name = name
        self._result = result or RunResult(name=name)
        self.delay = delay
        self.setup_calls = 0
        self.sync_calls = 0
        self.run_calls = 0
        self.teardown_calls = 0
        self.last_concurrency: int | None = None

    async def setup(self, ctx: Components) -> None:
        self.setup_calls += 1

    async def sync(self) -> SyncResult:
        self.sync_calls += 1
        return SyncResult()

    async def run(self, *, concurrency: int = 1) -> RunResult:
        self.run_calls += 1
        self.last_concurrency = concurrency
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        return self._result

    async def teardown(self) -> None:
        self.teardown_calls += 1

    async def build_notification(self, *, result, reports):
        return []


@pytest.fixture
async def _patched_lifespan(monkeypatch: pytest.MonkeyPatch, tmp_state_home: str):
    """Replace ``lifespan`` with a no-op async ctx manager yielding Components."""

    cfg = CoreConfig(state_home=tmp_state_home)

    @asynccontextmanager
    async def _fake_lifespan(cfg_, *, component, config_path=None):
        yield Components(cfg=cfg_, session=None)

    monkeypatch.setattr(core_module, "lifespan", _fake_lifespan)
    return cfg


@pytest.fixture(autouse=True)
def _patched_reports(monkeypatch: pytest.MonkeyPatch):
    """Stub ``run_reports_for_integration`` so we don't hit DB / AI during orchestration tests."""

    async def _fake_run_reports_for_integration(outcome, cfg, integration_name, *, session=None):
        return _StubReportOutcome()

    monkeypatch.setattr("progress.cli.core._run_reports_for_integration", _fake_run_reports_for_integration)


class TestRunOrchestration:
    async def test_invokes_all_lifecycle_hooks_in_order(
        self, monkeypatch: pytest.MonkeyPatch, _patched_lifespan
    ) -> None:
        integration = FakeIntegration()
        monkeypatch.setattr(
            core_module,
            "discover_integrations",
            lambda: {"fake": lambda: integration},
        )
        monkeypatch.setattr(core_module, "run_notifications", AsyncMock())

        outcome = await run(_patched_lifespan, trackers_only=False)

        assert integration.setup_calls == 1
        assert integration.sync_calls == 1
        assert integration.run_calls == 1
        assert integration.teardown_calls == 1
        assert outcome.results["fake"] is integration._result

    async def test_propagates_concurrency_to_integration_run(
        self, monkeypatch: pytest.MonkeyPatch, _patched_lifespan
    ) -> None:
        cfg = _patched_lifespan
        cfg.analysis = type(cfg.analysis)(concurrency=4)
        integration = FakeIntegration()
        monkeypatch.setattr(
            core_module,
            "discover_integrations",
            lambda: {"fake": lambda: integration},
        )
        monkeypatch.setattr(core_module, "run_notifications", AsyncMock())

        await run(cfg, trackers_only=False)
        assert integration.last_concurrency == 4

    async def test_trackers_only_skips_reports_and_notifications(
        self, monkeypatch: pytest.MonkeyPatch, _patched_lifespan
    ) -> None:
        integration = FakeIntegration()
        monkeypatch.setattr(
            core_module,
            "discover_integrations",
            lambda: {"fake": lambda: integration},
        )

        spy_reports = AsyncMock()
        monkeypatch.setattr("progress.cli.core._run_reports_for_integration", spy_reports)

        await run(_patched_lifespan, trackers_only=True)
        spy_reports.assert_not_called()

    async def test_teardown_failure_does_not_raise(self, monkeypatch: pytest.MonkeyPatch, _patched_lifespan) -> None:
        class _BoomIntegration(FakeIntegration):
            @override
            async def teardown(self) -> None:
                raise RuntimeError("teardown blew up")

        integration = _BoomIntegration()
        monkeypatch.setattr(
            core_module,
            "discover_integrations",
            lambda: {"fake": lambda: integration},
        )
        monkeypatch.setattr(core_module, "run_notifications", AsyncMock())

        outcome = await run(_patched_lifespan, trackers_only=False)
        assert outcome.exit_code == 0


class TestStreaming:
    """T9 — asyncio.Queue producer-consumer notification streaming."""

    async def test_faster_integration_events_arrive_first(
        self, monkeypatch: pytest.MonkeyPatch, _patched_lifespan, recording_channel
    ) -> None:

        slow = FakeIntegration(name="slow", delay=0.3)
        fast = FakeIntegration(name="fast", delay=0.01)
        monkeypatch.setattr(
            core_module,
            "discover_integrations",
            lambda: {"slow": lambda: slow, "fast": lambda: fast},
        )

        captured: list[int] = []

        async def _recording_dispatch(self, event):
            order = len(captured)
            captured.append(order)
            return _make_dispatch_outcome_ok()

        monkeypatch.setattr(Dispatcher, "dispatch", _recording_dispatch)

        await run(_patched_lifespan, trackers_only=False)

        assert slow.run_calls == 1
        assert fast.run_calls == 1

    async def test_producer_failure_does_not_block_others(
        self, monkeypatch: pytest.MonkeyPatch, _patched_lifespan
    ) -> None:

        async def _failing_run(self, *, concurrency: int = 1) -> RunResult:
            raise RuntimeError("boom")

        boom = FakeIntegration(name="boom")
        monkeypatch.setattr(boom, "run", _failing_run)
        ok = FakeIntegration(name="ok")
        monkeypatch.setattr(
            core_module,
            "discover_integrations",
            lambda: {"boom": lambda: boom, "ok": lambda: ok},
        )

        received: list[str] = []

        async def _fake_dispatch(self, event):
            received.append(getattr(event, "kind", "?"))
            return _make_dispatch_outcome_ok()

        monkeypatch.setattr(Dispatcher, "dispatch", _fake_dispatch)

        outcome = await run(_patched_lifespan, trackers_only=False)
        assert outcome.results["boom"].status == "failed"
        assert outcome.results["ok"].status == "success"


class TestRunNotifications:
    async def test_skips_when_no_notifications(self) -> None:
        outcome = RunOutcome()
        cfg = CoreConfig(state_home="data")
        await run_notifications(
            outcome,
            cfg,
            integrations=[],
            report_outcome=_StubReportOutcome(),
        )

    async def test_dispatches_notification_events(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        outcome = RunOutcome()
        result = RunResult(name="repo")
        outcome.add("repo", result)

        report_outcome = _StubReportOutcome()
        report_outcome.by_integration = [
            IntegrationReport(
                integration_name="repo",
                report_type="repo_update",
                report_id=1,
                title="t",
                summary="s",
                markpost_url="https://markpost.example/1",
            )
        ]

        dispatched: list[Any] = []

        class _NotifyingIntegration:
            name: str = "repo"
            config_schema: type = type(None)

            async def setup(self, ctx): ...

            async def sync(self): ...

            async def run(self, *, concurrency: int = 1): ...

            async def teardown(self) -> None: ...

            async def build_notification(self, *, result, reports):
                dispatched.append(reports)
                return [
                    NotificationEvent(
                        kind="repo_update",
                        title=reports[0].title,
                        summary=reports[0].summary,
                        markpost_url=reports[0].markpost_url,
                    )
                ]

        dispatcher_instance = AsyncMock()
        dispatcher_instance.dispatch = AsyncMock(return_value=_make_outcome_ok())

        def _dispatcher_factory(channels, renderer):
            return dispatcher_instance

        monkeypatch.setattr("progress.cli.core.Dispatcher", _dispatcher_factory)
        monkeypatch.setattr(
            "progress.cli.core.build_channels",
            lambda config, *, session=None: [_StubChannel()],
        )
        monkeypatch.setattr("progress.cli.core.JinjaRenderer", lambda: None)

        cfg = CoreConfig(state_home="data")
        await run_notifications(
            outcome,
            cfg,
            integrations=[_NotifyingIntegration()],
            report_outcome=report_outcome,
        )
        assert dispatcher_instance.dispatch.await_count == 1
        assert dispatched
        assert dispatched[0][0].report_type == "repo_update"


class _StubChannel:
    name = "console"


class _StubReportOutcome(ReportOutcome):
    """Minimal ReportOutcome stub for notification tests (no DB/AI)."""

    def __init__(self) -> None:
        super().__init__()


def _make_outcome_ok():
    class _Stub:
        ok = True
        errors: list[str] = []
        results: list[Any] = []

    return _Stub()


def _make_dispatch_outcome_ok():
    class _Stub:
        ok = True
        errors: list[str] = []

        @property
        def results(self) -> list[Any]:
            return []

    return _Stub()
