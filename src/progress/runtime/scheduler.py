"""In-process scheduler (PRFC 2026-08-31 phase 3): ``every(cron, fn)``.

croniter computes the next fire in local time (supercronic parity); each
entry owns one asyncio task that sleeps to the next fire, re-computes after
every trigger (no drift accumulation), and holds a per-entry mutex — a
trigger while the previous run is still active is skipped with a warning
(supercronic's per-job serialization). Missed fires during downtime are not
caught up. ``every`` returns a ``Disposable`` that cancels and deregisters.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any

from croniter import croniter

from progress.kernel import Definition, Entry

logger = logging.getLogger(__name__)


class SchedulerService(Definition):
    service_name = "scheduler"


@dataclass
class _Schedule:
    expression: str
    callback: Callable[[], Any]
    task: asyncio.Task[None] | None = None
    running: bool = False
    name: str = ""


@dataclass
class SchedulerHandle:
    """The ``ctx.scheduler`` service value."""

    schedules: dict[str, _Schedule] = field(default_factory=dict)

    def every(self, expression: str, callback: Callable[[], Any], *, name: str = "") -> Callable[[], None]:
        schedule_id = name or f"cron:{expression}:{len(self.schedules)}"
        schedule = _Schedule(expression=expression, callback=callback, name=schedule_id)
        self.schedules[schedule_id] = schedule
        schedule.task = asyncio.get_running_loop().create_task(self._loop(schedule))

        def _dispose() -> None:
            self.cancel(schedule_id)

        return _dispose

    def cancel(self, schedule_id: str) -> None:
        schedule = self.schedules.pop(schedule_id, None)
        if schedule is not None and schedule.task is not None and not schedule.task.done():
            schedule.task.cancel()

    def next_fire(self, expression: str, *, now: datetime | None = None) -> datetime:
        base = now or datetime.now(tz=UTC).astimezone()
        iterator = croniter(expression, base)
        return iterator.get_next(datetime)

    def entries(self) -> list[dict[str, str]]:
        return [{"name": s.name, "cron": s.expression, "running": str(s.running)} for s in self.schedules.values()]

    async def _loop(self, schedule: _Schedule) -> None:
        while True:
            now = datetime.now(tz=UTC).astimezone()
            next_fire = croniter(schedule.expression, now).get_next(datetime)
            delay = (next_fire - datetime.now(tz=UTC).astimezone()).total_seconds()
            await asyncio.sleep(max(delay, 0))
            if not acquire_run_slot(schedule):
                continue
            schedule.running = True
            try:
                await _maybe_await(schedule.callback())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduled callback failed for %s", schedule.name)
            finally:
                schedule.running = False


def acquire_run_slot(schedule: _Schedule) -> bool:
    """Per-entry mutex: a trigger while the previous run is active is skipped."""
    if schedule.running:
        logger.warning(
            "schedule %s skipped: previous run still active (per-entry mutex)",
            schedule.name,
        )
        return False
    return True


async def _maybe_await(value: Any) -> None:
    if asyncio.iscoroutine(value) or hasattr(value, "__await__"):
        await value


def make_scheduler_entry() -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        ctx.provide(SchedulerService, SchedulerHandle())

    return Entry(id="scheduler", plugin=_apply, inject=["config"])


__all__ = ["SchedulerHandle", "SchedulerService", "acquire_run_slot", "make_scheduler_entry"]
