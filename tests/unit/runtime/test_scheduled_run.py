"""scheduled-run consumer (PRFC phase 4c): arming, idling, env fallback, cadence math."""

from __future__ import annotations

from typing import Any

import pytest

from progress.config.root import CoreConfig
from progress.kernel import Entry, boot
from progress.runtime.scheduled_run import (
    KUMA_PUSH_MAX_RETENTION,
    SCHEDULE_CRON_ENV,
    build_kuma_push_url,
    expected_max_gap_seconds,
    kuma_push_retention_seconds,
    make_scheduled_run_entry,
)


def _tree(cfg: CoreConfig) -> list[Entry]:
    async def config_entry(ctx: Any, config: Any) -> None:
        ctx.provide("config", cfg)

    async def integrations_entry(ctx: Any, config: Any) -> None:
        ctx.provide("integrations", object())

    async def runner_entry(ctx: Any, config: Any) -> None:
        handle = type("Handle", (), {"run_once": staticmethod(_noop_run)})()
        ctx.provide("runner", handle)

    async def scheduler_entry(ctx: Any, config: Any) -> None:
        from progress.runtime.scheduler import SchedulerHandle  # noqa: PLC0415

        ctx.provide("scheduler", SchedulerHandle())

    config_entry.name = "config"
    integrations_entry.name = "integrations"
    runner_entry.name = "runner"
    scheduler_entry.name = "scheduler"
    return [
        Entry(id="config", plugin=config_entry),
        Entry(id="integrations", plugin=integrations_entry),
        Entry(id="runner", plugin=runner_entry),
        Entry(id="scheduler", plugin=scheduler_entry),
    ]


async def _noop_run(**kwargs: Any) -> None:
    return None


async def test_empty_cron_leaves_row_idle(tmp_state_home: str):
    cfg = CoreConfig(state_home=tmp_state_home)
    async with boot(_tree(cfg) + [make_scheduled_run_entry()]) as ctx:  # noqa: RUF005
        scheduler = ctx.scheduler
        assert scheduler.entries() == []  # armed nothing


async def test_cron_arms_scheduled_run(tmp_state_home: str):
    cfg = CoreConfig(state_home=tmp_state_home)
    cfg.schedule = type(cfg.schedule)(cron="*/5 * * * *")
    async with boot(_tree(cfg) + [make_scheduled_run_entry()]) as ctx:  # noqa: RUF005
        entries = ctx.scheduler.entries()
        assert len(entries) == 1
        assert entries[0]["name"] == "scheduled-run"
        assert entries[0]["cron"] == "*/5 * * * *"


async def test_env_fallback_arms_when_config_empty(tmp_state_home: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(SCHEDULE_CRON_ENV, "0 6 * * *")
    cfg = CoreConfig(state_home=tmp_state_home)
    async with boot(_tree(cfg) + [make_scheduled_run_entry()]) as ctx:  # noqa: RUF005
        entries = ctx.scheduler.entries()
        assert entries == [{"name": "scheduled-run", "cron": "0 6 * * *", "running": "False"}]


@pytest.mark.parametrize(
    ("expression", "expected_gap"),
    [
        ("30 8,22 * * *", 14 * 3600),
        ("*/5 * * * *", 300),
        ("0 6 * * *", 24 * 3600),
        ("0 0 * * 1", 7 * 24 * 3600),
    ],
)
def test_expected_max_gap_seconds(expression: str, expected_gap: float):
    assert expected_max_gap_seconds(expression) == expected_gap


def test_retention_is_twice_gap_plus_grace_capped():
    assert kuma_push_retention_seconds("*/5 * * * *") == 2_400
    assert kuma_push_retention_seconds("30 8,22 * * *") == KUMA_PUSH_MAX_RETENTION


def test_build_kuma_push_url_bare_and_suffixed():
    bare = build_kuma_push_url("http://kuma:3001/api/push/KEY", success=True, message="run ok", retention=2400)
    assert bare == "http://kuma:3001/api/push/KEY?status=up&msg=run+ok&ping=2400"
    suffixed = build_kuma_push_url("http://kuma:3001/api/push/KEY?foo=1", success=False, message="boom", retention=60)
    assert suffixed.startswith("http://kuma:3001/api/push/KEY?foo=1&")
    assert "status=down" in suffixed and "msg=boom" in suffixed and "ping=60" in suffixed


def test_build_kuma_push_url_truncates_long_messages():
    url = build_kuma_push_url("http://k/push/K", success=True, message="x" * 900, retention=1)
    msg_value = url.split("msg=")[1].split("&")[0]
    assert msg_value == "x" * 500
