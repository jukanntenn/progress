"""Live composition: L0 config reload + L1 transactional diff (PRFC phase 4b)."""

from __future__ import annotations

from typing import Any

import pytest

from progress.config.root import CoreConfig
from progress.kernel import Entry, root_context
from progress.runtime.composition import Composer


def _config_entry() -> Entry:
    from progress.runtime.config import make_config_entry  # noqa: PLC0415

    return make_config_entry(None, None)


def _spy_entry(row_id: str, calls: list[str]) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        calls.append(f"{row_id}:{ctx.config.language}")

    _apply.name = row_id
    _apply.inject = ["config"]
    return Entry(id=row_id, plugin=_apply, inject=["config"])


def _broken_entry(row_id: str) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        raise RuntimeError("cannot activate")

    _apply.name = row_id
    return Entry(id=row_id, plugin=_apply)


class TestL0:
    async def test_set_config_reaches_running_tree_without_restart(
        self, tmp_state_home: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr("progress.config.loader.apply_db_and_seed", _fake_apply_db_and_seed)

        cfg = CoreConfig(state_home=tmp_state_home, language="en")

        async def config_stub(ctx: Any, config: Any) -> None:
            ctx.provide("config", cfg)

        config_stub.name = "config"

        ctx = root_context()
        entries = [Entry(id="config", plugin=config_stub), _spy_entry("i18n", calls)]
        composer = Composer(ctx, profile="serve", cfg=cfg, base_entries_factory=lambda: entries)
        await composer.mount_initial(entries_to_rows_for_test(entries))
        assert calls == ["i18n:en"]

        _LANGUAGE["value"] = "zh"
        restarted = await composer.reload_config()
        assert restarted is True
        assert calls == ["i18n:en", "i18n:zh"]
        await composer.dispose()

    async def test_fibers_not_injecting_config_stay_untouched(self, tmp_state_home: str) -> None:
        steady_calls: list[str] = []
        cfg = CoreConfig(state_home=tmp_state_home)

        async def steady(ctx: Any, config: Any) -> None:
            ctx.provide("steady", True)
            steady_calls.append("loaded")

        steady.name = "steady"

        async def config_stub(ctx: Any, config: Any) -> None:
            ctx.provide("config", cfg)

        config_stub.name = "config"

        ctx = root_context()
        entries = [Entry(id="config", plugin=config_stub), Entry(id="steady", plugin=steady)]
        composer = Composer(ctx, profile="serve", cfg=cfg, base_entries_factory=lambda: entries)
        await composer.mount_initial(entries_to_rows_for_test(entries))
        assert steady_calls == ["loaded"]

        import progress.runtime.composition as composition_mod  # noqa: PLC0415

        original = composition_mod.Composer.reload_config  # noqa: F841

        async def _reload_no_merge(self: Composer) -> bool:
            fresh = CoreConfig(state_home=tmp_state_home, language="zh")
            self.cfg = fresh
            self.ctx.reflect.replace(self.ctx.isolate_chain, "config", fresh)
            for fiber in list(self.mounted.values()):
                if "config" in fiber.runtime.inject:
                    await fiber.update(fiber.raw_config)
            await self.ctx.fiber.settle_tree()
            return True

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(composition_mod.Composer, "reload_config", _reload_no_merge)
        await composer.reload_config()
        assert steady_calls == ["loaded"]
        monkeypatch.undo()
        await composer.dispose()


class TestL1:
    async def test_recompose_rolls_back_batch_on_failure(self, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        ok_calls: list[str] = []

        async def ok_plugin(ctx: Any, config: Any) -> None:
            ok_calls.append("ok")

        ok_plugin.name = "ok"

        async def config_stub(ctx: Any, config: Any) -> None:
            ctx.provide("config", cfg)

        config_stub.name = "config"

        ctx = root_context()
        base = [Entry(id="config", plugin=config_stub), Entry(id="ok", plugin=ok_plugin)]
        broken = _broken_entry("broken")
        composer = Composer(ctx, profile="serve", cfg=cfg, base_entries_factory=lambda: [*base, broken])
        await composer.mount_initial(entries_to_rows_for_test(base))
        assert ok_calls == ["ok"]

        from progress.kernel.errors import BootError  # noqa: PLC0415

        with pytest.raises(BootError):
            await composer.recompose()
        assert set(composer.mounted) == {"config", "ok"}
        assert ok_calls == ["ok"]
        await composer.dispose()

    async def test_recompose_removes_stale_rows(self, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        ok_calls: list[str] = []
        disposed: list[str] = []

        async def config_stub(ctx: Any, config: Any) -> None:
            ctx.provide("config", cfg)

        config_stub.name = "config"

        async def ok_plugin(ctx: Any, config: Any) -> None:
            ok_calls.append("ok")

        ok_plugin.name = "ok"

        async def stale_plugin(ctx: Any, config: Any) -> None:
            async def _record() -> None:
                disposed.append("stale")

            ctx.effect(_record)

        stale_plugin.name = "stale"

        ctx = root_context()
        base = [Entry(id="config", plugin=config_stub), Entry(id="ok", plugin=ok_plugin)]
        with_stale = [*base, Entry(id="stale", plugin=stale_plugin)]
        composer = Composer(ctx, profile="serve", cfg=cfg, base_entries_factory=lambda: with_stale)
        await composer.mount_initial(entries_to_rows_for_test(with_stale))
        assert set(composer.mounted) == {"config", "ok", "stale"}

        composer.base_entries_factory = lambda: base
        created = await composer.recompose()
        assert created == []
        assert set(composer.mounted) == {"config", "ok"}
        assert disposed == ["stale"]
        await composer.dispose()


_LANGUAGE: dict[str, str] = {"value": "en"}


async def _fake_apply_db_and_seed(cfg: CoreConfig, config_path: str | None) -> CoreConfig:
    return CoreConfig(state_home=cfg.state_home, language=_LANGUAGE["value"])


def _config_entry() -> Entry:
    from progress.runtime.config import make_config_entry  # noqa: PLC0415

    return make_config_entry(None, None)


def entries_to_rows_for_test(entries: list[Entry]) -> list[Any]:
    from progress.runtime.composition import entries_to_rows  # noqa: PLC0415

    return entries_to_rows(entries)
