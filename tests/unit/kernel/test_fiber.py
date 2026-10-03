"""Fiber lifecycle: effects, epochs, reload cascades, update, disposal."""

from __future__ import annotations

import pytest

from progress.kernel import Entry, boot, root_context
from progress.kernel.errors import InactiveEffectError
from progress.kernel.fiber import Fiber, FiberState


async def test_effects_dispose_in_reverse_order():
    order: list[str] = []

    async def plugin(ctx, config):
        for i in range(4):
            ctx.effect(lambda i=i: order.append(f"close-{i}"))

    async with boot([Entry(id="p", plugin=plugin)]) as _ctx:
        pass
    assert order == ["close-3", "close-2", "close-1", "close-0"]


async def test_disposer_exception_is_isolated_and_siblings_still_run():
    order: list[str] = []

    def _boom():
        raise RuntimeError("boom")

    async def plugin(ctx, config):
        ctx.effect(lambda: order.append("close-a"))
        ctx.effect(_boom)
        ctx.effect(lambda: order.append("close-c"))

    async with boot([Entry(id="p", plugin=plugin)]) as _ctx:
        pass
    assert order == ["close-c", "close-a"]


async def test_fiber_stays_pending_until_injected_service_resolves():
    states: list[str] = []

    async def consumer(ctx, config):
        states.append("loaded")

    ctx = root_context()
    fiber = ctx.plugin({"name": "consumer", "apply": consumer, "inject": ["db"]}, name="consumer")
    await ctx.fiber.settle_tree()
    assert fiber.state == FiberState.PENDING
    assert states == []

    async def provider(ctx, config):
        ctx.provide("db", object())

    ctx.plugin(provider, name="provider")
    await ctx.fiber.settle_tree()
    assert fiber.state == FiberState.ACTIVE
    assert states == ["loaded"]
    await ctx.fiber.dispose()


async def test_provider_failure_fails_loud_at_boot():
    async def broken(ctx, config):
        raise RuntimeError("no good")

    with pytest.raises(Exception) as excinfo:
        async with boot([Entry(id="broken", plugin=broken)]):
            pass
    assert "broken" in str(excinfo.value)


async def test_missing_inject_reports_precise_service_name():
    async def consumer(ctx, config):
        raise AssertionError("must not load")

    with pytest.raises(Exception) as excinfo:
        async with boot([Entry(id="consumer", plugin=consumer, inject=["telemetry"])]):
            pass
    assert "telemetry" in str(excinfo.value)


async def test_provider_replacement_cascades_reload_to_consumers():
    loads: list[str] = []

    def make_provider(tag: str):
        async def provider(ctx, config):
            ctx.provide("db", {"tag": tag})

        provider.name = f"provider-{tag}"
        return provider

    async def consumer(ctx, config):
        db = ctx.db
        loads.append(db["tag"])

    ctx = root_context()
    consumer_fiber = ctx.plugin({"name": "consumer", "apply": consumer, "inject": ["db"]}, name="consumer")
    ctx.plugin(make_provider("one"), name="provider")
    await ctx.fiber.settle_tree()
    assert loads == ["one"]

    async def remove_db(ctx2, config):
        return None

    provider_fiber = next(f for f in ctx.fiber.walk() if f.runtime.name == "provider-one")
    await provider_fiber.dispose()
    await ctx.fiber.settle_tree()
    assert consumer_fiber.state == FiberState.PENDING

    ctx.plugin(make_provider("two"), name="provider2")
    await ctx.fiber.settle_tree()
    assert loads == ["one", "two"]
    assert consumer_fiber.state == FiberState.ACTIVE
    await ctx.fiber.dispose()


async def test_update_reloads_fiber_with_new_config():
    from pydantic import BaseModel  # noqa: PLC0415

    class Config(BaseModel):
        tag: str = "default"

    seen: list[str] = []

    async def plugin(ctx, config: Config):
        seen.append(config.tag)

    ctx = root_context()
    fiber = ctx.plugin(plugin, Config(tag="first"), name="p")
    await ctx.fiber.settle_tree()
    assert seen == ["first"]

    await fiber.update(Config(tag="second"))
    assert seen == ["first", "second"]
    assert fiber.state == FiberState.ACTIVE
    await ctx.fiber.dispose()


async def test_update_can_be_vetoed_via_internal_update_waterfall():
    seen: list[str] = []

    async def plugin(ctx, config):
        seen.append(config)

    ctx = root_context()

    def veto(fiber, config, next_):
        return "vetoed"

    ctx.on("internal/update", veto)
    fiber = ctx.plugin(plugin, "first", name="p")
    await ctx.fiber.settle_tree()
    await fiber.update("second")
    assert seen == ["first"]
    await ctx.fiber.dispose()


async def test_class_plugin_with_start():
    started: list[str] = []

    class Plugin:
        name = "classy"

        def __init__(self, ctx, config):
            self.ctx = ctx

        async def start(self):
            started.append("start")

        async def stop(self):
            started.append("stop")

    async with boot([Entry(id="c", plugin=Plugin)]) as _ctx:
        assert started == ["start"]
    assert started == ["start", "stop"]


async def test_effect_after_disposal_raises():
    async def plugin(ctx, config):
        ctx.provide("svc", 1)
        fiber_holder.append(ctx.fiber)

    fiber_holder: list[Fiber] = []
    async with boot([Entry(id="p", plugin=plugin)]) as _ctx:
        pass
    with pytest.raises(InactiveEffectError):
        fiber_holder[0].effect(lambda: lambda: None)


async def test_child_fiber_disposed_with_parent():
    child_ran: list[str] = []

    async def child(ctx, config):
        ctx.effect(lambda: child_ran.append("child-closed"))

    async def parent(ctx, config):
        ctx.plugin(child, name="child")

    async with boot([Entry(id="parent", plugin=parent)]) as _ctx:
        pass
    assert child_ran == ["child-closed"]


async def test_pydantic_config_validation_failure_fails_boot():
    from pydantic import BaseModel  # noqa: PLC0415

    from progress.kernel.errors import BootError  # noqa: PLC0415

    class Config(BaseModel):
        required_tag: str

    def plugin(ctx, config):
        raise AssertionError("unreachable")

    plugin.Config = Config

    with pytest.raises(BootError):
        async with boot([Entry(id="p", plugin=plugin, config={"wrong": 1})]) as _ctx:
            pass
