"""Component tests for scheduled-run arming against the real integration shim.

The incident these pin (issue #36): the ``scheduled-run`` row applies in the
same settle pass as the ``integrations`` row, but the per-integration child
fibers load one pass later — an arm-time membership snapshot therefore sees
an empty registry and schedules nothing, while every run still reports
success. The trees here boot the real ``@register`` shim (child fibers, the
two-pass settle), the real scheduler and scheduled-run rows, then fire the
armed trigger directly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, override

from progress.cli.notifications.base import ChannelPayload, ContentType
from progress.cli.notifications.events import NotificationEvent
from progress.config.root import CoreConfig
from progress.integrations.base import RunResult, SyncResult
from progress.kernel import Entry, boot
from progress.runtime.integrations import make_integrations_entry
from progress.runtime.runner import make_runner_entry
from progress.runtime.scheduled_run import make_scheduled_run_entry
from progress.runtime.scheduler import make_scheduler_entry

_DISCOVER: dict[str, Any] = {}


class FakeIntegration:
    """Minimal integration stand-in; no ``config_schema`` (no cron override)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run_calls = 0

    async def setup(self, ctx: Any) -> None:
        return None

    async def sync(self) -> SyncResult:
        return SyncResult()

    async def run(self, *, concurrency: int = 1) -> RunResult:
        self.run_calls += 1
        return RunResult(name=self.name)

    async def teardown(self) -> None:
        return None

    async def build_notification(self, *, result: RunResult, reports: list[Any]) -> list[NotificationEvent]:
        return []


class _StubReportOutcome:
    report_ids: list[int] = []
    errors: list[Any] = []
    events: list[Any] = []
    by_integration: list[Any] = []


class _NullRenderer:
    def render(self, event: Any, content_type: ContentType) -> ChannelPayload:
        raise AssertionError("no notification is rendered in this tree")


class _ArmedMessageHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__()
        self.sink = sink

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(record.getMessage())


async def _drain_until(predicate, *, timeout: float = 2.0) -> None:
    """Yield to the loop until ``predicate()`` holds (emit-mode listeners run as tasks)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached before timeout")
        await asyncio.sleep(0.01)


def _armed_label(armed_messages: list[str], expression: str) -> str | None:
    for message in reversed(armed_messages):
        if message.startswith("scheduled-run armed:") and f"{expression} -> " in message:
            segment = message.split(f"{expression} -> ", 1)[1]
            return segment.split(" (", 1)[0]
    return None


async def test_armed_schedule_runs_mounted_integrations(tmp_state_home: str, monkeypatch):
    """After boot the armed trigger runs every mounted integration (the #36 regression)."""
    alpha, beta = FakeIntegration("alpha"), FakeIntegration("beta")
    _DISCOVER["alpha"] = lambda: alpha
    _DISCOVER["beta"] = lambda: beta

    cfg = CoreConfig(state_home=tmp_state_home)
    cfg.schedule = type(cfg.schedule)(cron="0 6 * * *")

    async def _stub_base(ctx: Any, config: Any) -> None:
        from progress.runtime.notifications import NotificationsHub  # noqa: PLC0415

        ctx.provide("config", cfg)
        ctx.provide("http", None)
        ctx.provide("telemetry", object())
        ctx.provide("telemetryOtel", True)
        ctx.provide("notifications", NotificationsHub(_NullRenderer()))
        ctx.provide("ai", None)

    async def _stub_reports(outcome: Any, cfg_: Any, name: str, *, session: Any = None) -> Any:
        return _StubReportOutcome()

    monkeypatch.setattr("progress.runtime.runner.run_for_integration", _stub_reports)
    monkeypatch.setattr("progress.runtime.integrations.discover_integrations", lambda: dict(_DISCOVER))

    armed_messages: list[str] = []
    handler = _ArmedMessageHandler(armed_messages)
    logger = logging.getLogger("progress.runtime.scheduled_run")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        async with boot(
            [
                Entry(id="stub-base", plugin=_stub_base),
                make_integrations_entry(),
                make_runner_entry(),
                make_scheduler_entry(),
                make_scheduled_run_entry(),
            ]
        ) as ctx:
            await _drain_until(lambda: _armed_label(armed_messages, "0 6 * * *") == "alpha,beta")
            await ctx.scheduler.schedules["scheduled-run"].callback()
            assert alpha.run_calls == 1
            assert beta.run_calls == 1
    finally:
        logger.removeHandler(handler)
        _DISCOVER.clear()
