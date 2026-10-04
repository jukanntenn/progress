"""progress.kernel — a cordis-semantics plugin kernel (PRFC 2026-08-31).

A small kernel where a plugin is ``apply(ctx, config)`` plus three
declarations (``inject``, ``provide``, ``Config`` as a pydantic model); boot
order is expressed as service dependencies rather than sequencing code; every
registration is a reversible effect disposed in reverse order; events are the
only lateral extension point with five dispatch modes as public contract.

The kernel depends on nothing beyond the standard library (and pydantic for
plugin config validation) — enforced by an import-linter contract.
"""

from progress.kernel.compose import Entry, boot, mount
from progress.kernel.context import Context, RegistryService, RootServices, root_context
from progress.kernel.errors import (
    BootError,
    FiberError,
    InactiveEffectError,
    KernelError,
    ServiceNotFound,
    ValidationError,
)
from progress.kernel.events import (
    DISPATCH_MODES,
    EventSpec,
    EventsService,
    catalog,
    declare_event,
    set_background_error_handler,
)
from progress.kernel.fiber import INACTIVE, Fiber, FiberState, PluginRuntime
from progress.kernel.patches import (
    Patch as Patch,
    PyExpr as PyExpr,
    Row as Row,
    apply_patches as apply_patches,
    dump_rows as dump_rows,
    parse_patch_document as parse_patch_document,
)
from progress.kernel.reflect import DuplicateServiceError, ReflectService
from progress.kernel.service import Definition, Service, service_name_of

__version__ = "0.1.0"

__all__ = [
    "DISPATCH_MODES",
    "INACTIVE",
    "BootError",
    "Context",
    "Definition",
    "DuplicateServiceError",
    "Entry",
    "EventSpec",
    "EventsService",
    "Fiber",
    "FiberError",
    "FiberState",
    "InactiveEffectError",
    "KernelError",
    "PluginRuntime",
    "ReflectService",
    "RegistryService",
    "RootServices",
    "Service",
    "ServiceNotFound",
    "ValidationError",
    "boot",
    "catalog",
    "declare_event",
    "mount",
    "root_context",
    "service_name_of",
    "set_background_error_handler",
]
