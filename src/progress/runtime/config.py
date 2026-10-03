"""config entry: layered config merge (DB sections + seed file) → ``ctx.config``."""

from __future__ import annotations

from progress.config.loader import apply_db_and_seed
from progress.kernel import Definition, Entry


class ConfigService(Definition):
    service_name = "config"


def make_config_entry(cfg, config_path: str | None) -> Entry:
    async def _apply(ctx, config) -> None:
        merged = await apply_db_and_seed(cfg, config_path)
        ctx.provide(ConfigService, merged)

    return Entry(id="config", plugin=_apply, inject=["db"])
