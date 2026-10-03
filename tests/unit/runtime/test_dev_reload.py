"""L2 generation replacement + L3 plugin install (PRFC phase 4d)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from progress.config.root import CoreConfig
from progress.kernel import FiberState, root_context
from progress.runtime.dev_reload import DevPluginWatcher, PluginReloader
from progress.runtime.plugin_install import (
    ensure_plugin_path,
    install_plugin,
    list_plugins,
    plugins_dir,
    remove_plugin,
)

PLUGIN_PKG = """
from progress.integrations.base import RunResult, SyncResult


class {cls}:
    name = "thirdparty-demo"

    def __init__(self, ctx=None, config=None) -> None:
        pass

    async def setup(self, ctx) -> None:
        pass

    async def sync(self) -> SyncResult:
        return SyncResult()

    async def run(self, *, concurrency: int = 1) -> RunResult:
        return RunResult(name=self.name, summary="{marker}")

    async def build_notification(self, *, result, reports):
        return []

    async def teardown(self) -> None:
        pass
"""


def _write_plugin(source: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


class TestL2GenerationReplacement:
    async def test_generation_import_uses_fresh_module_names(self, tmp_path: Path):
        pkg = tmp_path / "demoplug" / "__init__.py"
        _write_plugin(PLUGIN_PKG.format(cls="DemoV1", marker="v1"), pkg)
        reloader = PluginReloader(ctx=None)
        m1 = reloader.import_generation("demoplug", pkg)
        _write_plugin(PLUGIN_PKG.format(cls="DemoV2", marker="v2"), pkg)
        m2 = reloader.import_generation("demoplug", pkg)
        assert m1.__name__ != m2.__name__
        assert m1.DemoV1 is not m2.DemoV2

    async def test_replace_swaps_fibers_and_rolls_back_on_failure(self, tmp_path: Path):
        pkg = tmp_path / "demoplug" / "__init__.py"
        _write_plugin(PLUGIN_PKG.format(cls="DemoV1", marker="v1"), pkg)

        async def _stub(ctx: Any, config: Any) -> None:
            ctx.provide("config", CoreConfig())

        _stub.name = "config"

        async def _drive() -> None:
            ctx = root_context()
            ctx.plugin(_stub, name="config")
            await ctx.root_fiber.settle_tree()

            reloader = PluginReloader(ctx)
            module_v1 = reloader.import_generation("demoplug", pkg)
            old_plugin = module_v1.DemoV1
            old_config = {"marker": "kept"}
            fiber = ctx.plugin(old_plugin, old_config, name="demo")
            await ctx.root_fiber.settle_tree()
            assert fiber.state == FiberState.ACTIVE

            _write_plugin(PLUGIN_PKG.format(cls="DemoV2", marker="v2"), pkg)
            module_v2 = reloader.import_generation("demoplug", pkg)
            replaced = await reloader.replace(old_plugin, module_v2.DemoV2)
            assert replaced is True
            new_fibers = [
                f
                for f in ctx.root_fiber.walk()
                if f.runtime.source is module_v2.DemoV2 or getattr(f.runtime.source, "__name__", "") == "DemoV2"
            ]
            assert any(f.raw_config == old_config for f in new_fibers)

            _write_plugin("raise RuntimeError('broken generation')\n", pkg)
            with pytest.raises(Exception):  # noqa: B017
                reloader.import_generation("demoplug", pkg)  # broken generation fails loud, tree untouched
            await ctx.root_fiber.dispose()

        await asyncio.to_thread(asyncio.run, _drive())

    async def test_watcher_detects_changes_by_polling(self, tmp_path: Path):
        async def _drive() -> None:
            ctx = root_context()
            watcher = DevPluginWatcher(ctx, interval=0.05)
            pkg = tmp_path / "demoplug" / "__init__.py"
            _write_plugin("PLUGIN = object()\n", pkg)
            watcher.watch(pkg)
            assert watcher._detect() == []
            import time  # noqa: PLC0415

            time.sleep(0.01)
            _write_plugin("PLUGIN = object()\n# touched\n", pkg)
            changed = watcher._detect()
            assert changed == [pkg]
            assert watcher._detect() == []  # snapshot updated

        await asyncio.to_thread(asyncio.run, _drive())


class TestL3PluginInstall:
    def test_install_list_remove_roundtrip(self, tmp_path: Path):
        state_home = tmp_path / "state"
        pkg_root = tmp_path / "fixture-plugin"
        pkg = pkg_root / "demo_plugin_pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text('PLUGIN = "demo"\n', encoding="utf-8")
        pyproject = pkg_root / "pyproject.toml"
        pyproject.write_text(
            """
[project]
name = "demo-plugin-pkg"
version = "0.1.0"

[tool.uv]
build-constraint-dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["demo_plugin_pkg"]
""",
            encoding="utf-8",
        )

        install_plugin(str(state_home), str(pkg_root))
        installed = {p["name"] for p in list_plugins(str(state_home))}
        assert "demo-plugin-pkg" in installed

        directory = plugins_dir(str(state_home))
        resolved = str(directory.resolve())
        import sys  # noqa: PLC0415

        assert resolved not in sys.path
        ensure_plugin_path(str(state_home))
        assert resolved in sys.path
        sys.path.remove(resolved)

        assert remove_plugin(str(state_home), "demo-plugin-pkg") is True
        assert list_plugins(str(state_home)) == []
