"""L2 module replacement primitive (PRFC 2026-08-31 phase 4d).

Generation-style fresh import: every reload imports the module under a new
name (``pkg@genN``); ``importlib.reload`` is banned — new class objects break
``isinstance`` and strand module singletons. Replacement swaps every fiber
of the old plugin for fibers of the new one, preserving configs; a failed
activation rolls back to the old plugin. Default-off dev capability
(``--dev-plugin-watch``); framework-surface changes still need a process
restart.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from progress.kernel.errors import BootError

if TYPE_CHECKING:
    from progress.kernel import Fiber

logger = logging.getLogger("progress.runtime.dev_reload")


class PluginReloader:
    """Generation import + fiber-level plugin replacement with rollback."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.generations = 0

    def import_generation(self, module_name: str, file_path: Path) -> Any:
        """Import ``file_path`` under a fresh generation name (never reload)."""
        import shutil  # noqa: PLC0415

        pycache = file_path.parent / "__pycache__"
        shutil.rmtree(pycache, ignore_errors=True)
        self.generations += 1
        spec = importlib.util.spec_from_file_location(f"{module_name}@gen{self.generations}", file_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def replace(self, old_plugin: Any, new_plugin: Any) -> bool:
        """Swap every fiber of ``old_plugin`` for ``new_plugin`` fibers.

        Preserves each fiber's raw config; on activation failure the new
        fibers are disposed and the old plugin remounted (rollback).
        """
        runtime = self.ctx.registry.get_or_create(old_plugin)
        fibers = [f for f in self.ctx.root_fiber.walk() if f.runtime is runtime]
        if not fibers:
            logger.warning("replace: no fibers mounted for plugin %r", old_plugin)
            return False
        configs = [f.raw_config for f in fibers]
        for fiber in fibers:
            await fiber.dispose()
        self.ctx.registry.delete(old_plugin)
        await self.ctx.root_fiber.settle_tree()

        replacements: list[Fiber] = []
        try:
            for config in configs:
                replacements.append(self.ctx.plugin(new_plugin, config))  # noqa: PERF401
            await self.ctx.root_fiber.settle_tree()
            failed = [f for f in replacements if f.state.value != "active"]
            if failed:
                raise BootError([f.diagnostics() for f in failed])
        except Exception:
            logger.exception("generation replacement failed; rolling back to previous plugin")
            for fiber in replacements:
                await fiber.dispose()
            self.ctx.registry.delete(new_plugin)
            for config in configs:
                self.ctx.plugin(old_plugin, config)
            await self.ctx.root_fiber.settle_tree()
            return False
        return True


class DevPluginWatcher:
    """Polling watcher over plugin source dirs (dev only, default off).

    Polls every ``interval`` seconds (stdlib only — no fs-event dependency;
    bind-mount inotify is unreliable anyway). On a change, the owning
    package's top-level module is generation-imported and the plugin named
    by ``attribute`` replaces its currently-mounted fibers.
    """

    def __init__(self, ctx: Any, *, attribute: str = "PLUGIN", interval: float = 1.0) -> None:
        self.ctx = ctx
        self.reloader = PluginReloader(ctx)
        self.attribute = attribute
        self.interval = interval
        self._task: asyncio.Task[None] | None = None
        self._snapshot: dict[Path, float] = {}
        self._sources: dict[Path, Path] = {}

    def watch(self, package_file: Path) -> None:
        """Register a plugin package ``__init__.py`` to watch."""
        package_file = Path(package_file)
        self._sources[package_file] = package_file
        self._snapshot[package_file] = package_file.stat().st_mtime

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:  # noqa: SIM105
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            changed = self._detect()
            for package_file in changed:
                await self._reload(package_file)

    def _detect(self) -> list[Path]:
        changed: list[Path] = []
        for package_file in list(self._sources):
            try:
                mtime = package_file.stat().st_mtime
            except OSError:
                continue
            if mtime != self._snapshot.get(package_file):
                self._snapshot[package_file] = mtime
                changed.append(package_file)
        return changed

    async def _reload(self, package_file: Path) -> None:
        module_name = package_file.parent.name
        try:
            module = self.reloader.import_generation(module_name, package_file)
            new_plugin = getattr(module, self.attribute, None)
            if new_plugin is None:
                logger.warning("dev reload: %s has no %s attribute; nothing to replace", package_file, self.attribute)
                return
            old_plugin = getattr(getattr(new_plugin, "_replaces", None), "value", None) or self._find_old(module_name)
            if old_plugin is None:
                logger.warning("dev reload: no mounted plugin found for %s", module_name)
                return
            await self.reloader.replace(old_plugin, new_plugin)
            logger.info("dev reload: replaced plugin from %s", package_file)
        except Exception:
            logger.exception("dev reload failed for %s; previous plugin kept", package_file)

    def _find_old(self, module_name: str) -> Any:
        context = self.ctx
        for fiber in context.root_fiber.walk():
            source = fiber.runtime.source
            source_module = getattr(source, "__module__", "") or ""
            if source_module.split("@")[0] == module_name:
                return source
        return None


__all__ = ["DevPluginWatcher", "PluginReloader"]
