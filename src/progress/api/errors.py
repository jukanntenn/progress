"""Exception → HTTP mapping + unified error envelope (spec 12).

Per spec 12 all errors return:

    {"error": {"code": "...", "message": "...", "details": {...}}}

Layered exceptions (:mod:`progress.errors`) are mapped to HTTP statuses:

- :class:`ConfigException` → 400 (validation/shape problem with config payload)
- :class:`ClientException` → 400 (caller-supplied bad input)
- :class:`ExternalServiceException` → 502 (upstream aiohttp failure)
- :class:`ProgressException` (base) → 500 (any other app error)
- uncaught ``Exception`` → 500 (defensive; lifespan has Bugsink hook too)
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import sentry_sdk

from progress.api.schemas import ErrorDetail, ErrorResponse
from progress.errors import (
    ClientException,
    ConfigException,
    ExternalServiceException,
    ProgressException,
)

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers that emit the unified error envelope."""

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = "client_error" if exc.status_code < 500 else "internal_error"
        return _envelope(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            details=_request_details(request),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            status_code=422,
            code="validation_error",
            message="request validation failed",
            details={"errors": exc.errors(), **_request_details(request)},
        )

    @app.exception_handler(ConfigException)
    async def _config_exception_handler(request: Request, exc: ConfigException) -> JSONResponse:
        return _envelope(status_code=400, code="config_error", message=str(exc), details=_request_details(request))

    @app.exception_handler(ClientException)
    async def _client_error_handler(request: Request, exc: ClientException) -> JSONResponse:
        return _envelope(status_code=400, code="client_error", message=str(exc), details=_request_details(request))

    @app.exception_handler(ExternalServiceException)
    async def _external_service_handler(request: Request, exc: ExternalServiceException) -> JSONResponse:
        return _envelope(
            status_code=502, code="external_service_error", message=str(exc), details=_request_details(request)
        )

    @app.exception_handler(ProgressException)
    async def _progress_exception_handler(request: Request, exc: ProgressException) -> JSONResponse:
        _capture_sentry(exc)
        return _envelope(
            status_code=500,
            code="internal_error",
            message=str(exc) or exc.__class__.__name__,
            details=_request_details(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled exception in %s %s", request.method, request.url.path)
        _capture_sentry(exc)
        return _envelope(
            status_code=500,
            code="internal_error",
            message="internal server error",
            details=_request_details(request),
        )


def _envelope(*, status_code: int, code: str, message: str, details: dict[str, Any]) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _request_details(request: Request) -> dict[str, Any]:
    """Minimal request context for error details (no PII, no headers)."""
    return {"method": request.method, "path": request.url.path}


def _capture_sentry(exc: Exception) -> None:
    """Best-effort Bugsink capture; never let it raise."""
    with contextlib.suppress(Exception):
        sentry_sdk.capture_exception(exc)


__all__ = ["register_exception_handlers"]
