"""db entry: Tortoise connection lifecycle + config-data repairs → ``ctx.db``."""

from __future__ import annotations

from dataclasses import dataclass

from progress.db import close_db, init_db
from progress.db.migrations._config_data import migrate_config_data
from progress.kernel import Definition, Entry


class DbService(Definition):
    service_name = "db"


@dataclass
class DbHandle:
    """The connection-lifecycle service value; Tortoise state is process-global."""

    state_home: str


def make_db_entry(cfg) -> Entry:
    state_home = cfg.state_home

    async def _apply(ctx, config) -> None:
        await init_db(state_home)
        await migrate_config_data()
        ctx.provide(DbService, DbHandle(state_home=state_home))
        ctx.effect(close_db)

    return Entry(id="db", plugin=_apply)
