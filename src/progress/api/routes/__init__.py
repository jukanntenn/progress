"""Route registration (spec 12).

Single entry :func:`register_routers` mounts every sub-router under the
``/api/v1`` prefix (except health probes which live at the root for k8s-style
probes that don't want auth-adjacent paths). The shared slowapi limiter is
wired here so per-route ``@limiter.limit(...)`` decorators work.
"""

from __future__ import annotations

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded

from progress.api.routes import (
    auth as auth_routes,
    config as config_routes,
    integrations as integration_routes,
    reports as report_routes,
    rss as rss_routes,
    system as system_routes,
)
from progress.api.routes._limiter import limiter, rate_limit_handler

API_PREFIX = "/api/v1"


def register_routers(app: FastAPI) -> None:
    """Mount every sub-router. System probes sit at the root (spec 12)."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)  # ty:ignore[invalid-argument-type]

    app.include_router(system_routes.router)
    app.include_router(auth_routes.router, prefix=API_PREFIX)
    app.include_router(report_routes.router, prefix=API_PREFIX)
    app.include_router(config_routes.router, prefix=API_PREFIX)
    app.include_router(integration_routes.router, prefix=API_PREFIX)
    app.include_router(rss_routes.router, prefix=API_PREFIX)


__all__ = ["API_PREFIX", "register_routers"]
