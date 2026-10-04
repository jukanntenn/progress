"""Composition tree parity (PRFC 2026-08-31, phase 1 acceptance).

``compose_base`` is the single ordering authority; both entry points must
boot the same base rows. Entry ids are stable contract (phase-four patch
layers target rows by id).
"""

from __future__ import annotations

from types import SimpleNamespace

from progress.config.root import CoreConfig
from progress.runtime import BASE_ENTRY_IDS, SERVE_EXTRA_IDS, compose_base, compose_serve, compose_users


def _cfg(tmp_state_home: str) -> CoreConfig:
    return CoreConfig(state_home=tmp_state_home)


def test_base_entry_ids_are_frozen():
    entries = compose_base(_cfg("/tmp/x"), config_path=None)
    assert [e.id for e in entries] == list(BASE_ENTRY_IDS)


def test_serve_tree_is_base_plus_auth_and_webserver(tmp_state_home: str):
    base = compose_base(_cfg(tmp_state_home), config_path=None)
    serve = compose_serve(_cfg(tmp_state_home), config_path=None, app=SimpleNamespace())
    assert [e.id for e in serve] == [*BASE_ENTRY_IDS, *SERVE_EXTRA_IDS]
    assert [e.id for e in serve[: len(base)]] == [e.id for e in base]


def test_users_tree_is_db_only(tmp_state_home: str):
    assert [e.id for e in compose_users(_cfg(tmp_state_home))] == ["db"]


def test_base_plugins_declare_the_ordering_invariants(tmp_state_home: str):
    entries = {e.id: e for e in compose_base(_cfg(tmp_state_home), config_path=None)}
    assert entries["config"].inject == ["db"]
    assert set(entries["http"].inject) == {"config", "telemetry", "telemetryOtel"}
    assert entries["telemetry"].inject == []
    assert entries["telemetry-otel"].inject == ["config", "telemetry"]
    assert entries["telemetry-bugsink"].inject == ["config", "telemetry"]
    assert entries["telemetry-logfile"].inject == ["config", "telemetry"]
    assert entries["ai"].inject == ["config"]
    assert entries["auth"].inject == ["config"]
    assert entries["scheduler"].inject == ["config"]
    assert entries["notifications"].inject == ["config", "http"]
    assert entries["i18n"].inject == ["config"]
    assert entries["git-proxy"].inject == ["config"]


def test_disabled_entries_are_data(tmp_state_home: str):
    entries = compose_base(_cfg(tmp_state_home), config_path=None)
    toggled = [type(e)(id=e.id, plugin=e.plugin, config=e.config, inject=e.inject, disabled=True) for e in entries]
    assert all(e.disabled for e in toggled) and len(toggled) == len(entries)
