"""Kernel exception hierarchy.

``ServiceNotFound`` subclasses :class:`AttributeError` on purpose: attribute
probing (``hasattr``, ``copy``, ``pickle``) must never trigger service
resolution, and the attribute worldview and the domain worldview must agree —
a missing service *is* a missing attribute.
"""

from __future__ import annotations


class KernelError(Exception):
    """Base class for every kernel error."""


class ServiceNotFound(AttributeError, KernelError):  # noqa: N818
    """Raised when attribute access cannot resolve a service.

    Subclasses :class:`AttributeError` so ``hasattr(ctx, name)`` returns
    ``False`` and pickle/copy probing stays side-effect free.
    """

    def __init__(self, name: str, *, detail: str = "") -> None:
        self.service_name = name
        self.detail = detail
        super().__init__(f"service {name!r} not found" + (f": {detail}" if detail else ""))


class FiberError(KernelError):
    """A fiber failed during apply or update."""

    def __init__(self, fiber_name: str, cause: BaseException) -> None:
        self.fiber_name = fiber_name
        self.cause = cause
        super().__init__(f"fiber {fiber_name!r} failed: {cause}")
        self.__cause__ = cause


class BootError(KernelError):
    """Composition failed to activate; carries per-fiber diagnostics."""

    def __init__(self, diagnostics: list[str]) -> None:
        self.diagnostics = diagnostics
        preview = "; ".join(diagnostics[:3])
        super().__init__(f"composition failed to boot: {preview}")


class ValidationError(KernelError):
    """Plugin config failed validation."""


class InactiveEffectError(KernelError):
    """An effect was registered on a fiber that is no longer accepting them."""


__all__ = [
    "BootError",
    "FiberError",
    "InactiveEffectError",
    "KernelError",
    "ServiceNotFound",
    "ValidationError",
]
