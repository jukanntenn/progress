"""API tests for integration endpoints (spec 12, 15)."""

from __future__ import annotations

from progress.integrations.registry import discover_integrations


class TestListIntegrations:
    async def test_returns_registered_integrations(self, client) -> None:
        resp = await client.get("/api/v1/integrations")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        names = {item["name"] for item in body}
        expected = set(discover_integrations().keys())
        assert names == expected

    async def test_each_item_has_schema(self, client) -> None:
        resp = await client.get("/api/v1/integrations")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) > 0
        for item in body:
            assert "name" in item
            assert "config_schema" in item
            assert isinstance(item["config_schema"], dict)


class TestIntegrationStatus:
    async def test_returns_one_integration(self, client) -> None:
        names = list(discover_integrations().keys())
        assert names
        resp = await client.get(f"/api/v1/integrations/{names[0]}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == names[0]
        assert isinstance(body["config_schema"], dict)

    async def test_404_for_unknown_integration(self, client) -> None:
        resp = await client.get("/api/v1/integrations/does-not-exist/status")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
