"""Event bus with five dispatch modes as public contract.

Modes (cordis semantics, ported):

- ``emit`` — fire-and-forget; listeners are scheduled, results ignored,
  exceptions reported through ``background_error_handler``.
- ``parallel`` — all listeners awaited concurrently; failures aggregate into
  one :class:`ExceptionGroup`.
- ``serial`` — in order, stopping at the first bail value.
- ``bail`` — veto alias of ``serial`` (identical in an all-async runtime; the
  name is preserved as contract vocabulary).
- ``waterfall`` — the last argument is ``next``; listeners run outermost first;
  a listener that never calls ``next`` vetoes the remainder including the
  kernel default.

A process-wide :data:`catalog` of :class:`EventSpec` entries declares the mode
per event name; dispatch validates against it and fails loud on undeclared
events or mode mismatches. This registry replaces cordis's TypeScript
declaration merging (which has no Python equivalent) — the mode-as-contract
guarantee the reference enforces with a compile-time catalog gate moves into
the kernel itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from progress.kernel.utils import is_bailed, maybe_await

logger = logging.getLogger("progress.kernel.events")

DISPATCH_MODES = ("emit", "parallel", "serial", "bail", "waterfall")
DispatchMode = str

BackgroundErrorHandler = Callable[[str, BaseException], None]

_background_error_handler: BackgroundErrorHandler | None = None


def set_background_error_handler(handler: BackgroundErrorHandler | None) -> None:
    """Route emit-mode listener failures somewhere visible (observability)."""
    global _background_error_handler
    _background_error_handler = handler


def _report_background_error(event: str, exc: BaseException) -> None:
    if _background_error_handler is not None:
        try:
            _background_error_handler(event, exc)
        except Exception:
            logger.exception("background error handler failed for event %s", event)
    else:
        logger.exception("emit listener failed for event %s", event)  # noqa: LOG004


@dataclass(frozen=True)
class EventSpec:
    name: str
    mode: DispatchMode

    def __post_init__(self) -> None:
        if self.mode not in DISPATCH_MODES:
            raise ValueError(f"event {self.name!r} declares unknown mode {self.mode!r}")


catalog: dict[str, EventSpec] = {}


def declare_event(name: str, *, mode: DispatchMode, replace: bool = False) -> EventSpec:
    spec = EventSpec(name=name, mode=mode)
    if name in catalog and not replace:
        raise ValueError(f"event {name!r} is already declared")
    catalog[name] = spec
    return spec


def _spec(name: str, mode: DispatchMode) -> EventSpec:
    spec = catalog.get(name)
    if spec is None:
        raise KeyError(
            f"event {name!r} is not declared in the catalog; declare it with declare_event() before dispatch"
        )
    aliases = {("serial", "bail"), ("bail", "serial")}
    if spec.mode != mode and (spec.mode, mode) not in aliases:
        raise TypeError(f"event {name!r} is declared {spec.mode!r} but dispatched as {mode!r}")
    return spec


Listener = Callable[..., Any]


class EventsService:
    """Listener registry plus the five dispatch modes."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    def on(self, name: str, listener: Listener, *, prepend: bool = False) -> Callable[[], None]:
        bucket = self._listeners.setdefault(name, [])
        if prepend:
            bucket.insert(0, listener)
        else:
            bucket.append(listener)

        def _dispose() -> None:
            try:  # noqa: SIM105
                bucket.remove(listener)
            except ValueError:
                pass

        return _dispose

    def listeners(self, name: str) -> list[Listener]:
        return list(self._listeners.get(name, ()))

    async def emit(self, name: str, *args: Any) -> None:
        _spec(name, "emit")
        for listener in self.listeners(name):
            task = asyncio.ensure_future(_invoke(listener, args))
            self._background_tasks.add(task)

            def _done(t: asyncio.Task[None], *, _name: str = name) -> None:
                self._background_tasks.discard(t)
                exc = None if t.cancelled() else t.exception()
                if exc is not None:
                    _report_background_error(_name, exc)

            task.add_done_callback(_done)

    async def parallel(self, name: str, *args: Any) -> list[Any]:
        _spec(name, "parallel")
        listeners = self.listeners(name)
        if not listeners:
            return []
        results = await asyncio.gather(*(_invoke(listener, args) for listener in listeners), return_exceptions=True)
        failures: list[Exception] = [r for r in results if isinstance(r, Exception)]
        if failures:
            raise ExceptionGroup(f"parallel dispatch of {name!r} failed", failures)
        return results

    async def serial(self, name: str, *args: Any) -> Any:
        _spec(name, "serial")
        for listener in self.listeners(name):
            result = await maybe_await(listener(*args))
            if is_bailed(result):
                return result
        return None

    async def bail(self, name: str, *args: Any) -> Any:
        return await self.serial(name, *args)

    async def waterfall(self, name: str, *args: Any) -> Any:
        return await self.waterfall_default(name, *args, default=_null_default)

    async def waterfall_default(self, name: str, *args: Any, default: Any = None) -> Any:
        """Waterfall with an explicit core action; listeners always wrap it.

        A listener that never calls ``next`` vetoes the rest of the chain
        including the core action — the veto semantics.
        """
        _spec(name, "waterfall")
        callbacks = self.listeners(name)
        if default is None:
            default = _null_default

        async def _next() -> Any:
            if callbacks:
                callback = callbacks.pop(0)
                return await maybe_await(callback(*args, _next))
            return await maybe_await(default())

        return await _next()

    async def dispatch(self, mode: DispatchMode, name: str, *args: Any) -> Any:
        if mode == "emit":
            await self.emit(name, *args)
            return None
        if mode == "parallel":
            return await self.parallel(name, *args)
        if mode in ("serial", "bail"):
            return await self.serial(name, *args)
        if mode == "waterfall":
            return await self.waterfall(name, *args)
        raise TypeError(f"unknown dispatch mode {mode!r}")


async def _invoke(listener: Listener, args: tuple[Any, ...]) -> None:
    await maybe_await(listener(*args))


async def _null_default() -> Any:
    return None


__all__ = [
    "DISPATCH_MODES",
    "BackgroundErrorHandler",
    "EventSpec",
    "EventsService",
    "catalog",
    "declare_event",
    "set_background_error_handler",
]
