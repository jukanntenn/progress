"""Unit tests for ``progress.config.loader`` + ``progress.config.root`` (spec 02).

Direct construction of CoreConfig (per spec 15) — no factory, no ConfigException
test fixture pollution.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, ValidationError
import pytest
import tomlkit

from progress.config.loader import (
    find_seed_file,
    load_config,
    load_seed,
    merge_db_config,
)
from progress.config.root import (
    AnalysisConfig,
    CoreConfig,
    GitHubConfig,
)
from progress.errors import ConfigException
from progress.integrations.registry import discover_integrations
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig


class TestCoreConfigDefaults:
    def test_zero_config(self) -> None:
        cfg = CoreConfig()
        assert cfg.state_home == "data"
        assert cfg.language == "en"
        assert cfg.timezone == "UTC"
        assert cfg.github.gh_token.get_secret_value() == ""
        assert cfg.analysis.provider == ""

    def test_state_home_override(self) -> None:
        cfg = CoreConfig(state_home="/tmp/progress-test")
        assert cfg.state_home == "/tmp/progress-test"

    def test_language_normalized_to_bcp47(self) -> None:
        assert CoreConfig(language="en").language == "en"
        assert CoreConfig(language="EN").language == "en"
        assert CoreConfig(language="zh-hans").language == "zh-Hans"
        assert CoreConfig(language="ZH-HANS").language == "zh-Hans"
        assert CoreConfig(language="zh-Hant").language == "zh-Hant"

    def test_language_region_subtag_uppercased(self) -> None:
        assert CoreConfig(language="pt-br").language == "pt-BR"

    def test_invalid_timezone_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoreConfig(timezone="Mars/Olympus")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoreConfig(unknown_field="oops")  # ty:ignore[unknown-argument]


class TestSecretStrMasking:
    def test_gh_token_secret_str(self) -> None:
        cfg = CoreConfig(github=GitHubConfig(gh_token=SecretStr("super-secret-token")))
        dumped = cfg.model_dump_json()
        assert "super-secret-token" not in dumped
        assert "**********" in dumped

    def test_api_key_secret_str(self) -> None:
        cfg = CoreConfig(analysis=AnalysisConfig(api_key=SecretStr("sk-test")))
        dumped = cfg.model_dump_json()
        assert "sk-test" not in dumped


class TestLoadConfig:
    def test_none_returns_defaults(self) -> None:
        cfg = load_config(None)
        assert cfg == CoreConfig()

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigException, match="config file not found"):
            load_config(str(tmp_path / "missing.toml"))

    def test_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text('state_home = "/tmp/x"\n', encoding="utf-8")
        cfg = load_config(str(path))
        assert cfg.state_home == "/tmp/x"

    def test_invalid_toml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text("not toml = = =\n", encoding="utf-8")
        with pytest.raises(ConfigException, match="failed to parse config"):
            load_config(str(path))

    def test_validation_error_pretty_message(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text('timezone = "Mars/Olympus"\n', encoding="utf-8")
        with pytest.raises(ConfigException, match="Configuration validation failed"):
            load_config(str(path))


class TestSeedFile:
    def test_find_seed_file_none(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text('state_home = "x"\n', encoding="utf-8")
        assert find_seed_file(str(path)) is None

    def test_find_seed_file_present(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text('state_home = "x"\n', encoding="utf-8")
        seed = tmp_path / "config.db.toml"
        seed.write_text('[core]\nlanguage = "zh-hans"\n', encoding="utf-8")
        assert find_seed_file(str(path)) == seed

    def test_find_seed_file_for_none_config_path(self) -> None:
        assert find_seed_file(None) is None

    def test_load_seed_extracts_sections(self, tmp_path: Path) -> None:
        seed = tmp_path / "config.db.toml"
        seed.write_text(
            '[core]\nlanguage = "zh-hans"\n[core.github]\ngh_token = "tok"\n[repo]\n[[repo.repos]]\nurl = "a/b"\n',
            encoding="utf-8",
        )
        out = load_seed(seed)
        assert "core" in out
        assert "repo" in out
        assert out["core"]["language"] == "zh-hans"
        assert out["repo"]["repos"][0]["url"] == "a/b"


class TestMergeDbConfig:
    def test_empty_db_returns_unchanged(self) -> None:
        cfg = CoreConfig(state_home="/tmp/x")
        assert merge_db_config(cfg, {}) is cfg

    def test_db_overrides_ansible(self) -> None:
        cfg = CoreConfig(state_home="/tmp/x", language="en")
        merged = merge_db_config(cfg, {"language": "zh-Hans"})
        assert merged.language == "zh-Hans"

    def test_state_home_preserved_from_ansible(self) -> None:
        cfg = CoreConfig(state_home="/tmp/ansible")
        merged = merge_db_config(cfg, {"state_home": "/should/be/ignored", "language": "zh-Hans"})
        assert merged.state_home == "/tmp/ansible"
        assert merged.language == "zh-Hans"

    def test_partial_merge_uses_model_defaults(self) -> None:
        """A partial db_core (e.g. {"language": ...}) fills missing fields with
        model defaults (spec 3.7.1: DB dict is the whole input; no cfg-dump
        merge). Production DB rows are always full normalized dumps, so a
        partial row only occurs transiently (seed bootstrap)."""
        cfg = CoreConfig(
            state_home="/tmp/x",
            github=GitHubConfig(gh_token=SecretStr("ghp_REAL_TOKEN")),
        )
        merged = merge_db_config(cfg, {"language": "zh-Hans"})
        assert merged.language == "zh-Hans"
        assert merged.github.gh_token.get_secret_value() == ""

    def test_db_plaintext_secret_round_trips(self) -> None:
        """DB stores plaintext (no mask sentinel); the merged config keeps the
        real secret value."""
        cfg = CoreConfig(state_home="/tmp/x")
        merged = merge_db_config(
            cfg,
            {
                "language": "zh-Hans",
                "github": {"gh_token": "ghp_REAL_TOKEN"},
                "notification": {"channels": [{"type": "feishu", "webhook_url": "https://open.feishu.cn/REAL"}]},
            },
        )
        assert merged.github.gh_token.get_secret_value() == "ghp_REAL_TOKEN"
        feishu = next(c for c in merged.notification.channels if c.type == "feishu")
        assert feishu.webhook_url.get_secret_value() == "https://open.feishu.cn/REAL"


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestExampleConfigFiles:
    """The committed example files must stay valid against the live schemas.

    Guards against drift between docs and code (spec 02 catalog).
    """

    def test_ansible_example_loads(self) -> None:
        cfg = load_config(str(REPO_ROOT / "config.example.toml"))
        assert cfg.state_home == "data"

    def test_db_seed_example_core_section_validates(self) -> None:

        data = tomlkit.loads((REPO_ROOT / "config.example.db.toml").read_text(encoding="utf-8"))
        core = dict(data.get("core", {}))
        CoreConfig.model_validate(core)

    def test_db_seed_example_plugin_sections_validate(self) -> None:

        data = tomlkit.loads((REPO_ROOT / "config.example.db.toml").read_text(encoding="utf-8"))
        for name, cls in discover_integrations().items():
            schema = getattr(cls, "config_schema", None)
            if schema is None:
                continue
            section_data = dict(data.get(name, {}))
            schema.model_validate(section_data)


class TestRepoItemConfig:
    """T6 — repo item defaults and extra-field rejection."""

    def test_track_toggles_default_true(self) -> None:

        item = RepoItemConfig(url="vitejs/vite")
        assert item.track_commits is True
        assert item.track_releases is True

    def test_extra_fields_rejected(self) -> None:

        with pytest.raises(ValidationError):
            RepoItemConfig(url="vitejs/vite", unknown_field="oops")  # ty:ignore[unknown-argument]


class TestRepoIntegrationConfig:
    """T6 — integration-level defaults and validation."""

    def test_defaults(self) -> None:

        cfg = RepoIntegrationConfig()
        assert cfg.first_run_lookback_commits == 3
        assert cfg.max_incremental_lookback_releases == 3

    def test_lookback_ge_one(self) -> None:

        with pytest.raises(ValidationError):
            RepoIntegrationConfig(first_run_lookback_commits=0)
        with pytest.raises(ValidationError):
            RepoIntegrationConfig(max_incremental_lookback_releases=0)
