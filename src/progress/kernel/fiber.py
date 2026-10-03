"""Fiber: one plugin runtime instance and its lifecycle.

States: ``PENDING → LOADING → ACTIVE → UNLOADING → DISPOSED`` with ``FAILED``
as the apply-error terminal. A fiber stays PENDING until every injected
service resolves; it reloads when a dependency's *implementation* changes.

The epoch is a fingerprint of provider fiber uids over the inject list; the
sentinel :data:`INACTIVE` marks unresolved. Because the fingerprint contains
provider identities, replacing a provider (not just removing it) forces
consumers to unload and reload against the new instance — cordis's epoch
design, ported verbatim.

All settlement flows through :meth:`Fiber.settle_tree` on the root fiber,
guarded by a tree lock; runtime mutations outside a pass call
:meth:`Fiber.kick` to schedule exactly one re-pass. The fixed-point loop
needs no event bookkeeping: a provider flipping state changes dependents'
computed epochs, which the loop's ``changed`` flag picks up on the next
sweep.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import enum
import inspect
import itertools
import logging
from typing import Any

from pydantic import BaseModel

from progress.kernel import events as event_bus
from progress.kernel.errors import FiberError, InactiveEffectError, ValidationError
from progress.kernel.utils import DisposableList, maybe_await, run_disposer

logger = logging.getLogger("progress.kernel.fiber")

INACTIVE = "__inactive__"
MAX_PASSES = 200

event_bus.declare_event("internal/status", mode="emit", replace=True)
event_bus.declare_event("internal/service", mode="emit", replace=True)
event_bus.declare_event("internal/update", mode="waterfall", replace=True)


class FiberState(str, enum.Enum):  # noqa: UP042
    PENDING = "pending"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"
    UNLOADING = "unloading"
    DISPOSED = "disposed"


_uid_counter = itertools.count(1)


@dataclass
class PluginRuntime:
    """Normalized plugin declaration shared by every fiber of that plugin."""

    name: str
    callback: Callable[..., Any]
    config_type: type[BaseModel] | None = None
    inject: list[str] = field(default_factory=list)
    inject_config: dict[str, Any] = field(default_factory=dict)
    provide: list[str] = field(default_factory=list)
    isolate: dict[str, str | bool] = field(default_factory=dict)
    source: Any = None


class Fiber:
    """A mounted plugin instance."""

    def __init__(self, parent: Any, runtime: PluginRuntime, config: Any = None) -> None:
        self.uid = next(_uid_counter)
        self.runtime = runtime
        self.raw_config = config
        self.config: Any = None
        self.parent = parent
        self.ctx: Any = parent.extend(fiber=self, isolate=runtime.isolate) if parent is not None else None
        self.state = FiberState.PENDING
        self.error: BaseException | None = None
        self.epoch = INACTIVE
        self.name = f"{runtime.name}#{self.uid}"
        self._disposables = DisposableList()
        self._children: list[Fiber] = []
        self._waiters: list[asyncio.Future[None]] = []
        self._instance: Any = None
        self._tree_lock: asyncio.Lock | None = None
        self._kick_scheduled = False

    @classmethod
    def create_root(cls, ctx: Any, runtime: PluginRuntime) -> Fiber:
        fiber = cls(None, runtime)
        fiber.uid = 0
        fiber.name = "root"
        fiber.state = FiberState.ACTIVE
        fiber.epoch = ""
        fiber.ctx = ctx
        return fiber

    @property
    def root(self) -> Fiber:
        node = self
        while node.parent is not None:
            node = node.parent.fiber
        return node

    def walk(self) -> list[Fiber]:
        ordered = [self]
        for child in self._children:
            ordered.extend(child.walk())
        return ordered

    def missing_injects(self) -> list[str]:
        return [name for name in self.runtime.inject if self.ctx.reflect.resolve(self.ctx.isolate_chain, name) is None]

    def diagnostics(self) -> str:
        injects = ", ".join(self.runtime.inject) or "(none)"
        if self.state == FiberState.FAILED and self.error is not None:
            return f"{self.name}: failed: {self.error!r}"
        if self.state == FiberState.PENDING:
            missing = ", ".join(self.missing_injects()) or "(none)"
            return f"{self.name}: pending (injects [{injects}], missing [{missing}])"
        return f"{self.name}: {self.state.value}"

    def effect(self, disposer: Callable[[], Any], *, label: str | None = None) -> Callable[[], Any]:
        """Register a disposer (sync or async callable) on this fiber.

        Python adaptation of cordis's ``effect(() => disposer)`` body form:
        the callable is registered as the disposer directly, not executed now
        — the double-lambda body form is a footgun Python does not need. The
        returned handle is an async undo that deregisters and runs it.
        """
        if self.state in (FiberState.DISPOSED, FiberState.UNLOADING):
            raise InactiveEffectError(f"fiber {self.name} no longer accepts effects")
        if not callable(disposer):
            raise TypeError(f"effect on {self.name} registered a non-callable disposer")
        self._disposables.push(disposer)

        async def _undo() -> None:
            self._disposables.remove(disposer)
            await run_disposer(disposer)

        return _undo

    def register_disposer(self, disposer: Callable[[], Any]) -> Callable[[], None]:
        if self.state in (FiberState.DISPOSED, FiberState.UNLOADING):
            raise InactiveEffectError(f"fiber {self.name} no longer accepts effects")

        def _deregister() -> None:
            self._disposables.remove(disposer)

        self._disposables.push(disposer)
        return _deregister

    async def await_ready(self) -> None:
        await self._wait_terminal()
        if self.state == FiberState.FAILED:
            raise FiberError(self.name, self.error or RuntimeError("unknown failure"))

    def __await__(self):
        return self.await_ready().__await__()

    async def _wait_terminal(self) -> None:
        if self.state in (FiberState.ACTIVE, FiberState.FAILED, FiberState.DISPOSED):
            return
        waiter = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        await waiter

    def _notify_waiters(self) -> None:
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    def _set_state(self, state: FiberState) -> None:
        old, self.state = self.state, state
        if state not in (old, FiberState.PENDING):
            self._fire_internal_status(old)

    def _fire_internal_status(self, old: FiberState) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_safe_emit(self.ctx.events, "internal/status", self, old))  # noqa: RUF006

    def _compute_epoch(self) -> str:
        reflect = self.ctx.reflect
        parts: list[str] = []
        for name in self.runtime.inject:
            impl = reflect.resolve(self.ctx.isolate_chain, name)
            if impl is None:
                return INACTIVE
            parts.append(f"{name}:{impl.fiber.uid}")
        return "|".join(parts)

    async def _load(self, epoch: str) -> None:
        self._set_state(FiberState.LOADING)
        try:
            self.config = _validate_config(self.runtime, self.raw_config)
            callback = self.runtime.callback
            if inspect.isclass(callback):
                self._instance = callback(self.ctx, self.config)
                start = getattr(self._instance, "start", None)
                if start is not None:
                    await maybe_await(start())
                stop = getattr(self._instance, "stop", None)
                if stop is not None:
                    self._disposables.push(stop)
            else:
                await maybe_await(callback(self.ctx, self.config))
        except Exception as exc:
            self.error = exc
            self.epoch = epoch
            self._set_state(FiberState.FAILED)
            logger.error("fiber %s failed to load: %r", self.name, exc)
            return
        self.error = None
        self.epoch = epoch
        self._set_state(FiberState.ACTIVE)

    async def _unload(self) -> None:
        self._set_state(FiberState.UNLOADING)
        for disposer in self._disposables.reversed_items():
            try:
                await run_disposer(disposer)
            except Exception:
                logger.exception("disposer failed on fiber %s", self.name)
        self._disposables = DisposableList()
        children, self._children = self._children, []
        for child in children:
            try:
                await child.dispose()
            except Exception:
                logger.exception("child dispose failed on fiber %s", child.name)
        self._instance = None
        self._set_state(FiberState.PENDING)
        self._notify_waiters()

    async def _pass(self) -> bool:
        if self.state == FiberState.DISPOSED:
            return False
        before = (self.state, self.epoch)
        epoch = self._compute_epoch()
        if self.state == FiberState.PENDING:
            if epoch != INACTIVE:
                await self._load(epoch)
            else:
                self.epoch = INACTIVE
        elif self.state == FiberState.ACTIVE and epoch != self.epoch:
            await self._unload()
            if self._compute_epoch() != INACTIVE:
                await self._load(self._compute_epoch())
        return (self.state, self.epoch) != before

    async def update(self, config: Any) -> bool:
        """Vetoable config update; the default action restarts in place."""
        callbacks = list(self.ctx.events.listeners("internal/update"))

        async def _default() -> Any:
            self.raw_config = config
            self.epoch = INACTIVE
            async with self.root.tree_lock():
                await self._pass()
            return True

        async def _next() -> Any:
            if callbacks:
                callback = callbacks.pop(0)
                return await maybe_await(callback(self, config, _next))
            return await _default()

        await _next()
        await self.settle_tree()
        return self.state != FiberState.FAILED

    async def dispose(self) -> None:
        if self.state == FiberState.DISPOSED:
            return
        if self.state != FiberState.PENDING or len(self._disposables) or self._children:
            await self._unload()
        self._set_state(FiberState.DISPOSED)
        self._notify_waiters()

    def tree_lock(self) -> asyncio.Lock:
        if self._tree_lock is None:
            self._tree_lock = asyncio.Lock()
        return self._tree_lock

    async def settle_tree(self) -> None:
        root = self.root
        async with root.tree_lock():
            for _ in range(MAX_PASSES):
                changed = False
                for fiber in root.walk():
                    if await fiber._pass():  # noqa: SLF001
                        changed = True
                if not changed:
                    return
            raise RuntimeError("kernel settlement did not converge")

    def kick(self) -> None:
        """Schedule one settlement pass for the whole tree (runtime mutation)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        root = self.root
        if root._kick_scheduled:  # noqa: SLF001
            return
        root._kick_scheduled = True  # noqa: SLF001

        async def _run() -> None:
            try:
                await root.settle_tree()
            finally:
                root._kick_scheduled = False  # noqa: SLF001

        loop.create_task(_run())  # noqa: RUF006

    def mount_child(self, fiber: Fiber) -> None:
        self._children.append(fiber)

        async def _dispose_child() -> None:
            await fiber.dispose()

        self.register_disposer(_dispose_child)


def _validate_config(runtime: PluginRuntime, raw: Any) -> Any:
    config_type = runtime.config_type
    if config_type is None:
        return raw
    if raw is None:
        return config_type()
    if isinstance(raw, config_type):
        return raw
    try:
        return config_type.model_validate(raw)
    except Exception as exc:
        raise ValidationError(f"config for plugin {runtime.name!r} failed validation: {exc}") from exc


async def _safe_emit(events: Any, name: str, *args: Any) -> None:
    try:
        await events.emit(name, *args)
    except Exception:
        logger.exception("internal event %s failed", name)


__all__ = ["INACTIVE", "Fiber", "FiberState", "PluginRuntime"]
