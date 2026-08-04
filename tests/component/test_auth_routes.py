"""API tests for auth endpoints (login, me, change-password, refresh, protection).

Uses the ``auth_client`` (auth enabled) and ``authed_client`` (pre-logged-in)
fixtures from the shared conftest.
"""

from __future__ import annotations

from progress.db.models import User
from progress.utils.security import hash_password


class TestLogin:
    async def test_login_success_returns_tokens(self, auth_client) -> None:

        _app, client = auth_client
        admin = await User.filter(username="admin").first()
        assert admin is not None
        admin.hashed_password = hash_password("test-password-123")
        await admin.save(update_fields=["hashed_password", "updated_at"])

        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password-123"})
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 0
        assert len(body["refresh_token"]) > 0

    async def test_login_wrong_password_returns_401(self, auth_client) -> None:
        _, client = auth_client
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
        assert "Incorrect" in r.json()["error"]["message"]

    async def test_login_unknown_user_returns_401(self, auth_client) -> None:
        _, client = auth_client
        r = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert r.status_code == 401

    async def test_login_empty_body_returns_422(self, auth_client) -> None:
        _, client = auth_client
        r = await client.post("/api/v1/auth/login", json={})
        assert r.status_code == 422


class TestMe:
    async def test_me_with_valid_token(self, authed_client) -> None:
        r = await authed_client.get("/api/v1/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "admin"
        assert body["is_superuser"] is True

    async def test_me_without_token_returns_401(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401

    async def test_me_with_invalid_token_returns_401(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401


class TestChangePassword:
    async def test_change_password_success(self, authed_client) -> None:
        r = await authed_client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "test-password-123", "new_password": "new-password-456"},
        )
        assert r.status_code == 200
        # Old password should no longer work
        r2 = await authed_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "test-password-123"},
        )
        assert r2.status_code == 401

    async def test_change_password_wrong_current_returns_400(self, authed_client) -> None:
        r = await authed_client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "wrong", "new_password": "new-password-456"},
        )
        assert r.status_code == 400

    async def test_change_password_too_short_returns_422(self, authed_client) -> None:
        r = await authed_client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "test-password-123", "new_password": "short"},
        )
        assert r.status_code == 422


class TestEndpointProtection:
    async def test_reports_requires_auth(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/api/v1/reports")
        assert r.status_code == 401

    async def test_reports_accessible_with_token(self, authed_client) -> None:
        r = await authed_client.get("/api/v1/reports")
        assert r.status_code == 200

    async def test_config_requires_auth(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/api/v1/config")
        assert r.status_code == 401

    async def test_integrations_requires_auth(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/api/v1/integrations")
        assert r.status_code == 401


class TestPublicEndpoints:
    async def test_healthz_is_public(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/healthz")
        assert r.status_code == 200

    async def test_readyz_is_public(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/readyz")
        assert r.status_code == 200

    async def test_rss_is_public(self, auth_client) -> None:
        _, client = auth_client
        r = await client.get("/api/v1/rss")
        assert r.status_code == 200


class TestRefresh:
    async def _set_admin_password(self, auth_client) -> None:

        _app, _client = auth_client
        admin = await User.filter(username="admin").first()
        assert admin is not None
        admin.hashed_password = hash_password("test-password-123")
        await admin.save(update_fields=["hashed_password", "updated_at"])

    async def test_refresh_with_valid_token_returns_new_tokens(self, auth_client) -> None:
        await self._set_admin_password(auth_client)
        _, client = auth_client
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password-123"})
        assert r.status_code == 200
        refresh_token = r.json()["refresh_token"]

        r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert r2.status_code == 200
        body = r2.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 0
        assert len(body["refresh_token"]) > 0

    async def test_refresh_with_access_token_returns_401(self, auth_client) -> None:
        await self._set_admin_password(auth_client)
        _, client = auth_client
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password-123"})
        assert r.status_code == 200
        access_token = r.json()["access_token"]

        r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
        assert r2.status_code == 401

    async def test_refresh_with_invalid_token_returns_401(self, auth_client) -> None:
        _, client = auth_client
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-valid-token"})
        assert r.status_code == 401

    async def test_refresh_rotation(self, auth_client) -> None:
        await self._set_admin_password(auth_client)
        _, client = auth_client
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password-123"})
        assert r.status_code == 200
        first_refresh = r.json()["refresh_token"]

        r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
        assert r2.status_code == 200
        second_refresh = r2.json()["refresh_token"]
        assert second_refresh != first_refresh
