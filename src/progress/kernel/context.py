"""Context: the service registry every plugin receives.

Attribute access resolves services through ``__getattr__``; underscore names
raise :class:`AttributeError` immediately so ``copy``/``pickle``/``hasattr``
probing never triggers resolution, and :class:`ServiceNotFound` subclasses
:class:`AttributeError` so the attribute worldview and the domain worldview
agree. Service lookup is a plain store read — no per-access event dispatch.

``isolate(name, label)`` derives a child context binding a service name to a
scope label (the same string label joins scopes, an anonymous label shadows);
``intercept(name, config)`` derives a child context contributing a config
fragment resolved root-first by the service itself.
"""

from __future__ import annotations

from collections import ChainMap
from collections.abc import Callable
from typing import Any

from progress.kernel.errors import ServiceNotFound
from progress.kernel.fiber import Fiber, PluginRuntime
from progress.kernel.reflect import ReflectService, fresh_label
from progress.kernel.service import Definition, service_name_of
from progress.kernel.utils import qual_name


def _plugin_callback(plugin: Any) -> Callable[..., Any]:
    if isinstance(plugin, dict):
        return plugin["apply"]
    return getattr(plugin, "apply", None) or plugin


def _normalize_plugin(plugin: Any, *, name: str | None = None) -> PluginRuntime:
    if isinstance(plugin, dict):
        callback = plugin["apply"]
        name = plugin.get("name") or name
        inject_decl = plugin.get("inject", [])
        config_type = plugin.get("Config")
        provide_decl = plugin.get("provide", [])
        isolate_decl = plugin.get("isolate", {})
    else:
        callback = getattr(plugin, "apply", None) or plugin
        name = getattr(plugin, "name", None) or name
        inject_decl = getattr(plugin, "inject", [])
        config_type = getattr(plugin, "Config", None)
        provide_decl = getattr(plugin, "provide", [])
        isolate_decl = getattr(plugin, "isolate", {})

    isolate_scopes: dict[str, str | bool] = dict(isolate_decl) if isinstance(isolate_decl, dict) else {}

    inject: list[str]
    inject_config: dict[str, Any] = {}
    if isinstance(inject_decl, dict):
        inject = [str(key) for key in inject_decl]
        inject_config = dict(inject_decl)
    elif inject_decl is None:
        inject = []
    else:
        inject = list(inject_decl)

    if provide_decl is None:
        provide = []
    elif isinstance(provide_decl, str):
        provide = [provide_decl]
    else:
        provide = list(provide_decl)

    if name is None:
        name = qual_name(callback)
    return PluginRuntime(
        name=str(name),
        callback=callback,
        config_type=config_type,
        inject=inject,
        inject_config=inject_config,
        provide=provide,
        isolate=isolate_scopes,
        source=plugin,
    )


class RegistryService:
    """Plugin runtime table keyed by callback identity (L2 replacement)."""

    def __init__(self) -> None:
        self.runtimes: dict[int, PluginRuntime] = {}
        self._root_ctx: Context | None = None

    def bind_root(self, ctx: Context) -> None:
        self._root_ctx = ctx

    def get_or_create(self, plugin: Any, *, name: str | None = None) -> PluginRuntime:
        callback = _plugin_callback(plugin)
        runtime = self.runtimes.get(id(callback))
        if runtime is None:
            runtime = _normalize_plugin(plugin, name=name)
            self.runtimes[id(callback)] = runtime
        return runtime

    def delete(self, plugin: Any) -> PluginRuntime | None:
        return self.runtimes.pop(id(_plugin_callback(plugin)), None)

    def fibers_of(self, runtime: PluginRuntime) -> list[Fiber]:
        if self._root_ctx is None:
            return []
        return [f for f in self._root_ctx.root_fiber.walk() if f.runtime is runtime]


class RootServices:
    """Shared plumbing owned by the root context of one kernel tree."""

    def __init__(self) -> None:
        from progress.kernel.events import EventsService  # noqa: PLC0415

        self.events: EventsService = EventsService()
        self.reflect = ReflectService()
        self.registry = RegistryService()
        self.root_fiber: Fiber | None = None
        self.root_ctx: Context | None = None


class Context:
    """Per-fiber handle onto the shared kernel services."""

    def __init__(
        self,
        *,
        fiber: Fiber | None,
        root: RootServices,
        isolate_chain: ChainMap[str, str],
        intercept_chain: ChainMap[str, dict[str, Any]],
    ) -> None:
        self.fiber = fiber
        self._root = root
        self.isolate_chain = isolate_chain
        self.intercept_chain = intercept_chain

    @property
    def events(self) -> Any:
        return self._root.events

    @property
    def reflect(self) -> ReflectService:
        return self._root.reflect

    @property
    def registry(self) -> RegistryService:
        return self._root.registry

    @property
    def root_fiber(self) -> Fiber:
        fiber = self._root.root_fiber
        if fiber is None:
            raise RuntimeError("root fiber not created yet")
        return fiber

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        impl = self._root.reflect.resolve(self.isolate_chain, name)
        if impl is not None:
            return impl.value
        raise ServiceNotFound(name, detail=_resolution_detail(self, name))

    def get(self, ref: str | type) -> Any:
        """Typed or literal service access; ``None`` when absent."""
        name = ref if isinstance(ref, str) else service_name_of(ref)
        impl = self._root.reflect.resolve(self.isolate_chain, name)
        return impl.value if impl is not None else None

    def has(self, ref: str | type) -> bool:
        name = ref if isinstance(ref, str) else service_name_of(ref)
        return self._root.reflect.resolve(self.isolate_chain, name) is not None

    def provide(self, ref: str | type, value: Any) -> Callable[[], Any]:
        """Register a service as an effect of the current fiber.

        The returned handle is an async undo: it deregisters and notifies the
        tree to re-settle.
        """
        service = ref if isinstance(ref, str) else service_name_of(ref)
        fiber = self.fiber or self.root_fiber

        self._root.reflect.define(fiber, self.isolate_chain, service, value)

        def _dispose() -> None:
            self._root.reflect.undefine(self.isolate_chain, service)
            fiber.kick()

        undo = fiber.effect(_dispose)
        fiber.kick()
        return undo

    def effect(self, body: Callable[[], Any], *, label: str | None = None) -> Callable[[], Any]:
        fiber = self.fiber or self.root_fiber
        return fiber.effect(body, label=label)

    def on(self, name: str, listener: Callable[..., Any], *, prepend: bool = False) -> Callable[[], None]:
        dispose = self.events.on(name, listener, prepend=prepend)
        return self.effect(dispose)

    def once(self, name: str, listener: Callable[..., Any]) -> Callable[[], None]:
        def _wrap(*args: Any) -> Any:
            remove()
            return listener(*args)

        remove = self.events.on(name, _wrap)
        return self.effect(remove)

    async def emit(self, name: str, *args: Any) -> None:
        await self.events.emit(name, *args)

    async def parallel(self, name: str, *args: Any) -> list[Any]:
        return await self.events.parallel(name, *args)

    async def serial(self, name: str, *args: Any) -> Any:
        return await self.events.serial(name, *args)

    async def bail(self, name: str, *args: Any) -> Any:
        return await self.events.bail(name, *args)

    async def waterfall(self, name: str, *args: Any) -> Any:
        return await self.events.waterfall(name, *args)

    def waterfall_default(self, name: str, *args: Any, default: Any = None) -> Any:
        return self.events.waterfall_default(name, *args, default=default)

    def plugin(self, plugin: Any, config: Any = None, *, name: str | None = None) -> Fiber:
        runtime = self.registry.get_or_create(plugin, name=name)
        parent_fiber = self.fiber or self.root_fiber
        fiber = Fiber(parent_fiber.ctx, runtime, config)
        parent_fiber.mount_child(fiber)
        parent_fiber.kick()
        return fiber

    def inject(
        self, deps: list[str] | dict[str, Any], callback: Callable[..., Any], *, name: str | None = None
    ) -> Fiber:
        plugin: dict[str, Any] = {"apply": callback, "inject": deps}
        if name is not None:
            plugin["name"] = name
        return self.plugin(plugin)

    def isolate(self, name: str, label: str | None = None) -> Context:
        return Context(
            fiber=self.fiber,
            root=self._root,
            isolate_chain=ChainMap({name: label or fresh_label()}, self.isolate_chain),
            intercept_chain=ChainMap({}, self.intercept_chain),
        )

    def intercept(self, name: str, config: dict[str, Any]) -> Context:
        return Context(
            fiber=self.fiber,
            root=self._root,
            isolate_chain=ChainMap({}, self.isolate_chain),
            intercept_chain=ChainMap({name: dict(config)}, self.intercept_chain),
        )

    def resolve_config(self, name: str, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge intercept fragments root-first over ``base`` (weakest layer)."""
        merged: dict[str, Any] = dict(base) if base else {}
        for layer in reversed(self.intercept_chain.maps):
            fragment = layer.get(name)
            if isinstance(fragment, dict):
                merged.update(fragment)
        return merged

    def extend(self, *, fiber: Fiber | None = None, isolate: dict[str, str | bool] | None = None) -> Context:
        isolate_chain: ChainMap[str, str] = self.isolate_chain
        if isolate:
            updates = {k: (v if isinstance(v, str) else fresh_label()) for k, v in isolate.items()}
            isolate_chain = ChainMap(updates, self.isolate_chain)
        return Context(
            fiber=fiber or self.fiber,
            root=self._root,
            isolate_chain=ChainMap({}, isolate_chain),
            intercept_chain=ChainMap({}, self.intercept_chain),
        )


def _resolution_detail(ctx: Context, name: str) -> str:
    impl = ctx._root.reflect.peek(ctx.isolate_chain, name)  # noqa: SLF001
    if impl is not None:
        return f"provider fiber {impl.fiber.name} is {impl.fiber.state.value}"
    return "no provider registered in this scope"


def _root_apply(ctx: Context, config: Any) -> None:
    return None


def root_context() -> Context:
    """Create a fresh kernel tree and return its root context."""
    services = RootServices()
    ctx = Context(
        fiber=None,
        root=services,
        isolate_chain=ChainMap({}),
        intercept_chain=ChainMap({}),
    )
    root_fiber = Fiber.create_root(ctx, PluginRuntime(name="root", callback=_root_apply))
    ctx.fiber = root_fiber
    services.root_fiber = root_fiber
    services.root_ctx = ctx
    services.registry.bind_root(ctx)
    return ctx


__all__ = ["Context", "Definition", "RegistryService", "RootServices", "root_context"]
