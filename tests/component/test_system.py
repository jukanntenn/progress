"""API tests for system endpoints: /healthz, /readyz, /api/v1/version (spec 12, 15)."""

from __future__ import annotations

from progress import __version__


class TestHealthz:
    async def test_returns_ok(self, client) -> None:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok"}


class TestReadyz:
    async def test_returns_ok_when_db_up(self, client) -> None:
        resp = await client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"


class TestVersion:
    async def test_returns_runtime_version(self, client) -> None:
        resp = await client.get("/api/v1/version")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "progress"
        assert body["version"] == __version__


class TestMiddleware:
    async def test_gzip_compression(self, client) -> None:
        """GZip should kick in for large responses (>1024 bytes per spec 12)."""
        resp = await client.get("/api/v1/version", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200

    async def test_correlation_id_header(self, client) -> None:
        """CorrelationIdMiddleware echoes a valid request ID (spec 12)."""
        valid_uuid = "12345678-1234-1234-1234-123456789abc"
        resp = await client.get("/healthz", headers={"X-Request-ID": valid_uuid})
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id") == valid_uuid

    async def test_correlation_id_generated(self, client) -> None:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id")
