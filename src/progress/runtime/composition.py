"""Composition layers as data (PRFC phase 4a): rows, profiles, user patches.

The code-generated entries are the shipped base rows; TOML patch layers
stack on top — the shipped profile layer (``progress/runtime/profiles``),
the state-home user patch (``<state_home>/composition/user.patch.toml``),
and ``--patch`` debug overlays — and the result materializes back into
mountable entries. Rows stay structural: business configuration lives in
DB config namespaces, so patches adjust existence/``disabled``/``inject``
and structural config, not business values.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from progress.kernel import Entry, Fiber, FiberState
from progress.kernel.errors import BootError
from progress.kernel.patches import (
    Patch,
    PyExpr,
    Row,
    apply_patches,
    evaluate_disabled,
    evaluate_row_config,
    load_patch_file,
)

if TYPE_CHECKING:
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)

PROFILES = ("base", "run", "serve", "all-in-one")
_PROFILE_FILES = {"base": "base.toml", "run": "run.toml", "serve": "serve.toml", "all-in-one": "all_in_one.toml"}
_USER_PATCH = "composition/user.patch.toml"


def entries_to_rows(entries: list[Entry]) -> list[Row]:
    rows: list[Row] = []
    for entry in entries:
        plugin_inject = list(getattr(entry.plugin, "inject", []) or [])
        inject = list(dict.fromkeys([*plugin_inject, *entry.inject]))
        rows.append(
            Row(
                id=entry.id,
                plugin=entry.plugin,
                name=getattr(entry.plugin, "name", entry.id),
                config=dict(entry.config) if isinstance(entry.config, dict) else {},
                inject=inject,
                disabled=bool(entry.disabled),
            )
        )
    return rows


def rows_to_entries(rows: list[Row]) -> list[Entry]:
    entries: list[Entry] = []
    for row in rows:
        if row.plugin is None:
            logger.warning("row %r has no plugin (insert rows need a plugin registry); skipping", row.id)
            continue
        row_config = row.config or {}
        needs_wrapper = isinstance(row.disabled, PyExpr) or any(isinstance(v, PyExpr) for v in row_config.values())
        if not needs_wrapper:
            config: Any = row_config or None
            entries.append(
                Entry(id=row.id, plugin=row.plugin, config=config, inject=row.inject, disabled=row.disabled is True)
            )
            continue
        entries.append(Entry(id=row.id, plugin=_expression_wrapper(row), inject=row.inject))
    return entries


def _expression_wrapper(row: Row) -> Any:
    """Evaluate ``disabled``/config expressions inside apply — after injects."""

    async def _apply(ctx: Any, config: Any) -> None:
        if evaluate_disabled(row, ctx):
            logger.info("row %r pruned by disabled expression", row.id)
            return
        evaluated = evaluate_row_config(row, ctx)
        plugin = row.plugin
        result = plugin(ctx, evaluated or None)
        if hasattr(result, "__await__"):
            await result

    return {"apply": _apply, "inject": row.inject, "name": row.name or row.id}


def shipped_profile_layer(profile: str) -> list[Patch]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    path = Path(__file__).parent / "profiles" / _PROFILE_FILES[profile]
    if not path.exists():
        return []
    return load_patch_file(path)


def user_patch_layer(cfg: CoreConfig | None) -> list[Patch]:
    if cfg is None:
        return []
    path = Path(cfg.state_home) / _USER_PATCH
    if not path.exists():
        return []
    return load_patch_file(path)


def effective_rows(
    base_entries: list[Entry],
    *,
    profile: str,
    cfg: CoreConfig | None = None,
    extra_patches: list[Patch] | None = None,
) -> list[Row]:
    """Compose the effective rows: code base → profile → user patch → overlays."""
    rows = entries_to_rows(base_entries)
    layers: list[list[Patch]] = [shipped_profile_layer(profile), user_patch_layer(cfg)]
    if extra_patches:
        layers.append(extra_patches)
    for layer in layers:
        rows = apply_patches(rows, layer)
    return rows


__all__ = [
    "PROFILES",
    "Composer",
    "effective_rows",
    "entries_to_rows",
    "rows_to_entries",
    "shipped_profile_layer",
    "user_patch_layer",
]


class Composer:
    """Live composition driver for a running tree: L0 config reload, L1 diff.

    L0 (``reload_config``): re-merge the layered config, swap the value
    inside the ``config`` implementation in place, restart every fiber that
    injects ``config`` (row-precise: fibers that inject no volatile section
    stay untouched), and re-evaluate ``_py`` rows whose disabled/config
    changed — channel or language edits take effect live.

    L1 (``recompose``): re-read the patch layers, then a transactional diff —
    create all new rows first, remove stale rows after, roll the whole batch
    back if any created row fails to activate.
    """

    def __init__(
        self,
        ctx: Any,
        *,
        profile: str,
        cfg: Any,
        base_entries_factory: Any,
    ) -> None:
        self.ctx = ctx
        self.profile = profile
        self.cfg = cfg
        self.base_entries_factory = base_entries_factory
        self.mounted: dict[str, Fiber] = {}
        self._rows_by_id: dict[str, Row] = {}

    def rows(self) -> list[Row]:
        return effective_rows(self.base_entries_factory(), profile=self.profile, cfg=self.cfg)

    async def mount_initial(self, rows: list[Row] | None = None) -> None:
        mounted_rows = rows if rows is not None else self.rows()
        for row in mounted_rows:
            entry = _single_entry(row)
            if entry is None or entry.disabled:
                continue
            self.mounted[row.id] = self._mount(entry)
        await self.ctx.fiber.settle_tree()
        _assert_active(list(self.mounted.values()))
        self._rows_by_id = {row.id: row for row in mounted_rows}

    async def reload_config(self) -> bool:
        """L0: re-merge + restart config-injecting fibers + re-evaluate _py rows."""
        from progress.config.loader import apply_db_and_seed, load_config  # noqa: PLC0415

        fresh = load_config(self._config_path()) if self._config_path() else self.cfg
        merged = await apply_db_and_seed(fresh, self._config_path())
        self.cfg = fresh
        self.ctx.reflect.replace(self.ctx.isolate_chain, "config", merged)

        restarted = False
        for fiber in list(self.mounted.values()):
            if "config" in fiber.runtime.inject:
                await fiber.update(fiber.raw_config)
                restarted = True
        await self.ctx.fiber.settle_tree()
        return restarted

    async def recompose(self) -> list[str]:
        """L1: transactional diff over the current patch layers."""
        new_rows = [r for r in self.rows() if r.disabled is not True]
        new_by_id = {r.id: r for r in new_rows}
        created: list[tuple[str, Fiber]] = []
        changed: list[str] = []
        try:
            for row in new_rows:
                entry = _single_entry(row)
                if entry is None:
                    continue
                if row.id not in self.mounted:
                    created.append((row.id, self._mount(entry)))
                elif _row_changed(self._rows_by_id.get(row.id), row):
                    changed.append(row.id)
            await self.ctx.fiber.settle_tree()
            _assert_active([f for _, f in created])
        except BootError:
            for _, fiber in created:
                await fiber.dispose()
            await self.ctx.fiber.settle_tree()
            raise
        for row_id in changed:
            fiber = self.mounted.get(row_id)
            if fiber is not None:
                await fiber.update(fiber.raw_config)
        stale = [row_id for row_id in self.mounted if row_id not in new_by_id]
        for row_id in stale:
            await self.mounted[row_id].dispose()
            del self.mounted[row_id]
        self._rows_by_id = new_by_id
        await self.ctx.fiber.settle_tree()
        return [row_id for row_id, _ in created]

    def _mount(self, entry: Entry) -> Fiber:
        plugin = entry.plugin
        extra = entry.inject
        runtime_inject = list(getattr(plugin, "inject", []) or [])
        if extra:
            plugin = _WithExtraInject(plugin, [*runtime_inject, *extra])
        fiber = self.ctx.plugin(plugin, entry.config, name=entry.id)
        return fiber  # noqa: RET504

    def _config_path(self) -> str | None:
        return getattr(self, "_config_path_value", None)

    def set_config_path(self, config_path: str | None) -> None:
        self._config_path_value = config_path

    async def dispose(self) -> None:
        await self.ctx.fiber.dispose()


class _WithExtraInject:
    """Re-declare a plugin with additional injects (mount-time composition)."""

    def __init__(self, plugin: Any, inject: list[str]) -> None:
        self._plugin = plugin
        self.inject = list(dict.fromkeys(inject))
        self.name = getattr(plugin, "name", None)
        self.apply = getattr(plugin, "apply", None) if not callable(plugin) or isinstance(plugin, type) else None

    def __call__(self, ctx: Any, config: Any) -> Any:
        return self._plugin(ctx, config)


def _single_entry(row: Row) -> Entry | None:
    entries = rows_to_entries([row])
    return entries[0] if entries else None


def _row_changed(old: Row | None, new: Row) -> bool:
    if old is None:
        return True
    return (old.disabled != new.disabled) or (old.config != new.config) or (old.inject != new.inject)


def _assert_active(fibers: list[Fiber]) -> None:
    diagnostics = [f.diagnostics() for f in fibers if f.state != FiberState.ACTIVE]
    if diagnostics:
        raise BootError(diagnostics)
