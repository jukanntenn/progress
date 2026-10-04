"""System endpoints: ``/healthz``, ``/readyz``, ``/api/v1/version`` (spec 12).

- ``/healthz`` is the liveness probe: returns 200 ``{"status": "ok"}`` with no
  DB hit. k8s uses this to decide whether to route traffic.
- ``/readyz`` is the readiness probe: pings the DB so a half-started pod fails
  readiness before the lifespan finishes wiring things up.
- ``/api/v1/version`` exposes the runtime version (informational).
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Response, status
from tortoise import Tortoise

from progress import __version__
from progress.api.schemas import HealthResponse, ReadyResponse, VersionResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/healthz", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def healthz() -> HealthResponse:
    """Liveness probe — no DB hit (spec 12)."""
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    response_model=ReadyResponse,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def readyz(response: Response) -> ReadyResponse:
    """Readiness probe — pings the DB (spec 12).

    Returns the ``ReadyResponse`` model on both 200 and 503 so the
    ``response_model`` validation always applies (no raw ``JSONResponse``
    bypass). The status code is driven via the injected ``Response`` object.
    """
    db_state = "ok"
    try:
        conn = Tortoise.get_connection("default")
        await conn.execute_query("SELECT 1")
    except Exception as e:
        logger.warning("readyz DB ping failed: %s", e)
        db_state = "fail"
    response.status_code = status.HTTP_200_OK if db_state == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ok" if db_state == "ok" else "fail", database=db_state)


@router.get(
    "/api/v1/version",
    response_model=VersionResponse,
    status_code=status.HTTP_200_OK,
    tags=["system"],
)
async def version() -> VersionResponse:
    """Runtime version info (spec 12).

    ``git_sha`` is injected at image build time via the ``GIT_SHA`` build arg
    (``unknown`` outside a container). Deploy automation compares it against
    the expected commit to confirm the new image is actually live.
    """
    return VersionResponse(name="progress", version=__version__, git_sha=os.environ.get("GIT_SHA", "unknown"))


__all__ = ["router"]
