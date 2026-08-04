"""Unit tests for ``progress.observability.scrub`` (spec 04)."""

from __future__ import annotations

import pytest

from progress.observability.scrub import (
    scrub_event,
    scrub_secrets,
    scrub_secrets_processor,
    scrub_value,
)


class TestScrubSecretKeys:
    @pytest.mark.parametrize(
        "key",
        [
            "gh_token",
            "token",
            "password",
            "secret",
            "authorization",
            "webhook_url",
            "dsn",
            "api_key",
            "apikey",
            "api_secret",
            "access_token",
            "refresh_token",
            "client_secret",
            "private_key",
            "session_token",
        ],
    )
    def test_known_secret_key_redacted(self, key: str) -> None:
        out = scrub_value({key: "super-secret-value"})
        assert out[key] == "[REDACTED]"

    def test_partial_match_redacted(self) -> None:
        out = scrub_value({"my_token_field": "value"})
        assert out["my_token_field"] == "[REDACTED]"

    def test_case_insensitive(self) -> None:
        out = scrub_value({"API_KEY": "v"})
        assert out["API_KEY"] == "[REDACTED]"

    def test_non_secret_key_preserved(self) -> None:
        out = scrub_value({"username": "alice", "id": 42})
        assert out["username"] == "alice"
        assert out["id"] == 42


class TestScrubNested:
    def test_dict_in_dict(self) -> None:
        out = scrub_value({"outer": {"token": "x", "name": "y"}})
        assert out["outer"]["token"] == "[REDACTED]"
        assert out["outer"]["name"] == "y"

    def test_list_of_dicts(self) -> None:
        out = scrub_value({"items": [{"token": "a"}, {"name": "b"}]})
        assert out["items"][0]["token"] == "[REDACTED]"
        assert out["items"][1]["name"] == "b"

    def test_tuple(self) -> None:
        out = scrub_value(({"token": "x"}, "plain"))
        assert out[0]["token"] == "[REDACTED]"
        assert out[1] == "plain"

    def test_scalar_passthrough(self) -> None:
        assert scrub_value(42) == 42
        assert scrub_value(None) is None
        assert scrub_value(True) is True


class TestScrubUrl:
    def test_strips_credentials_from_url(self) -> None:
        url = "https://x-access-token:abc123@github.com/vitejs/vite.git"
        assert scrub_value(url) == "https://github.com/vitejs/vite.git"

    def test_url_with_port(self) -> None:
        url = "https://user:pass@host:8080/path"
        assert scrub_value(url) == "https://host:8080/path"

    def test_url_without_credentials_unchanged(self) -> None:
        url = "https://github.com/vitejs/vite.git"
        assert scrub_value(url) == url

    def test_non_url_string_unchanged(self) -> None:
        assert scrub_value("just a string") == "just a string"

    def test_string_with_no_scheme_unchanged(self) -> None:
        assert scrub_value("user:pass@host") == "user:pass@host"

    def test_string_with_space_treated_as_non_url(self) -> None:
        s = "https://example.com/ with space"
        assert scrub_value(s) == s


class TestScrubAliases:
    def test_scrub_secrets_alias(self) -> None:
        assert scrub_secrets({"token": "x"}) == scrub_value({"token": "x"})

    def test_scrub_event_returns_input(self) -> None:
        event = {"extra": {"password": "x"}}
        out = scrub_event(event)
        assert out["extra"]["password"] == "[REDACTED]"

    def test_scrub_event_with_hint(self) -> None:
        event = {"token": "x"}
        out = scrub_event(event, {"some": "hint"})
        assert out["token"] == "[REDACTED]"

    def test_processor_signature(self) -> None:
        event_dict = {"token": "x", "msg": "hi"}
        out = scrub_secrets_processor(None, "info", event_dict)
        assert out["token"] == "[REDACTED]"
        assert out["msg"] == "hi"
