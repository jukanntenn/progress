"""Component tests for the event-driven pipeline (PRFC 2026-08-31 phase 2).

Boots a real kernel tree — stub base services, the real ``@register`` shim
mounting fake integrations as child fibers, the real runner — and drives
``run_once``: lifecycle hooks, concurrency propagation, trackers-only, the
streaming semantics (fast integrations dispatch first), producer failure
isolation, the ``integration/pre-run`` veto, the sole-author
``notification/build`` accumulator, and third-party entry_points loading
unchanged through the shim.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, override

import pytest

from progress.cli.notifications.events import NotificationEvent
from progress.config.root import CoreConfig
from progress.integrations.base import Components, RunResult, SyncResult
from progress.integrations.registry import discover_integrations
from progress.kernel import Entry, boot
from progress.runtime.integrations import make_integrations_entry
from progress.runtime.runner import make_runner_entry


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
        self.notification_events: list[NotificationEvent] = []
        self.build_calls = 0

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

    async def build_notification(self, *, result: RunResult, reports: list[Any]) -> list[NotificationEvent]:
        self.build_calls += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        return list(self.notification_events)


class _StubReportOutcome:
    """Minimal report-outcome stand-in (no DB/AI)."""

    report_ids: list[int] = []
    errors: list[Any] = []
    events: list[Any] = []
    by_integration: list[Any] = []


_DISCOVER: dict[str, Any] = {}


@pytest.fixture
def pipeline_tree(tmp_state_home: str, monkeypatch: pytest.MonkeyPatch):
    """Factory for a real kernel tree; enter it after filling ``_DISCOVER``.

    Tests register their fake integrations first, then ``async with
    pipeline_tree() as (ctx, cfg)`` boots the full tree — stub base services,
    the real ``@register`` shim, the real runner — with the reports pipeline
    stubbed (no DB/AI).
    """
    cfg = CoreConfig(state_home=tmp_state_home)

    async def _stub_base(ctx: Any, config: Any) -> None:
        from progress.runtime.notifications import NotificationsHub  # noqa: PLC0415

        ctx.provide("config", cfg)
        ctx.provide("http", None)
        ctx.provide("telemetry", object())
        ctx.provide("telemetryOtel", True)
        ctx.provide("notifications", NotificationsHub(renderer=None))
        ctx.provide("ai", None)

    async def _stub_reports(outcome: Any, cfg_: Any, name: str, *, session: Any = None) -> Any:
        return _StubReportOutcome()

    monkeypatch.setattr("progress.runtime.runner.run_for_integration", _stub_reports)
    monkeypatch.setattr("progress.runtime.integrations.discover_integrations", lambda: dict(_DISCOVER))

    @asynccontextmanager
    async def _factory():
        try:
            async with boot(
                [
                    Entry(id="stub-base", plugin=_stub_base),
                    make_integrations_entry(),
                    make_runner_entry(),
                ]
            ) as ctx:
                yield ctx, cfg
        finally:
            _DISCOVER.clear()

    return _factory


@pytest.fixture
def dispatch_order(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the dispatcher; record per-event kinds in dispatch order."""
    order: list[str] = []

    async def _fake_dispatch(self: Any, event: Any) -> Any:
        order.append(getattr(event, "kind", "?"))
        return _ok_outcome()

    monkeypatch.setattr("progress.runtime.notifications.NotificationsHub.dispatch", _fake_dispatch)
    return order


def _ok_outcome() -> Any:
    class _Stub:
        ok = True
        errors: list[Any] = []
        results: list[Any] = []

    return _Stub()


class TestRunOrchestration:
    async def test_invokes_all_lifecycle_hooks_in_order(self, pipeline_tree) -> None:
        integration = FakeIntegration()
        _DISCOVER["fake"] = lambda: integration

        async with pipeline_tree() as (ctx, _cfg):
            outcome = await ctx.runner.run_once(trackers_only=False)
            assert integration.teardown_calls == 0  # teardown runs at tree disposal
            assert outcome.results["fake"] is integration._result

        assert integration.setup_calls == 1
        assert integration.sync_calls == 1
        assert integration.run_calls == 1
        assert integration.teardown_calls == 1

    async def test_propagates_concurrency_to_integration_run(self, pipeline_tree) -> None:
        integration = FakeIntegration()
        _DISCOVER["fake"] = lambda: integration
        async with pipeline_tree() as (ctx, cfg):
            cfg.analysis = type(cfg.analysis)(concurrency=4)
            await ctx.runner.run_once(trackers_only=False)
        assert integration.last_concurrency == 4

    async def test_only_runs_requested_subset(self, pipeline_tree) -> None:
        selected = FakeIntegration(name="a")
        excluded = FakeIntegration(name="b")
        _DISCOVER["a"] = lambda: selected
        _DISCOVER["b"] = lambda: excluded
        async with pipeline_tree() as (ctx, _cfg):
            outcome = await ctx.runner.run_once(only={"a"})
            assert selected.run_calls == 1
            assert excluded.run_calls == 0
            assert set(outcome.results) == {"a"}

    async def test_only_ignores_unknown_names(self, pipeline_tree) -> None:
        integration = FakeIntegration(name="a")
        _DISCOVER["a"] = lambda: integration
        async with pipeline_tree() as (ctx, _cfg):
            outcome = await ctx.runner.run_once(only={"a", "ghost"})
            assert integration.run_calls == 1
            assert set(outcome.results) == {"a"}

    async def test_trackers_only_skips_reports_and_notifications(self, pipeline_tree, monkeypatch) -> None:
        integration = FakeIntegration()
        _DISCOVER["fake"] = lambda: integration
        calls: list[str] = []

        async def _counting(outcome, cfg_, name, *, session=None):
            calls.append(name)
            return _StubReportOutcome()

        monkeypatch.setattr("progress.runtime.runner.run_for_integration", _counting)
        async with pipeline_tree() as (ctx, _cfg):
            await ctx.runner.run_once(trackers_only=True)
        assert calls == []
        assert integration.build_calls == 0

    async def test_teardown_failure_does_not_raise(self, pipeline_tree) -> None:
        class _BoomIntegration(FakeIntegration):
            @override
            async def teardown(self) -> None:
                raise RuntimeError("teardown blew up")

        integration = _BoomIntegration()
        _DISCOVER["fake"] = lambda: integration
        async with pipeline_tree() as (ctx, _cfg):
            outcome = await ctx.runner.run_once(trackers_only=False)
            assert outcome.exit_code == 0


class TestStreaming:
    async def test_faster_integration_dispatches_first(self, pipeline_tree, dispatch_order) -> None:
        slow = FakeIntegration(name="slow", delay=0.15)
        fast = FakeIntegration(name="fast", delay=0.01)
        slow.notification_events = [NotificationEvent(kind="slow_update", title="s", summary="s")]
        fast.notification_events = [NotificationEvent(kind="fast_update", title="f", summary="f")]
        _DISCOVER["slow"] = lambda: slow
        _DISCOVER["fast"] = lambda: fast
        async with pipeline_tree() as (ctx, _cfg):
            await ctx.runner.run_once(trackers_only=False)
        assert dispatch_order == ["fast_update", "slow_update"]

    async def test_producer_failure_does_not_block_others(self, pipeline_tree, dispatch_order) -> None:
        async def _failing_run(*, concurrency: int = 1) -> RunResult:
            raise RuntimeError("boom")

        boom = FakeIntegration(name="boom")
        boom.run = _failing_run
        ok = FakeIntegration(name="ok")
        ok.notification_events = [NotificationEvent(kind="ok_update", title="o", summary="o")]
        _DISCOVER["boom"] = lambda: boom
        _DISCOVER["ok"] = lambda: ok

        async with pipeline_tree() as (ctx, _cfg):
            outcome = await ctx.runner.run_once(trackers_only=False)

        assert outcome.results["boom"].status == "failed"
        assert outcome.results["ok"].status == "success"
        assert dispatch_order == ["ok_update"]


class TestPreRunPolicy:
    async def test_veto_skips_targeted_integration_only(self, pipeline_tree) -> None:
        victim = FakeIntegration(name="victim")
        survivor = FakeIntegration(name="survivor")
        _DISCOVER["victim"] = lambda: victim
        _DISCOVER["survivor"] = lambda: survivor

        async def _quiet_hours(payload, next_):
            if payload.name == "victim":
                payload.vetoed = True
                payload.reason = "quiet hours"
                return "vetoed"
            return await next_()

        async with pipeline_tree() as (ctx, _cfg):
            dispose = ctx.on("integration/pre-run", _quiet_hours)
            outcome = await ctx.runner.run_once(trackers_only=False)
            dispose()

        assert outcome.results["victim"].status == "skipped"
        assert "quiet hours" in outcome.results["victim"].summary
        assert victim.run_calls == 0
        assert outcome.results["survivor"].status == "success"
        assert survivor.run_calls == 1


class TestNotificationBuild:
    async def test_sole_author_accumulator(self, pipeline_tree, dispatch_order) -> None:
        repo = FakeIntegration(name="repo")
        repo.notification_events = [NotificationEvent(kind="repo_update", title="r", summary="r")]
        other = FakeIntegration(name="other")
        other.notification_events = [NotificationEvent(kind="other_update", title="o", summary="o")]
        _DISCOVER["repo"] = lambda: repo
        _DISCOVER["other"] = lambda: other
        async with pipeline_tree() as (ctx, _cfg):
            await ctx.runner.run_once(trackers_only=False)

        assert repo.build_calls == 1
        assert other.build_calls == 1
        assert dispatch_order == ["repo_update", "other_update"]


class TestThirdPartyEntryPoint:
    async def test_fake_entry_point_loads_through_shim(self, pipeline_tree, monkeypatch) -> None:
        """A third-party integration declared via entry_points runs unchanged."""
        thirdparty = FakeIntegration(name="thirdparty")
        _DISCOVER.clear()

        class _FakeEntryPoint:
            name = "thirdparty"

            @staticmethod
            def load() -> Any:
                return lambda: thirdparty

        import importlib.metadata  # noqa: PLC0415

        def _fake_entry_points(group: str):
            assert group == "progress.integrations"
            return [_FakeEntryPoint()]

        monkeypatch.setattr(importlib.metadata, "entry_points", _fake_entry_points)
        discovered = discover_integrations()
        assert "thirdparty" in discovered
        _DISCOVER["thirdparty"] = discovered["thirdparty"]

        async with pipeline_tree() as (ctx, _cfg):
            outcome = await ctx.runner.run_once(trackers_only=False)
            assert outcome.results["thirdparty"] is thirdparty._result
        assert thirdparty.setup_calls == 1
