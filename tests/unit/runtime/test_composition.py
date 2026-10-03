"""Composition data layer (PRFC phase 4a): user patches, deferred disable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from progress.config.root import CoreConfig
from progress.kernel import Entry, boot
from progress.kernel.patches import PyExpr, Row
from progress.runtime.composition import effective_rows, rows_to_entries


def _config_entry(cfg: CoreConfig) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        ctx.provide("config", cfg)

    _apply.name = "stub-config"
    return Entry(id="config", plugin=_apply)


def test_user_patch_layer_statically_disables_a_row(tmp_state_home: str):
    cfg = CoreConfig(state_home=tmp_state_home)
    patch_dir = Path(tmp_state_home) / "composition"
    patch_dir.mkdir(parents=True)
    (patch_dir / "user.patch.toml").write_text('[[patch]]\ntarget = "git-proxy"\ndisabled = true\n', encoding="utf-8")

    rows = effective_rows([_config_entry(cfg), _git_proxy_entry()], profile="run", cfg=cfg)
    assert next(r for r in rows if r.id == "git-proxy").disabled is True

    entries = rows_to_entries(rows)
    disabled = [e for e in entries if e.id == "git-proxy"]
    assert disabled and disabled[0].disabled is True


def test_unknown_profile_rejected():
    import pytest  # noqa: PLC0415

    with pytest.raises(ValueError):
        effective_rows([], profile="nope", cfg=None)


def test_deferred_disabled_expression_evaluates_after_injection(tmp_state_home: str):
    events: list[str] = []
    cfg = CoreConfig(state_home=tmp_state_home)

    row = Row(
        id="probed",
        name="probed",
        disabled=PyExpr("bool(ctx.config)"),
        inject=[],
    )

    async def probe_plugin(ctx: Any, config: Any) -> None:
        events.append("mounted")

    row.plugin = probe_plugin
    entries = rows_to_entries([_config_entry(cfg), row])

    async def _drive() -> None:
        async with boot(entries) as ctx:
            assert ctx.get("config") is cfg

    import asyncio  # noqa: PLC0415

    asyncio.run(_drive())
    assert events == []  # disabled expression (config present) pruned the row


def test_deferred_disabled_expression_false_mounts_row(tmp_state_home: str):
    events: list[str] = []
    cfg = CoreConfig(state_home=tmp_state_home)

    async def probe_plugin(ctx: Any, config: Any) -> None:
        events.append("mounted")
        ctx.provide("probe", True)

    row = Row(
        id="probed",
        name="probed",
        disabled=PyExpr("not bool(ctx.config)"),
        plugin=probe_plugin,
    )
    entries = rows_to_entries([_config_entry(cfg), row])

    async def _drive() -> None:
        async with boot(entries) as ctx:
            assert ctx.get("probe") is True

    import asyncio  # noqa: PLC0415

    asyncio.run(_drive())
    assert events == ["mounted"]


def _git_proxy_entry() -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        return None

    _apply.name = "git-proxy"
    return Entry(id="git-proxy", plugin=_apply)
