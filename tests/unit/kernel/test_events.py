"""Event bus: five dispatch modes, catalog validation, scope-free listeners."""

from __future__ import annotations

import asyncio

import pytest

from progress.kernel import declare_event, root_context
from progress.kernel.events import catalog


@pytest.fixture(autouse=True)
def _fresh_events():
    catalog.clear()
    declare_event("internal/status", mode="emit", replace=True)
    declare_event("internal/service", mode="emit", replace=True)
    declare_event("internal/update", mode="waterfall", replace=True)


async def test_emit_is_fire_and_forget_and_reports_errors():

    declare_event("x/emit", mode="emit")
    seen: list[int] = []
    errors: list[BaseException] = []

    from progress.kernel.events import set_background_error_handler  # noqa: PLC0415

    set_background_error_handler(lambda name, exc: errors.append(exc))
    ctx = root_context()

    async def good(v):
        seen.append(v)

    async def bad(v):
        raise RuntimeError("listener boom")

    ctx.on("x/emit", good)
    ctx.on("x/emit", bad)
    await ctx.emit("x/emit", 1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert seen == [1]
    assert len(errors) == 1
    set_background_error_handler(None)
    await ctx.fiber.dispose()


async def test_parallel_aggregates_failures_into_exception_group():
    declare_event("x/parallel", mode="parallel")
    ctx = root_context()

    async def ok():
        return "ok"

    async def boom():
        raise ValueError("nope")

    ctx.on("x/parallel", ok)
    ctx.on("x/parallel", boom)
    with pytest.raises(ExceptionGroup) as excinfo:
        await ctx.parallel("x/parallel")
    assert any(isinstance(e, ValueError) for e in excinfo.value.exceptions)
    await ctx.fiber.dispose()


async def test_serial_stops_at_first_bail_value():
    declare_event("x/serial", mode="serial")
    calls: list[str] = []
    ctx = root_context()

    async def first():
        calls.append("first")
        return "stop"

    async def second():
        calls.append("second")

    ctx.on("x/serial", first)
    ctx.on("x/serial", second)
    result = await ctx.serial("x/serial")
    assert result == "stop"
    assert calls == ["first"]
    await ctx.fiber.dispose()


async def test_bail_is_serial_veto_alias():
    declare_event("x/bail", mode="bail")
    calls: list[str] = []
    ctx = root_context()

    async def veto():
        calls.append("veto")
        return "vetoed"

    async def never():
        calls.append("never")

    ctx.on("x/bail", veto)
    ctx.on("x/bail", never)
    result = await ctx.bail("x/bail")
    assert result == "vetoed"
    assert calls == ["veto"]
    await ctx.fiber.dispose()


async def test_waterfall_runs_outermost_first_and_veto_stops_chain():
    declare_event("x/waterfall", mode="waterfall")
    calls: list[str] = []
    ctx = root_context()

    async def outer(payload, next_):
        calls.append("outer")
        return await next_()

    async def middle(payload, next_):
        calls.append("middle")
        return "from-middle"

    async def inner_default(payload):
        calls.append("default")

    ctx.on("x/waterfall", outer)
    ctx.on("x/waterfall", middle)
    result = await ctx.waterfall("x/waterfall", "p")
    assert calls == ["outer", "middle"]
    assert result == "from-middle"

    calls.clear()

    async def veto(payload, next_):
        calls.append("veto")
        return "vetoed"

    ctx.on("x/waterfall", veto, prepend=True)
    result = await ctx.waterfall("x/waterfall", "p")
    assert calls == ["veto"]
    assert result == "vetoed"
    await ctx.fiber.dispose()


async def test_dispatch_validates_catalog_and_fails_loud():
    ctx = root_context()
    with pytest.raises(KeyError):
        await ctx.emit("undeclared/event")
    declare_event("x/waterfall2", mode="waterfall")
    with pytest.raises(TypeError):
        await ctx.serial("x/waterfall2")
    await ctx.fiber.dispose()


async def test_duplicate_declaration_rejected_without_replace():
    declare_event("x/dup", mode="emit")
    with pytest.raises(ValueError):
        declare_event("x/dup", mode="emit")
    declare_event("x/dup", mode="emit", replace=True)


async def test_once_listener_fires_single_time():
    declare_event("x/once", mode="emit")
    hits: list[int] = []
    ctx = root_context()
    ctx.once("x/once", lambda: hits.append(1))
    await ctx.emit("x/once")
    await asyncio.sleep(0)
    await ctx.emit("x/once")
    await asyncio.sleep(0)
    assert hits == [1]
    await ctx.fiber.dispose()


async def test_listener_disposed_with_fiber():
    declare_event("x/scope", mode="emit")
    hits: list[int] = []
    ctx = root_context()

    async def listener():
        hits.append(1)

    async def plugin(pctx, config):
        pctx.on("x/scope", listener)

    fiber = ctx.plugin(plugin, name="p")
    await ctx.fiber.settle_tree()
    await ctx.emit("x/scope")
    await asyncio.sleep(0)
    assert hits == [1]
    await fiber.dispose()
    await ctx.emit("x/scope")
    await asyncio.sleep(0)
    assert hits == [1]
    await ctx.fiber.dispose()
