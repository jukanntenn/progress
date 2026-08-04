"""Component tests for auth bootstrap + user model + management commands."""

from __future__ import annotations

from pydantic import SecretStr
import pytest
from tortoise.exceptions import IntegrityError

from progress.api.auth_bootstrap import bootstrap_auth
from progress.config.root import CoreConfig
from progress.db import close_db, init_db
from progress.db.models import User
from progress.utils.security import hash_password, verify_password


@pytest.fixture(autouse=True)
async def _db(tmp_state_home: str):
    """Per-test fresh DB."""
    await init_db(tmp_state_home)
    yield

    await close_db()


class TestUserModel:
    async def test_create_user(self) -> None:
        user = await User.create(
            username="alice",
            hashed_password=hash_password("pass123"),
            is_active=True,
            is_superuser=False,
        )
        assert user.id is not None
        fetched = await User.filter(username="alice").first()
        assert fetched is not None
        assert fetched.is_active is True

    async def test_username_unique(self) -> None:

        await User.create(username="dup", hashed_password="x")
        with pytest.raises(IntegrityError):
            await User.create(username="dup", hashed_password="y")

    async def test_updated_at_auto_refreshes(self) -> None:
        user = await User.create(username="bob", hashed_password="x")
        old_updated = user.updated_at
        user.email = "bob@example.com"
        await user.save(update_fields=["email", "updated_at"])
        refetched = await User.get(id=user.id)
        assert refetched.updated_at >= old_updated


class TestBootstrapAuth:
    async def test_creates_admin_when_table_empty(self) -> None:

        cfg = CoreConfig()
        cfg.auth.enabled = True
        cfg.auth.initial_admin_username = "root"
        cfg.auth.initial_admin_password = SecretStr("known-pass-1")
        cfg = await bootstrap_auth(cfg)
        admin = await User.filter(username="root").first()
        assert admin is not None
        assert admin.is_superuser is True
        assert verify_password("known-pass-1", admin.hashed_password)

    async def test_does_not_recreate_admin_when_exists(self) -> None:

        await User.create(username="existing", hashed_password="x", is_superuser=True)
        cfg = CoreConfig()
        cfg.auth.initial_admin_username = "admin"
        await bootstrap_auth(cfg)
        assert await User.all().count() == 1
        assert (await User.filter(username="admin").first()) is None

    async def test_generates_secret_key_when_empty(self) -> None:

        cfg = CoreConfig()
        assert cfg.auth.secret_key.get_secret_value() == ""
        cfg = await bootstrap_auth(cfg)
        assert len(cfg.auth.secret_key.get_secret_value()) > 0

    async def test_preserves_existing_secret_key(self) -> None:

        cfg = CoreConfig()
        cfg.auth.enabled = False
        cfg.auth.secret_key = SecretStr("preconfigured-key")
        cfg = await bootstrap_auth(cfg)
        assert cfg.auth.secret_key.get_secret_value() == "preconfigured-key"

    async def test_no_admin_when_auth_disabled(self) -> None:

        cfg = CoreConfig()
        cfg.auth.enabled = False
        await bootstrap_auth(cfg)
        assert await User.all().count() == 0
