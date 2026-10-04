"""Scheduler service (PRFC phase 3): croniter math, every() lifecycle, mutex."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from progress.runtime.scheduler import SchedulerHandle, _Schedule, acquire_run_slot


def test_next_fire_computes_from_cron_expression():
    scheduler = SchedulerHandle()
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    assert scheduler.next_fire("*/15 * * * *", now=now) == datetime(2026, 9, 1, 12, 15, 0, tzinfo=UTC)
    daily = scheduler.next_fire("0 9 * * *", now=now)
    assert (daily.hour, daily.minute, daily.day) == (9, 0, 2)


def test_next_fire_always_in_the_future_no_catch_up():
    scheduler = SchedulerHandle()
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    for expression in ("*/5 * * * *", "0 * * * *", "0 9 * * 1"):
        assert scheduler.next_fire(expression, now=now) > now


async def test_every_registers_and_dispose_cancels():
    fired: list[int] = []

    async def _cb() -> None:
        fired.append(1)

    scheduler = SchedulerHandle()
    dispose = scheduler.every("*/5 * * * *", _cb, name="probe")
    assert scheduler.entries()[0]["name"] == "probe"
    dispose()
    assert scheduler.entries() == []
    await asyncio.sleep(0)
    assert fired == []


def test_acquire_run_slot_is_per_entry_mutex():
    schedule = _Schedule(expression="* * * * *", callback=lambda: None, name="t")
    assert acquire_run_slot(schedule) is True
    schedule.running = True
    assert acquire_run_slot(schedule) is False
    schedule.running = False
    assert acquire_run_slot(schedule) is True
