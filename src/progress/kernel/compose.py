"""Composition helpers: entries as data, boot, fail-loud activation audit.

Phase one composes in code — an ordered list of :class:`Entry` rows. Entry
ids are stable contract (phase-four patch layers target them by id), which
is why ids are assigned here rather than at serialization time.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from progress.kernel.context import Context, root_context
from progress.kernel.errors import BootError
from progress.kernel.fiber import Fiber, FiberState


@dataclass
class Entry:
    """One composition row: an id, a plugin, its config, extra injects."""

    id: str
    plugin: Any
    config: Any = None
    inject: list[str] = field(default_factory=list)
    disabled: bool = False


def mount(ctx: Context, entries: Iterable[Entry]) -> list[Fiber]:
    """Mount every enabled entry under the context's fiber."""
    fibers: list[Fiber] = []
    for entry in entries:
        if entry.disabled:
            continue
        plugin = entry.plugin
        if entry.inject:
            plugin = _with_extra_inject(plugin, entry.inject)
        fibers.append(ctx.plugin(plugin, entry.config, name=entry.id))
    return fibers


def _with_extra_inject(plugin: Any, extra: list[str]) -> dict[str, Any]:
    """Dict-plugin form carrying the merged declarations (normalized, ty-safe)."""
    if isinstance(plugin, dict):
        merged = dict(plugin)
    else:
        merged = {
            "apply": getattr(plugin, "apply", None) or plugin,
            "name": getattr(plugin, "name", None),
            "Config": getattr(plugin, "Config", None),
            "provide": getattr(plugin, "provide", None),
            "isolate": getattr(plugin, "isolate", None),
            "inject": list(getattr(plugin, "inject", []) or []),
        }
    base: list[str] = list(merged.get("inject") or [])
    merged["inject"] = list(dict.fromkeys([*base, *extra]))
    return merged


@asynccontextmanager
async def boot(entries: Iterable[Entry], *, name: str = "tree") -> AsyncIterator[Context]:
    """Mount a composition, drive it to a fixed point, fail loud, yield, unwind.

    Every fiber must reach ACTIVE; a FAILED or eternally PENDING fiber raises
    :class:`BootError` carrying per-fiber diagnostics (state and precise
    missing service names). Exit disposes the tree strictly LIFO.
    """
    ctx = root_context()
    try:
        fibers = mount(ctx, entries)
        await ctx.root_fiber.settle_tree()
        _assert_activated(fibers, name)
        try:
            yield ctx
        finally:
            await ctx.root_fiber.dispose()
    except BaseException:
        await ctx.root_fiber.dispose()
        raise


def _assert_activated(fibers: list[Fiber], name: str) -> None:
    diagnostics = [f.diagnostics() for f in fibers if f.state != FiberState.ACTIVE]
    if diagnostics:
        raise BootError(diagnostics)


__all__ = ["Entry", "boot", "mount"]
