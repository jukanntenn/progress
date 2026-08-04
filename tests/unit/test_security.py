"""Unit tests for ``progress.utils.security`` primitives (hashing, JWT, decode).

Covers Argon2id password hashing and HS256 access/refresh token creation and
decode. The decode helpers raise :class:`jwt.PyJWTError` on any validation
failure; the HTTP-layer translation to ``HTTPException(401)`` lives in
``progress.api.auth`` and is exercised through the auth route tests.
"""

from __future__ import annotations

import time

import jwt
import pytest

from progress.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self) -> None:
        h = hash_password("s3cret-pass")
        assert h != "s3cret-pass"
        assert verify_password("s3cret-pass", h) is True

    def test_wrong_password_fails(self) -> None:
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_hash_is_non_deterministic(self) -> None:
        """Argon2 uses a random salt, so two hashes of the same password differ."""
        h1 = hash_password("same-pass")
        h2 = hash_password("same-pass")
        assert h1 != h2
        assert verify_password("same-pass", h1)
        assert verify_password("same-pass", h2)


class TestCreateAccessToken:
    def test_token_contains_subject(self) -> None:
        token = create_access_token(subject="alice", secret_key="k" * 32, expires_minutes=60)
        payload = jwt.decode(token, "k" * 32, algorithms=["HS256"])
        assert payload["sub"] == "alice"
        assert "exp" in payload

    def test_token_contains_access_type(self) -> None:
        token = create_access_token(subject="alice", secret_key="k" * 32, expires_minutes=60)
        payload = jwt.decode(token, "k" * 32, algorithms=["HS256"])
        assert payload["type"] == "access"

    def test_token_expiry_in_future(self) -> None:
        token = create_access_token(subject="bob", secret_key="k" * 32, expires_minutes=30)
        payload = jwt.decode(token, "k" * 32, algorithms=["HS256"])
        now = int(time.time())
        assert payload["exp"] > now
        assert payload["exp"] <= now + 31 * 60


class TestCreateRefreshToken:
    def test_token_contains_refresh_type(self) -> None:
        token = create_refresh_token(subject="alice", secret_key="k" * 32, expires_days=30)
        payload = jwt.decode(token, "k" * 32, algorithms=["HS256"])
        assert payload["sub"] == "alice"
        assert payload["type"] == "refresh"

    def test_token_long_expiry(self) -> None:
        token = create_refresh_token(subject="bob", secret_key="k" * 32, expires_days=30)
        payload = jwt.decode(token, "k" * 32, algorithms=["HS256"])
        now = int(time.time())
        assert payload["exp"] > now + 29 * 86400
        assert payload["exp"] <= now + 31 * 86400


class TestDecodeAccessToken:
    def test_decode_returns_subject(self) -> None:
        token = create_access_token(subject="carol", secret_key="my-secret", expires_minutes=60)
        assert decode_access_token(token, "my-secret") == "carol"

    def test_decode_rejects_refresh_token(self) -> None:

        token = create_refresh_token(subject="carol", secret_key="my-secret", expires_days=30)
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(token, "my-secret")

    def test_decode_wrong_secret_raises(self) -> None:

        token = create_access_token(subject="carol", secret_key="secret-a", expires_minutes=60)
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(token, "secret-b")

    def test_decode_expired_raises(self) -> None:

        token = create_access_token(subject="carol", secret_key="k" * 32, expires_minutes=-1)
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(token, "k" * 32)

    def test_decode_garbage_raises(self) -> None:

        with pytest.raises(jwt.PyJWTError):
            decode_access_token("not.a.jwt", "k" * 32)

    def test_decode_missing_sub_raises(self) -> None:

        token = jwt.encode({"exp": int(time.time()) + 60}, "k" * 32, algorithm="HS256")
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(token, "k" * 32)


class TestDecodeRefreshToken:
    def test_decode_returns_subject(self) -> None:
        token = create_refresh_token(subject="carol", secret_key="my-secret", expires_days=30)
        assert decode_refresh_token(token, "my-secret") == "carol"

    def test_decode_rejects_access_token(self) -> None:

        token = create_access_token(subject="carol", secret_key="my-secret", expires_minutes=60)
        with pytest.raises(jwt.PyJWTError):
            decode_refresh_token(token, "my-secret")

    def test_decode_wrong_secret_raises(self) -> None:

        token = create_refresh_token(subject="carol", secret_key="secret-a", expires_days=30)
        with pytest.raises(jwt.PyJWTError):
            decode_refresh_token(token, "secret-b")

    def test_decode_garbage_raises(self) -> None:

        with pytest.raises(jwt.PyJWTError):
            decode_refresh_token("not.a.jwt", "k" * 32)
