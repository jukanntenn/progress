"""Tests for database path resolution (must be CWD-independent)."""

from progress.db import resolve_db_path


def test_progress_db_path_env_overrides(monkeypatch, tmp_path):
    env_db = tmp_path / "env.db"
    monkeypatch.setenv("PROGRESS_DB_PATH", str(env_db))

    assert resolve_db_path("data", "/app/config.toml") == str(env_db.resolve())


def test_relative_data_dir_anchored_to_config_dir_not_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("PROGRESS_DB_PATH", raising=False)
    monkeypatch.delenv("PROGRESS_HOME", raising=False)

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"

    monkeypatch.chdir(tmp_path)

    resolved = resolve_db_path("data", str(config_path))

    assert resolved == str((config_dir / "data" / "progress.db").resolve())


def test_progress_home_anchors_relative_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("PROGRESS_DB_PATH", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PROGRESS_HOME", str(home))

    resolved = resolve_db_path("data", "/wherever/config.toml")

    assert resolved == str((home / "data" / "progress.db").resolve())


def test_absolute_data_dir_used_as_is(monkeypatch, tmp_path):
    monkeypatch.delenv("PROGRESS_DB_PATH", raising=False)
    monkeypatch.delenv("PROGRESS_HOME", raising=False)
    abs_data = tmp_path / "absdata"

    resolved = resolve_db_path(str(abs_data), None)

    assert resolved == str((abs_data / "progress.db").resolve())
