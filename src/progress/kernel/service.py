"""Service declarations: the typed seam surface.

``Definition`` subclasses declare a ctx key (``service_name``) so
``ctx.get(MyDefinition)`` resolves by type; the attribute sugar ``ctx.db``
resolves the same key through ``__getattr__``. ``Service`` is the optional
base class for lifecycle-bearing service *values* — ``start`` runs inside
the provider's load, ``stop`` is the natural disposer body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from progress.kernel.context import Context


class Definition:
    """Abstract base for typed service keys; subclass and set ``service_name``."""

    service_name: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.service_name:
            for base in cls.__mro__[1:]:
                inherited = getattr(base, "service_name", "")
                if inherited:
                    cls.service_name = inherited
                    break


def service_name_of(ref: type) -> str:
    name = getattr(ref, "service_name", "")
    if not name:
        raise TypeError(f"{ref!r} has no service_name; subclass Definition to use it as a service key")
    return name


class Service:
    """Optional base for lifecycle-bearing service values.

    The provider constructs the instance in ``apply``, calls ``start`` (if
    defined) before the fiber goes ACTIVE, and registers ``stop`` (if
    defined) as the effect disposer — the service is only visible to
    consumers while its provider is ACTIVE, so readiness is structural.
    """

    service_name: ClassVar[str] = ""

    def __init__(self, ctx: Context, *, name: str | None = None) -> None:
        self.ctx = ctx
        self.name = name or self.service_name

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


__all__ = ["Definition", "Service", "service_name_of"]
