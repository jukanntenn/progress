"""Unit tests for e2e test-helper pure functions.

Tests ``_parse_compose_ps`` (Docker Compose JSON output parser) and
``_unmask_secrets`` / ``_dump_for_seed`` (SecretStr-aware config serializer).
"""

from __future__ import annotations

import json

from pydantic import SecretStr

from progress.integrations.feed.config import FeedIntegrationConfig
from tests.e2e.conftest import _dump_for_seed, _unmask_secrets
from tests.e2e.feed.conftest import _parse_compose_ps


class TestParseComposePs:
    """Tests for e2e/feed/conftest._parse_compose_ps."""

    @staticmethod
    def _call(output: str) -> dict[str, dict[str, str]]:

        return _parse_compose_ps(output)

    def test_empty_string(self) -> None:
        assert self._call("") == {}

    def test_ndjson_format(self) -> None:
        """Docker Compose v2.24+ emits one JSON object per line."""
        line1 = json.dumps({"Service": "db", "State": "running", "Health": "healthy"})
        line2 = json.dumps({"Service": "miniflux", "State": "running", "Health": "healthy"})
        result = self._call(f"{line1}\n{line2}")
        assert set(result.keys()) == {"db", "miniflux"}
        assert result["db"]["Health"] == "healthy"
        assert result["miniflux"]["State"] == "running"

    def test_json_array_format(self) -> None:
        """Older Docker Compose versions emit a single JSON array."""
        payload = [
            {"Service": "db", "State": "running"},
            {"Service": "miniflux", "State": "running"},
        ]
        result = self._call(json.dumps(payload))
        assert set(result.keys()) == {"db", "miniflux"}

    def test_single_json_object_with_services_key(self) -> None:
        payload = {"services": {"db": {"State": "running"}, "app": {"State": "running"}}}
        result = self._call(json.dumps(payload))
        assert result == {"db": {"State": "running"}, "app": {"State": "running"}}

    def test_ndjson_with_blank_lines(self) -> None:
        line = json.dumps({"Service": "db", "State": "running"})
        result = self._call(f"\n{line}\n\n")
        assert set(result.keys()) == {"db"}

    def test_ndjson_with_invalid_lines_skipped(self) -> None:
        line = json.dumps({"Service": "db", "State": "running"})
        result = self._call(f"not json\n{line}")
        assert set(result.keys()) == {"db"}


class TestUnmaskSecrets:
    """Tests for e2e/conftest._unmask_secrets."""

    @staticmethod
    def _call(data: dict[str, object], raw: dict[str, object]) -> dict[str, str | dict[str, str]]:

        return _unmask_secrets(data, raw)

    def test_secretstr_unmasked(self) -> None:
        result = self._call(
            {"api_key": "**********"},
            {"api_key": SecretStr("real_key")},
        )
        assert result == {"api_key": "real_key"}

    def test_non_secret_preserved(self) -> None:
        result = self._call(
            {"base_url": "http://x"},
            {"base_url": "http://x"},
        )
        assert result == {"base_url": "http://x"}

    def test_nested_secretstr_unmasked(self) -> None:
        result = self._call(
            {"github": {"gh_token": "**********"}, "language": "en"},
            {"github": {"gh_token": SecretStr("ghp_real")}, "language": "en"},
        )
        assert result == {"github": {"gh_token": "ghp_real"}, "language": "en"}

    def test_non_secretstr_raw_value_passed_through(self) -> None:
        result = self._call({"key": "some_value"}, {"key": "some_value"})
        assert result == {"key": "some_value"}

    def test_empty_dicts(self) -> None:
        assert self._call({}, {}) == {}


class TestDumpForSeed:
    """Tests for e2e/conftest._dump_for_seed."""

    @staticmethod
    def _call(cfg: object) -> dict[str, str | dict[str, str]]:

        return _dump_for_seed(cfg)

    def test_feed_config_preserves_api_key(self) -> None:

        cfg = FeedIntegrationConfig(base_url="http://localhost:18080", api_key=SecretStr("my_secret"))
        result = self._call(cfg)
        assert result["api_key"] == "my_secret"
        assert result["base_url"] == "http://localhost:18080"

    def test_feed_config_empty_key(self) -> None:

        cfg = FeedIntegrationConfig()
        result = self._call(cfg)
        assert result["api_key"] == ""
        assert result["base_url"] == ""

    def test_plain_dict_passthrough(self) -> None:
        data = {"key": "value"}
        result = self._call(data)
        assert result == {"key": "value"}
