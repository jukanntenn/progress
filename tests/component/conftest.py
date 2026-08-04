"""Component-test-scoped fixtures (spec 15).

Lives in ``tests/component/conftest.py`` so it is visible to every file under
``tests/component/`` (including the former ``tests/api/`` suite, now merged
here per the unit/component/e2e three-layer model) but not to other layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
import pytest

from progress.api import create_app
from progress.cli.notifications.base import ChannelPayload, SendResult
from progress.db.models import User
from progress.db.models.report import Report
from progress.utils.security import hash_password

if TYPE_CHECKING:
    from pathlib import Path


class RecordingChannel:
    """Test double that records every payload it receives."""

    def __init__(self, name: str = "recording") -> None:
        self.name = name
        self.received: list[tuple[str, int]] = []

    async def send(self, payload: ChannelPayload) -> SendResult:
        self.received.append((getattr(payload, "title", "?"), len(self.received)))
        return SendResult(channel=self.name, ok=True)


@pytest.fixture
def recording_channel() -> RecordingChannel:
    return RecordingChannel()


@pytest.fixture
async def app_client(tmp_state_home: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Yield ``(app, client)`` with lifespan wired up + DB initialized.

    Observability setup is stubbed out (spec 15: no disk IO in tests, no
    global state pollution across tests).

    Auth is **disabled** for this fixture so the existing report/config/integration
    tests (which test non-auth concerns) don't each need to log in. Auth-specific
    tests use the ``auth_client`` fixture instead.
    """
    monkeypatch.setattr("progress.api.setup_observability", lambda *a, **kw: None)
    monkeypatch.setattr("progress.api.shutdown_observability", lambda: None)
    monkeypatch.setattr("progress.api.instrument_fastapi_app", lambda app: None)

    config_path = tmp_path / "config.toml"
    config_path.write_text(f'state_home = "{tmp_state_home}"\n', encoding="utf-8")

    app = create_app(str(config_path))
    async with LifespanManager(app):
        # Disable auth post-startup so existing tests don't need login.
        app.state.cfg.auth.enabled = False
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


@pytest.fixture
async def auth_client(tmp_state_home: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Yield ``(app, client)`` with auth **enabled** + a seeded admin user.

    Use for tests that verify authentication/authorization behaviour. The
    returned client has ``PROGRESS_TEST_TOKEN`` in env; tests can call
    ``_login(client)`` to get a token, or use the ``authed_client`` fixture
    which is already logged in.
    """
    monkeypatch.setattr("progress.api.setup_observability", lambda *a, **kw: None)
    monkeypatch.setattr("progress.api.shutdown_observability", lambda: None)
    monkeypatch.setattr("progress.api.instrument_fastapi_app", lambda app: None)

    config_path = tmp_path / "config.toml"
    config_path.write_text(f'state_home = "{tmp_state_home}"\n', encoding="utf-8")

    app = create_app(str(config_path))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


@pytest.fixture
async def authed_client(auth_client):
    """``auth_client`` but already logged in as the seeded admin.

    The bootstrap creates an admin with a *random* password (logged at WARNING).
    To get a known credential, we reset the admin password via the management
    helper before logging in.
    """

    _app, client = auth_client
    admin = await User.filter(username="admin").first()
    assert admin is not None, "bootstrap should have created an admin"
    admin.hashed_password = hash_password("test-password-123")
    await admin.save(update_fields=["hashed_password", "updated_at"])

    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password-123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
async def client(app_client):
    """Convenience: just the httpx client."""
    _app, client = app_client
    return client


@pytest.fixture
async def db_with_reports(app_client):
    """Seed the DB with a couple of reports for list/detail tests."""

    await Report.create(
        report_type="aggregated",
        title="First report",
        content="# Hello\n\nworld",
        commit_hash="abc123",
        commit_count=3,
    )
    await Report.create(
        report_type="changelog_update",
        title="Second report",
        content="## v2\n\n- thing",
        commit_hash="def456",
        commit_count=1,
    )
    return app_client
