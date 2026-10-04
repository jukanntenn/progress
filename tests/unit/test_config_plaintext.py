"""Unit tests for the plaintext config write/read pipeline (spec 02 redesign).

Pure functions only (spec 15): ``_dump_plaintext`` / ``_unwrap_secrets`` /
``_preserve_internal_fields`` / ``_normalize_nulls`` / ``_get_section_model`` /
``_format_validation_errors`` / ``merge_db_config``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, SecretStr, ValidationError
import pytest

from progress.config.loader import merge_db_config
from progress.config.root import CoreConfig
from progress.config.schema import get_core_config_schema
from progress.db import (
    _dump_plaintext,
    _format_validation_errors,
    _get_section_model,
    _normalize_nulls,
    _preserve_internal_fields,
    _unwrap_secrets,
)


class _DemoModel(BaseModel):
    token: SecretStr
    name: str


class TestDumpPlaintext:
    def test_unwraps_nested_secrets(self) -> None:
        model = _DemoModel(token=SecretStr("sekrit"), name="n")
        out = _dump_plaintext(model)
        assert out == {"token": "sekrit", "name": "n"}

    def test_unwrap_secrets_recursive(self) -> None:
        obj = {
            "a": SecretStr("x"),
            "b": [SecretStr("y"), {"c": SecretStr("z"), "d": 1}],
            "e": "plain",
        }
        out = _unwrap_secrets(obj)
        assert out == {"a": "x", "b": ["y", {"c": "z", "d": 1}], "e": "plain"}

    def test_unwrap_empty_string_secret(self) -> None:
        model = _DemoModel(token=SecretStr(""), name="n")
        assert _dump_plaintext(model) == {"token": "", "name": "n"}


class TestPreserveInternalFields:
    def test_injects_missing_internal_fields(self) -> None:
        existing = {
            "state_home": "/app/data",
            "auth": {"secret_key": "sk", "initial_admin_password": "pw"},
        }
        out = _preserve_internal_fields({"language": "zh-Hans"}, existing)
        assert out["state_home"] == "/app/data"
        assert out["auth"]["secret_key"] == "sk"
        assert out["auth"]["initial_admin_password"] == "pw"

    def test_does_not_touch_other_fields(self) -> None:
        existing = {"state_home": "/app/data", "auth": {"secret_key": "sk"}}
        out = _preserve_internal_fields({"language": "zh-Hans"}, existing)
        assert set(out.keys()) == {"language", "state_home", "auth"}

    def test_empty_existing_injects_nothing(self) -> None:
        out = _preserve_internal_fields({"language": "zh-Hans"}, {})
        assert out == {"language": "zh-Hans"}

    def test_submitted_values_overridden_by_db(self) -> None:
        """DB is the single source of truth for internal fields."""
        existing = {"state_home": "/real", "auth": {"secret_key": "real-sk"}}
        out = _preserve_internal_fields(
            {"state_home": "/fake", "auth": {"secret_key": "fake-sk", "enabled": True}},
            existing,
        )
        assert out["state_home"] == "/real"
        assert out["auth"]["secret_key"] == "real-sk"
        assert out["auth"]["enabled"] is True

    def test_auth_missing_in_submit_still_preserved(self) -> None:
        existing = {"auth": {"secret_key": "sk", "initial_admin_password": "pw"}}
        out = _preserve_internal_fields({"language": "en"}, existing)
        assert out["auth"] == {"secret_key": "sk", "initial_admin_password": "pw"}


class TestNormalizeNulls:
    def _core_schema(self) -> dict[str, Any]:
        return get_core_config_schema()

    def test_top_level_string_null_to_empty(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {"language": {"type": "string"}}}
        out = _normalize_nulls({"language": None}, schema, schema)
        assert out == {"language": ""}

    def test_nested_object_through_ref(self) -> None:
        """D2: nulls inside $ref'd sub-models must be normalized."""
        schema = {
            "$defs": {
                "GitHubConfig": {
                    "type": "object",
                    "properties": {
                        "gh_token": {"type": "string", "format": "password"},
                        "proxy": {"type": "string"},
                    },
                }
            },
            "type": "object",
            "properties": {"github": {"$ref": "#/$defs/GitHubConfig"}},
        }
        out = _normalize_nulls({"github": {"gh_token": None, "proxy": None}}, schema, schema)
        assert out == {"github": {"gh_token": "", "proxy": ""}}

    def test_discriminated_union_list_item(self) -> None:
        """channels[].password null → '' via the discriminator member schema."""
        schema = {
            "$defs": {
                "EmailChannelConfig": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "const": "email"},
                        "password": {"type": "string"},
                    },
                },
                "FeishuChannelConfig": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "const": "feishu"},
                        "webhook_url": {"type": "string"},
                    },
                },
            },
            "type": "object",
            "properties": {
                "channels": {
                    "type": "array",
                    "items": {
                        "discriminator": {"propertyName": "type"},
                        "oneOf": [
                            {"$ref": "#/$defs/EmailChannelConfig"},
                            {"$ref": "#/$defs/FeishuChannelConfig"},
                        ],
                    },
                }
            },
        }
        data = {
            "channels": [
                {"type": "email", "password": None},
                {"type": "feishu", "webhook_url": None},
            ]
        }
        out = _normalize_nulls(data, schema, schema)
        assert out["channels"][0]["password"] == ""
        assert out["channels"][1]["webhook_url"] == ""

    def test_plain_list_of_object_with_ref_items(self) -> None:
        """repo.repos items are $refs; nulls inside must normalize."""
        schema = {
            "$defs": {
                "RepoItemConfig": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}, "branch": {"type": "string"}},
                }
            },
            "type": "object",
            "properties": {"repos": {"type": "array", "items": {"$ref": "#/$defs/RepoItemConfig"}}},
        }
        out = _normalize_nulls({"repos": [{"url": None, "branch": "main"}]}, schema, schema)
        assert out == {"repos": [{"url": "", "branch": "main"}]}

    def test_non_string_nulls_passthrough(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "concurrency": {"type": "integer"},
                "enabled": {"type": "boolean"},
            },
        }
        out = _normalize_nulls({"concurrency": None, "enabled": None}, schema, schema)
        assert out == {"concurrency": None, "enabled": None}

    def test_unknown_key_passthrough(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        out = _normalize_nulls({"a": "x", "unknown": None}, schema, schema)
        assert out == {"a": "x", "unknown": None}

    def test_known_nulls_for_unknown_prop_passthrough(self) -> None:
        """A key the schema doesn't know is not a string-per-schema, so its null
        stays; Pydantic extra='forbid' rejects it later (as intended)."""
        schema = {"type": "object", "properties": {}}
        out = _normalize_nulls({"mystery": None}, schema, schema)
        assert out == {"mystery": None}


class TestCoreSchemaStrip:
    def test_internal_fields_absent(self) -> None:
        schema = get_core_config_schema()
        assert "state_home" not in schema["properties"]
        auth = next(d for d in schema["$defs"].values() if d.get("title") == "AuthConfig")
        assert "secret_key" not in auth["properties"]
        assert "initial_admin_password" not in auth["properties"]

    def test_no_schema_keyword_emitted(self) -> None:
        """D1: a draft/2020-12 $schema breaks the RJSF ajv8 (draft-07) validator."""
        assert "$schema" not in get_core_config_schema()


class TestSectionModel:
    def test_core_maps_to_coreconfig(self) -> None:

        assert _get_section_model("core") is CoreConfig

    def test_plugin_maps_to_config_schema(self) -> None:

        model = _get_section_model("repo")
        assert model is not None
        assert model.model_json_schema()["title"] == "RepoIntegrationConfig"

    def test_unknown_returns_none(self) -> None:

        assert _get_section_model("nonexistent") is None


class TestFormatValidationErrors:
    def test_formats_locations_and_messages(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.model_validate({"github": {"gh_token": 42}})
        out = _format_validation_errors("core", exc_info.value)
        assert "invalid config for section 'core':" in out
        assert "github.gh_token" in out

    def test_multi_line_output(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CoreConfig.model_validate({"github": {"gh_token": 1, "proxy": 2}})
        lines = _format_validation_errors("core", exc_info.value).splitlines()
        assert len(lines) == 3


class TestMergeDbConfigNewSemantics:
    def test_db_dict_is_whole_input(self) -> None:
        cfg = CoreConfig(state_home="/app/data")
        merged = merge_db_config(cfg, {"github": {"gh_token": "tok"}})
        assert merged.github.gh_token.get_secret_value() == "tok"

    def test_state_home_always_from_ansible(self) -> None:
        cfg = CoreConfig(state_home="/ansible")
        merged = merge_db_config(cfg, {"state_home": "/db", "language": "zh-Hans"})
        assert merged.state_home == "/ansible"
        assert merged.language == "zh-Hans"

    def test_bad_db_raises_validation_error(self) -> None:
        cfg = CoreConfig(state_home="/x")
        with pytest.raises(ValidationError):
            merge_db_config(cfg, {"observability": {"bugsink": [{"dsn": "x"}]}})
