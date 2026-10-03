"""Context: attribute resolution, isolate scopes, intercept merge, Service base."""

from __future__ import annotations

import pickle
from typing import override

import pytest

from progress.kernel import Definition, Entry, Service, ServiceNotFound, boot, root_context


class DbDef(Definition):
    service_name = "db"


async def test_attribute_resolution_and_typed_get():
    async def provider(ctx, config):
        ctx.provide(DbDef, {"ok": True})

    async with boot([Entry(id="provider", plugin=provider)]) as ctx:
        assert ctx.db == {"ok": True}
        assert ctx.get(DbDef) == {"ok": True}
        assert ctx.get("db") == {"ok": True}
        assert ctx.has(DbDef)


async def test_service_not_found_is_attribute_error():
    ctx = root_context()
    with pytest.raises(ServiceNotFound) as excinfo:
        ctx.missing_thing  # noqa: B018
    assert isinstance(excinfo.value, AttributeError)
    assert ctx.get("missing_thing") is None
    assert not hasattr(ctx, "missing_thing")
    assert not hasattr(ctx, "_private_probe")
    pickle.dumps(ctx.isolate_chain)
    await ctx.fiber.dispose()


async def test_duplicate_provide_in_same_scope_fails_boot():
    async def provider(ctx, config):
        ctx.provide("db", 1)
        ctx.provide("db", 2)

    with pytest.raises(Exception) as excinfo:
        async with boot([Entry(id="p", plugin=provider)]) as _ctx:
            pass
    assert "already registered" in str(excinfo.value)


async def test_isolate_anonymous_label_shadows_root_service():
    async def provider(ctx, config):
        ctx.provide("db", "root-db")

    async def root_consumer(ctx, config):
        ctx.provide("seen-root", ctx.db)

    async def shadow_provider(ctx, config):
        ctx.provide("db", "shadow-db")

    shadow_provider.isolate = {"db": "shadow"}

    async def isolated_consumer(ctx, config):
        ctx.provide("seen-isolated", ctx.db)

    isolated_consumer.isolate = {"db": "shadow"}

    async with boot(
        [
            Entry(id="provider", plugin=provider),
            Entry(id="shadow-provider", plugin=shadow_provider),
            Entry(id="root-consumer", plugin=root_consumer, inject=["db"]),
            Entry(id="isolated-consumer", plugin=isolated_consumer, inject=["db"]),
        ]
    ) as ctx:
        assert ctx.get("seen-root") == "root-db"
        assert ctx.get("seen-isolated") == "shadow-db"
        assert ctx.db == "root-db"


async def test_isolate_same_label_joins_scopes_and_conflicts():
    async def left(ctx, config):
        scoped = ctx.isolate("db", "pair")
        scoped.provide("db", "from-left")
        ctx.provide("left-ran", True)

    async def right(ctx, config):
        scoped = ctx.isolate("db", "pair")
        scoped.provide("db", "from-right")
        ctx.provide("right-ran", True)

    with pytest.raises(Exception) as excinfo:
        async with boot([Entry(id="left", plugin=left), Entry(id="right", plugin=right)]) as _ctx:
            pass
    assert "already registered" in str(excinfo.value)


async def test_intercept_config_collected_root_first():
    ctx = root_context()
    outer = ctx.intercept("telemetry", {"level": "info", "extra": True})
    inner = outer.intercept("telemetry", {"level": "debug"})
    merged = inner.resolve_config("telemetry", base={"other": 1})
    assert merged == {"level": "debug", "extra": True, "other": 1}
    await ctx.fiber.dispose()


async def test_service_base_lifecycle():
    events: list[str] = []

    class FakeDb(Service):
        service_name = "fakeDb"

        @override
        async def start(self):
            events.append("start")

        @override
        async def stop(self):
            events.append("stop")

    async def provider(ctx, config):
        svc = FakeDb(ctx)
        await svc.start()
        ctx.provide(FakeDb, svc)
        ctx.effect(svc.stop)

    async with boot([Entry(id="p", plugin=provider)]) as ctx:
        assert events == ["start"]
        assert isinstance(ctx.get(FakeDb), FakeDb)
    assert events == ["start", "stop"]
