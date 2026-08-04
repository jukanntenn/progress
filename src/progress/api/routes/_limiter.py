"""Shared slowapi limiter instance (spec 12).

One :class:`slowapi.Limiter` per process, registered on the FastAPI app in
:mod:`progress.api.routes`. Routes that need per-endpoint limits import
``limiter`` from here and apply ``@limiter.limit("...")``; the route signature
must include ``request: Request`` (slowapi source: ``extension.py:711-718``).
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["240 per minute"],
)


def rate_limit_handler(_request, exc: RateLimitExceeded):
    """Render :class:`RateLimitExceeded` as the unified error envelope."""

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limit_exceeded",
                "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
                "details": {},
            }
        },
    )


__all__ = ["limiter", "rate_limit_handler"]
