"""Compose: entries as data, boot audit, reload-during-unload stress."""

from __future__ import annotations

import asyncio

import pytest

from progress.kernel import Entry, FiberState, boot


async def test_disabled_entry_is_skipped():
    ran: list[str] = []

    async def plugin(ctx, config):
        ran.append("yes")

    async with boot([Entry(id="on", plugin=plugin), Entry(id="off", plugin=plugin, disabled=True)]) as _ctx:
        pass
    assert ran == ["yes"]


async def test_runtime_mount_and_unmount_without_restart():
    from progress.kernel import root_context  # noqa: PLC0415

    async def provider(ctx, config):
        ctx.provide("dyn", config)

    async def consumer(ctx, config):
        ctx.provide("seen", ctx.dyn)

    ctx = root_context()
    consumer_fiber = ctx.plugin({"name": "consumer", "apply": consumer, "inject": ["dyn"]}, name="consumer")
    provider_fiber = ctx.plugin(provider, "v1", name="provider")
    await ctx.fiber.settle_tree()
    assert ctx.get("seen") == "v1"

    await provider_fiber.dispose()
    await ctx.fiber.settle_tree()
    assert consumer_fiber.state == FiberState.PENDING
    provider_fiber2 = ctx.plugin(provider, "v2", name="provider")  # noqa: F841
    await ctx.fiber.settle_tree()
    assert ctx.get("seen") == "v2"
    assert consumer_fiber.state == FiberState.ACTIVE
    await ctx.fiber.dispose()


async def test_reload_during_unload_stress():
    """Provider replaced while consumers are mid-unload stays consistent."""
    from progress.kernel import root_context  # noqa: PLC0415

    iterations = 20
    loads: list[str] = []

    def make_provider(tag: str):
        async def provider(ctx, config):
            ctx.provide("stress", tag)
            await asyncio.sleep(0)

        provider.name = f"stress-{tag}"
        return provider

    async def consumer(ctx, config):
        loads.append(ctx.stress)
        await asyncio.sleep(0)

    ctx = root_context()
    consumer_fiber = ctx.plugin({"name": "consumer", "apply": consumer, "inject": ["stress"]}, name="consumer")
    previous = None
    for i in range(iterations):
        if previous is not None:
            await previous.dispose()
            await ctx.fiber.settle_tree()
            assert consumer_fiber.state == FiberState.PENDING
        previous = ctx.plugin(make_provider(f"p{i}"), name=f"provider-{i}")
        await ctx.fiber.settle_tree()
    await ctx.fiber.settle_tree()
    assert consumer_fiber.state == FiberState.ACTIVE
    assert ctx.stress == f"p{iterations - 1}"
    assert len(loads) == iterations
    await ctx.fiber.dispose()


async def test_boot_error_carries_missing_service_name():
    async def consumer(ctx, config):
        raise AssertionError("must not load")

    with pytest.raises(Exception) as excinfo:
        async with boot([Entry(id="c", plugin=consumer, inject=["definitely-missing"])]):
            pass
    assert "definitely-missing" in str(excinfo.value)
