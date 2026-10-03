"""Service store: implementation registry, resolution, provider notification.

Services are keyed by name; each name has one implementation per *isolate
scope label* (``None`` being the root scope). ``ctx.isolate(name, label)``
binds a name to a label on a child context — two isolates sharing a string
label share the implementation (scope joining), an anonymous isolate gets a
fresh unique label (scope shadowing).

Resolution honors the provider's lifecycle: an implementation is only visible
while its providing fiber is ACTIVE, which makes "service ready" a structural
fact rather than a convention.
"""

from __future__ import annotations

from collections import ChainMap
from dataclasses import dataclass, field
import itertools
from typing import TYPE_CHECKING, Any

from progress.kernel.errors import KernelError

if TYPE_CHECKING:
    from progress.kernel.fiber import Fiber

_label_counter = itertools.count(1)


def fresh_label() -> str:
    return f"#isolate-{next(_label_counter)}"


@dataclass
class Impl:
    name: str
    value: Any
    fiber: Fiber

    @property
    def available(self) -> bool:
        return self.fiber.state == "active"


class DuplicateServiceError(KernelError):
    pass


@dataclass
class ReflectService:
    """Root-owned service store; shared by every context in the tree."""

    store: dict[str, dict[str | None, Impl]] = field(default_factory=dict)

    def define(self, fiber: Fiber, chain: ChainMap[str, str], name: str, value: Any) -> Impl:
        label = chain.get(name)
        scopes = self.store.setdefault(name, {})
        if label in scopes:
            provider = scopes[label].fiber.name
            raise DuplicateServiceError(
                f"service {name!r} is already registered at {provider!r}; provide is single-owner per scope"
            )
        impl = Impl(name=name, value=value, fiber=fiber)
        scopes[label] = impl
        return impl

    def replace(self, chain: ChainMap[str, str], name: str, value: Any) -> Impl | None:
        """Swap the value inside the existing implementation (same provider fiber).

        The provider identity is unchanged so epochs stay stable; consumers
        that must observe the new value re-run via an explicit row-level
        update (the L0 reload), not via the epoch cascade.
        """
        impl = self.peek(chain, name)
        if impl is None:
            return None
        impl.value = value
        return impl

    def undefine(self, chain: ChainMap[str, str], name: str) -> Impl | None:
        label = chain.get(name)
        scopes = self.store.get(name)
        if not scopes or label not in scopes:
            return None
        return scopes.pop(label)

    def resolve(self, chain: ChainMap[str, str], name: str) -> Impl | None:
        label = chain.get(name)
        impl = self.store.get(name, {}).get(label)
        if impl is not None and impl.available:
            return impl
        return None

    def peek(self, chain: ChainMap[str, str], name: str) -> Impl | None:
        """Resolve ignoring the provider's lifecycle (diagnostics, reload)."""
        label = chain.get(name)
        return self.store.get(name, {}).get(label)

    def names(self) -> list[str]:
        return sorted(self.store)


__all__ = ["DuplicateServiceError", "Impl", "ReflectService", "fresh_label"]
