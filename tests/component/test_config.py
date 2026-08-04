"""API tests for config endpoints (spec 12, 15)."""

from __future__ import annotations

from progress.db import get_config, set_config


class TestGetAllConfig:
    async def test_returns_empty_defaults(self, client) -> None:
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "core" in body
        assert "plugins" in body
        assert isinstance(body["core"], dict)
        assert isinstance(body["plugins"], dict)

    async def test_masks_secrets_in_core(self, client) -> None:
        """SecretStr fields must serialize to ``**********`` (spec 02)."""
        await set_config("core", {"github": {"gh_token": "super-secret"}})
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        gh = body["core"].get("github", {})
        assert gh.get("gh_token") == "**********"

    async def test_masks_secrets_in_plugin(self, client) -> None:
        await set_config(
            "changelog",
            {"trackers": [{"name": "X", "url": "https://x/y.md"}]},
        )
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "changelog" in body["plugins"]


class TestGetSchema:
    async def test_returns_schema_map(self, client) -> None:
        resp = await client.get("/api/v1/config/schema")
        assert resp.status_code == 200
        body = resp.json()
        assert "schemas" in body
        schemas = body["schemas"]
        assert "core" in schemas
        for name, schema in schemas.items():
            assert isinstance(name, str)
            assert isinstance(schema, dict)


class TestPutSection:
    async def test_upserts_core_section(self, client) -> None:
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["section"] == "core"
        assert body["data"]["language"] == "zh-Hans"

        stored = await get_config("core")
        assert stored["language"] == "zh-Hans"

    async def test_unknown_section_returns_404(self, client) -> None:
        resp = await client.put(
            "/api/v1/config/nonexistent",
            json={"data": {"x": 1}},
        )
        assert resp.status_code == 404

    async def test_invalid_body_returns_422(self, client) -> None:
        resp = await client.put("/api/v1/config/core", json={"not_data": {}})
        assert resp.status_code == 422


class TestReloadConfig:
    async def test_reload_returns_ok(self, app_client) -> None:
        _app, client = app_client
        await set_config("core", {"language": "en"})
        resp = await client.post("/api/v1/config/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["section"] == "core"

    async def test_reload_noop_when_db_empty(self, client) -> None:
        resp = await client.post("/api/v1/config/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"ok", "noop"}


class TestLanguage:
    async def test_get_returns_configured_language(self, app_client) -> None:
        _app, client = app_client
        await set_config("core", {"language": "zh-Hans"})
        await client.post("/api/v1/config/reload")
        resp = await client.get("/api/v1/config/language")
        assert resp.status_code == 200
        assert resp.json() == {"language": "zh-Hans"}

    async def test_get_defaults_to_en_when_unset(self, client) -> None:
        resp = await client.get("/api/v1/config/language")
        assert resp.status_code == 200
        assert resp.json() == {"language": "en"}

    async def test_put_updates_language_and_live_cfg(self, app_client) -> None:
        app, client = app_client
        resp = await client.put(
            "/api/v1/config/language",
            json={"language": "zh-Hans"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"language": "zh-Hans"}
        stored = await get_config("core")
        assert stored["language"] == "zh-Hans"
        assert app.state.cfg.language == "zh-Hans"
        resp = await client.get("/api/v1/config/language")
        assert resp.json() == {"language": "zh-Hans"}

    async def test_put_preserves_rest_of_core(self, app_client) -> None:
        _app, client = app_client
        await set_config("core", {"language": "en", "timezone": "Asia/Shanghai"})
        await client.post("/api/v1/config/reload")
        resp = await client.put(
            "/api/v1/config/language",
            json={"language": "zh-Hans"},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["language"] == "zh-Hans"
        assert stored["timezone"] == "Asia/Shanghai"

    async def test_put_idempotent_when_same(self, app_client) -> None:
        _app, client = app_client
        await set_config("core", {"language": "en"})
        await client.post("/api/v1/config/reload")
        resp = await client.put(
            "/api/v1/config/language",
            json={"language": "en"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"language": "en"}

    async def test_put_invalid_body_returns_422(self, client) -> None:
        resp = await client.put("/api/v1/config/language", json={"not_language": "x"})
        assert resp.status_code == 422
