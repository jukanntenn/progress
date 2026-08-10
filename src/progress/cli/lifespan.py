"""CLI process lifespan (spec 05).

Owns the per-process lifecycle for the CLI entry point:

1. Initialize DB (with migrations) and merge DB-stored + seed-file core config.
2. Start observability (structlog + OTel + Bugsink). **Must happen before any
   ``aiohttp.ClientSession`` is constructed** so the OTel aiohttp instrumentor
   can attach a TraceConfig (spec 04).
3. Set the active i18n locale.
4. Open one ``aiohttp.ClientSession`` for the whole run (spec 07).
5. ``yield Components`` to ``core.run``.
6. On exit: close session, shutdown observability, close DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from progress import __version__
from progress.cli.git.local import set_git_proxy
from progress.config.loader import apply_db_and_seed
from progress.config.root import CoreConfig
from progress.db import close_db, init_db
from progress.db.migrations._config_data import migrate_config_data
from progress.integrations.base import Components
from progress.observability import setup_observability, shutdown_observability
from progress.utils.http import session_factory
from progress.utils.i18n import set_locale

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(
    cfg: CoreConfig,
    *,
    component: str = "cli",
    config_path: str | None = None,
) -> AsyncIterator[Components]:
    """CLI process lifespan: DB + observability + i18n + aiohttp session."""
    await init_db(cfg.state_home)
    await migrate_config_data()
    cfg = await apply_db_and_seed(cfg, config_path)

    setup_observability(
        cfg.state_home,
        component=component,
        bugsink_dsn=cfg.observability.bugsink.dsn.get_secret_value(),
        bugsink_environment=cfg.observability.bugsink.environment,
        version=_progress_version(),
    )
    set_locale(cfg.language)

    set_git_proxy(cfg.github.proxy)

    async with session_factory(proxy=cfg.github.proxy or None) as session:
        yield Components(cfg=cfg, session=session)

    shutdown_observability()
    await close_db()


def _progress_version() -> str:

    return __version__


__all__ = ["lifespan"]
