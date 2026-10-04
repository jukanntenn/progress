"""API tests for the unified error envelope (spec 12, 15).

Per spec 12 every error returns:
    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from asgi_lifespan import LifespanManager
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
import pytest

from progress.api import create_app
from progress.errors import (
    ClientException,
    ConfigException,
    ExternalServiceException,
    ProgressException,
)


@pytest.fixture
async def error_app_client(tmp_state_home: str, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """App with routes that raise each exception type so we can verify the envelope."""

    monkeypatch.setattr("progress.runtime.telemetry.setup_telemetry", lambda *a, **kw: None)
    monkeypatch.setattr("progress.runtime.telemetry.flush_telemetry", lambda: None)
    monkeypatch.setattr("progress.runtime.telemetry.configure_structlog", lambda *a, **kw: None)
    monkeypatch.setattr("progress.runtime.telemetry.init_bugsink", lambda *a, **kw: None)
    monkeypatch.setattr("progress.runtime.webserver.instrument_fastapi_app", lambda app: None)

    config_path = tmp_path / "config.toml"
    config_path.write_text(f'state_home = "{tmp_state_home}"\n', encoding="utf-8")
    app = create_app(str(config_path))

    router = APIRouter(tags=["errors"])

    @router.get("/errors/config")
    async def _raise_config() -> None:
        raise ConfigException("bad config payload")

    @router.get("/errors/client")
    async def _raise_client() -> None:
        raise ClientException("bad request from client")

    @router.get("/errors/external")
    async def _raise_external() -> None:
        raise ExternalServiceException("upstream blew up")

    @router.get("/errors/internal")
    async def _raise_internal() -> None:
        raise ProgressException("unexpected internal error")

    @router.get("/errors/unhandled")
    async def _raise_unhandled() -> None:
        raise RuntimeError("not a ProgressException")

    app.include_router(router)

    async with LifespanManager(app):
        # raise_app_exceptions=False: ServerErrorMiddleware always re-raises
        # after handling (Starlette design), so the ASGITransport would re-raise
        # the original exception instead of returning the 500 response.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


class TestErrorEnvelope:
    async def test_config_exception_returns_400(self, error_app_client) -> None:
        resp = await error_app_client.get("/errors/config")
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "config_error"
        assert "bad config payload" in body["error"]["message"]
        assert body["error"]["details"]["method"] == "GET"
        assert body["error"]["details"]["path"] == "/errors/config"

    async def test_client_error_returns_400(self, error_app_client) -> None:
        resp = await error_app_client.get("/errors/client")
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "client_error"

    async def test_external_service_returns_502(self, error_app_client) -> None:
        resp = await error_app_client.get("/errors/external")
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["code"] == "external_service_error"

    async def test_progress_exception_returns_500(self, error_app_client) -> None:
        resp = await error_app_client.get("/errors/internal")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert "unexpected internal error" in body["error"]["message"]

    async def test_unhandled_exception_returns_500(self, error_app_client) -> None:
        resp = await error_app_client.get("/errors/unhandled")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["message"] == "internal server error"
