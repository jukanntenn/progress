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

    async def test_returns_plaintext_secrets_in_core(self, client) -> None:
        """Secret fields must round-trip as real plaintext (spec 02 redesign)."""
        await set_config("core", {"github": {"gh_token": "super-secret"}})
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        gh = body["core"].get("github", {})
        assert gh.get("gh_token") == "super-secret"

    async def test_strips_internal_fields_from_core(self, client) -> None:
        """state_home / auth.secret_key / auth.initial_admin_password must be
        invisible to the Web UI (spec 3.6.2)."""
        await set_config(
            "core",
            {
                "state_home": "/app/data",
                "github": {"gh_token": "tok"},
                "auth": {
                    "secret_key": "jwt-secret",
                    "initial_admin_password": "admin-pw",
                    "initial_admin_username": "admin",
                },
            },
        )
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        core = resp.json()["core"]
        assert "state_home" not in core
        auth = core["auth"]
        assert "secret_key" not in auth
        assert "initial_admin_password" not in auth
        assert auth["initial_admin_username"] == "admin"

    async def test_returns_plaintext_secrets_in_plugin(self, client) -> None:
        await set_config(
            "changelog",
            {"trackers": [{"name": "X", "url": "https://x/y.md"}]},
        )
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "changelog" in body["plugins"]

    async def test_corrupted_core_returns_422(self, client) -> None:
        """Bad data in the DB must surface as 422, never partial/masked data."""
        await set_config("core", {"github": {"gh_token": "ok"}})
        row = await _config_row("core")
        row.data["observability"] = {"bugsink": [{"dsn": "x"}]}
        await row.save()
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 422
        assert "corrupted" in resp.json()["error"]["message"]

    async def test_corrupted_plugin_returns_422(self, client) -> None:
        await set_config("repo", {"first_run_lookback_commits": 3})
        row = await _config_row("repo")
        row.data["repos"] = [{"url": 123}]
        await row.save()
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 422
        assert "corrupted" in resp.json()["error"]["message"]


async def _config_row(section: str):
    from progress.db.models.config import Config  # noqa: PLC0415

    return await Config.get_or_none(section=section)


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

    async def test_core_schema_strips_internal_fields(self, client) -> None:
        """The schema must not advertise internal fields so the RJSF form never
        renders them (acceptance #10)."""
        resp = await client.get("/api/v1/config/schema")
        core = resp.json()["schemas"]["core"]
        assert "state_home" not in core["properties"]
        assert "$schema" not in core
        auth_defs = [d for d in core["$defs"].values() if d.get("title") == "AuthConfig"]
        assert len(auth_defs) == 1
        auth_props = auth_defs[0]["properties"]
        assert "secret_key" not in auth_props
        assert "initial_admin_password" not in auth_props
        assert "enabled" in auth_props

    async def test_core_schema_keeps_ui_group_annotations(self, client) -> None:
        """ui_group/ui_order layout hints survive the strip (spec 4.4)."""
        resp = await client.get("/api/v1/config/schema")
        core = resp.json()["schemas"]["core"]
        gh = next(d for d in core["$defs"].values() if d.get("title") == "GitHubConfig")
        assert gh["ui_group"] == "integrations"
        assert gh["ui_order"] == 10
        plugins = resp.json()["schemas"]["repo"]
        assert plugins["ui_group"] == "integrations"


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

    async def test_secret_round_trip_is_idempotent(self, client) -> None:
        """Editing a non-secret field must keep every secret's real value
        (acceptance #1: user edits language, secrets unchanged)."""
        await set_config(
            "core",
            {"github": {"gh_token": "ghp_REAL"}, "language": "en"},
        )
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans", "github": {"gh_token": "ghp_REAL"}}},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["language"] == "zh-Hans"
        assert stored["github"]["gh_token"] == "ghp_REAL"

    async def test_secret_updated_when_changed(self, client) -> None:
        """A user-edited secret overwrites the old value (acceptance #2)."""
        await set_config("core", {"github": {"gh_token": "ghp_OLD"}})
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"github": {"gh_token": "ghp_NEW"}}},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["github"]["gh_token"] == "ghp_NEW"

    async def test_secret_cleared_to_empty_string(self, client) -> None:
        """Clearing a secret stores '' — no sentinel, no null (acceptance #3)."""
        await set_config("core", {"github": {"gh_token": "ghp_OLD"}})
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"github": {"gh_token": ""}}},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["github"]["gh_token"] == ""

    async def test_null_secret_normalized_to_empty_string(self, client) -> None:
        """RJSF empty input produces null; the backend tolerates it as ''
        (acceptance #15/#16)."""
        await set_config("core", {"github": {"gh_token": "ghp_OLD"}})
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"github": {"gh_token": None, "proxy": None}}},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["github"]["gh_token"] == ""
        assert stored["github"]["proxy"] == ""

    async def test_bugsink_array_rejected_db_unchanged(self, client) -> None:
        """A list where a single object is expected must 422 and leave the DB
        intact (acceptance #7)."""
        await set_config("core", {"language": "en"})
        before = await get_config("core")
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans", "observability": {"bugsink": [{"dsn": "x"}]}}},
        )
        assert resp.status_code == 422
        assert "bugsink" in resp.json()["error"]["message"]
        after = await get_config("core")
        assert after == before

    async def test_unknown_field_rejected_db_unchanged(self, client) -> None:
        """extra='forbid' must 422 on unknown fields (acceptance #8)."""
        await set_config("core", {"language": "en"})
        before = await get_config("core")
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans", "unknown_field": 1}},
        )
        assert resp.status_code == 422
        after = await get_config("core")
        assert after == before

    async def test_recipient_poisoned_object_rejected(self, client) -> None:
        """recipient is list[str]; a [{}] element must 422 (the old corruption
        shape can no longer land)."""
        resp = await client.put(
            "/api/v1/config/core",
            json={
                "data": {
                    "notification": {"channels": [{"type": "email", "recipient": [{}], "host": "smtp.x", "user": "u"}]}
                }
            },
        )
        assert resp.status_code == 422

    async def test_internal_fields_preserved_on_put(self, client) -> None:
        """A PUT without state_home/secret_key keeps the DB values (acceptance
        #11: state_home survives; #14: secret_key stays and signs JWTs).

        The seed writes straight to the DB row because set_config itself
        preserves internal fields from the existing row (that is what is under
        test); production values are placed there by Ansible/bootstrap."""
        row = await _config_row("core")
        row.data["state_home"] = "/app/data"
        row.data["auth"]["secret_key"] = "jwt-secret-123"
        row.data["auth"]["initial_admin_password"] = "pw-456"
        await row.save()
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans"}},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["state_home"] == "/app/data"
        assert stored["auth"]["secret_key"] == "jwt-secret-123"
        assert stored["auth"]["initial_admin_password"] == "pw-456"

    async def test_put_never_overwrites_internal_fields(self, client) -> None:
        """Even a malicious payload carrying internal fields is ignored."""
        row = await _config_row("core")
        row.data["state_home"] = "/app/data"
        await row.save()
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"state_home": "/evil", "auth": {"secret_key": "evil"}}},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["state_home"] == "/app/data"
        assert stored["auth"]["secret_key"] != "evil"

    async def test_put_response_strips_internal_fields(self, client) -> None:
        await set_config("core", {"state_home": "/app/data", "language": "en"})
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans"}},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "state_home" not in data
        assert "secret_key" not in data.get("auth", {})

    async def test_unknown_section_returns_404(self, client) -> None:
        resp = await client.put(
            "/api/v1/config/nonexistent",
            json={"data": {"x": 1}},
        )
        assert resp.status_code == 404

    async def test_invalid_body_returns_422(self, client) -> None:
        resp = await client.put("/api/v1/config/core", json={"not_data": {}})
        assert resp.status_code == 422

    async def test_plugin_section_validated_on_put(self, client) -> None:
        await set_config("repo", {"first_run_lookback_commits": 3})
        resp = await client.put(
            "/api/v1/config/repo",
            json={"data": {"repos": [{"url": "vitejs/vite"}], "first_run_lookback_commits": 5}},
        )
        assert resp.status_code == 200
        stored = await get_config("repo")
        assert stored["repos"][0]["url"] == "vitejs/vite"

    async def test_plugin_section_rejects_bad_data(self, client) -> None:
        resp = await client.put(
            "/api/v1/config/feed",
            json={"data": {"base_url": 123}},
        )
        assert resp.status_code == 422

    async def test_put_refreshes_app_state_cfg(self, app_client) -> None:
        """PUT /config/core must refresh app.state.cfg so downstream consumers
        (notification test, report pipeline) see the new values immediately."""
        app, client = app_client
        before = app.state.cfg.timezone
        new_tz = "America/New_York" if before != "America/New_York" else "Europe/London"
        resp = await client.put("/api/v1/config/core", json={"data": {"timezone": new_tz}})
        assert resp.status_code == 200
        assert app.state.cfg.timezone == new_tz

    async def test_put_core_refreshes_notification_channels(self, app_client) -> None:
        """After PUT saves notification channels, test_notifications must see
        them without a manual reload (the original bug: email tests silently
        returned only feishu because app.state.cfg was stale)."""
        app, client = app_client
        resp = await client.put(
            "/api/v1/config/core",
            json={
                "data": {
                    "notification": {
                        "channels": [
                            {
                                "type": "console",
                                "enabled": True,
                            }
                        ]
                    }
                }
            },
        )
        assert resp.status_code == 200
        channels = app.state.cfg.notification.channels
        assert len(channels) == 1
        assert channels[0].type == "console"


class TestAuditEvent:
    async def test_put_records_config_updated_event(self, client, monkeypatch) -> None:
        """A successful PUT records who changed which section, without a field
        diff (acceptance #17)."""

        events: list[tuple[str, dict[str, object]]] = []

        def _capture(name: str, **kwargs: object) -> None:
            events.append((name, kwargs))

        import progress.api.routes.config as config_routes  # noqa: PLC0415

        monkeypatch.setattr(config_routes, "record_business_event", _capture)
        resp = await client.put(
            "/api/v1/config/core",
            json={"data": {"language": "zh-Hans"}},
        )
        assert resp.status_code == 200
        attrs = [
            attrs
            for name, kw in events
            if name == "progress.config.updated" and isinstance(attrs := kw.get("attributes"), dict)
        ]
        assert len(attrs) == 1
        section = attrs[0].get("section")
        assert section == "core"
        assert "user" in attrs[0]
        assert "diff" not in attrs[0]


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
    @staticmethod
    async def _reload_with_auth_off(app, client) -> None:
        """Reload re-merges the DB core section, which carries ``auth.enabled``
        from the normalized dump; the fixture's contract is auth-off, so the
        runtime flag is re-disabled after the reload."""
        resp = await client.post("/api/v1/config/reload")
        assert resp.status_code == 200
        app.state.cfg.auth.enabled = False

    async def test_get_returns_configured_language(self, app_client) -> None:
        app, client = app_client
        await set_config("core", {"language": "zh-Hans"})
        await self._reload_with_auth_off(app, client)
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
        app, client = app_client
        await set_config("core", {"language": "en", "timezone": "Asia/Shanghai"})
        await self._reload_with_auth_off(app, client)
        resp = await client.put(
            "/api/v1/config/language",
            json={"language": "zh-Hans"},
        )
        assert resp.status_code == 200
        stored = await get_config("core")
        assert stored["language"] == "zh-Hans"
        assert stored["timezone"] == "Asia/Shanghai"

    async def test_put_idempotent_when_same(self, app_client) -> None:
        app, client = app_client
        await set_config("core", {"language": "en"})
        await self._reload_with_auth_off(app, client)
        resp = await client.put(
            "/api/v1/config/language",
            json={"language": "en"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"language": "en"}

    async def test_put_invalid_body_returns_422(self, client) -> None:
        resp = await client.put("/api/v1/config/language", json={"not_language": "x"})
        assert resp.status_code == 422
