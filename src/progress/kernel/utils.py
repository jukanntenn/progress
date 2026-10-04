"""Kernel primitives: disposable registry, awaitable helpers, shared symbols.

The only module the rest of the kernel imports for plumbing; it must stay
dependency-free beyond the standard library.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import inspect
from typing import Any

Disposable = Callable[[], "Awaitable[None] | None"]


class DisposableList:
    """Insertion-ordered registry with O(1) removal and strict LIFO disposal."""

    __slots__ = ("_items",)

    def __init__(self) -> None:
        self._items: list[Disposable] = []

    def push(self, item: Disposable) -> None:
        self._items.append(item)

    def remove(self, item: Disposable) -> None:
        try:  # noqa: SIM105
            self._items.remove(item)
        except ValueError:
            pass

    def reversed_items(self) -> list[Disposable]:
        return self._items[::-1]

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item: object) -> bool:
        return item in self._items


async def run_disposer(disposer: Disposable, *, label: str | None = None) -> None:
    """Run one disposer, syncing or async; exceptions are contained by callers."""
    result = disposer()
    if inspect.isawaitable(result):
        await result


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def is_bailed(value: Any) -> bool:
    return value is not None and value is not False


def qual_name(obj: Any) -> str:
    name = getattr(obj, "__name__", None) or getattr(obj, "__qualname__", None)
    return str(name) if name else repr(obj)
