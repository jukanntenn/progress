"""FastAPI app factory + lifespan + middleware registration (spec 12).

The api package is the symmetric HTTP entry point alongside ``cli/``. It is
**self-contained**: lifespan owns DB / observability / aiohttp session; no
application-layer auth (per spec 12, network boundary is trusted).

``create_app(config_path)`` is the only public entry; ``api/main.py`` calls it
at ASGI load time. Importing this module does NOT construct the app — that
fixes the legacy bug where ``main.py:3 app = create_app()`` would raise at
import time when the config file was missing or invalid.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
import logging
import os

import aiohttp
from fastapi import FastAPI
import sentry_sdk

from progress import __version__
from progress.api.auth_bootstrap import bootstrap_auth
from progress.api.errors import register_exception_handlers
from progress.api.middleware import register_middleware
from progress.api.routes import register_routers
from progress.cli.git.local import set_git_proxy
from progress.config.loader import apply_db_and_seed, load_config
from progress.config.root import CoreConfig
from progress.db import close_db, init_db
from progress.db.migrations._config_data import migrate_config_data
from progress.observability import (
    instrument_fastapi_app,
    setup_observability,
    shutdown_observability,
)
from progress.utils.http import session_factory

logger = logging.getLogger(__name__)

DEV_CORS_ENV = "PROGRESS_DEV_CORS"
CONFIG_PATH_ENV = "PROGRESS_CONFIG"


def _config_path_from_env() -> str | None:
    """The Ansible-class config path handed to a uvicorn worker process.

    ``progress serve`` runs uvicorn by import string
    (``uvicorn.run("progress.api.main:app")``), so the worker is a fresh
    process that re-imports ``main.py`` and calls ``create_app()`` with no
    arguments. The ``-c`` value from the serve command would otherwise be
    lost and the app would fall back to the zero-config default
    ``state_home="data"``. The serve command exports it through this env var
    so the worker reconstructs the same app.
    """
    value = os.environ.get(CONFIG_PATH_ENV, "").strip()
    return value or None


def create_app(config_path: str | None = None) -> FastAPI:
    """Build a FastAPI app. Construction is deferred — no import-time crashes.

    The app's lifespan wires up DB / observability / aiohttp session in the
    right order (spec 12): observability BEFORE the aiohttp session so OTel's
    aiohttp instrumentor attaches a TraceConfig to the session.

    ``config_path`` defaults to the ``PROGRESS_CONFIG`` env var so the
    ``progress serve`` uvicorn worker picks up the ``-c`` value from the
    command line (the worker re-imports ``main.py`` and cannot receive the
    arg directly).
    """
    if config_path is None:
        config_path = _config_path_from_env()
    app = FastAPI(
        title="Progress API",
        description="GitHub multi-repo project tracking tool.",
        version=_progress_version(),
        lifespan=_lifespan_factory(config_path),
    )
    register_middleware(app, dev_cors=_dev_cors_enabled())
    register_exception_handlers(app)
    register_routers(app)
    return app


def _dev_cors_enabled() -> bool:
    """CORS is dev-only (spec 12). Toggled by ``PROGRESS_DEV_CORS=1``."""
    return os.environ.get(DEV_CORS_ENV, "").strip() in {"1", "true", "yes"}


def _progress_version() -> str:

    return __version__


def _lifespan_factory(config_path: str | None):
    """Build a lifespan that closes over ``config_path``."""

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg: CoreConfig | None = None
        session: aiohttp.ClientSession | None = None
        try:
            cfg = load_config(config_path)
            await init_db(cfg.state_home)
            await migrate_config_data()
            cfg = await apply_db_and_seed(cfg, config_path)

            cfg = await bootstrap_auth(cfg)
            setup_observability(
                cfg.state_home,
                component="api",
                bugsink_dsn=cfg.observability.bugsink.dsn.get_secret_value(),
                bugsink_environment=cfg.observability.bugsink.environment,
                version=_progress_version(),
            )
            instrument_fastapi_app(app)
            app.state.cfg = cfg

            set_git_proxy(cfg.github.proxy)
            session_ctx = session_factory(proxy=cfg.github.proxy or None)
            session = await session_ctx.__aenter__()
            app.state.session = session
            app.state.session_ctx = session_ctx
        except Exception as e:
            logger.exception("api lifespan startup failed")
            with suppress(Exception):
                sentry_sdk.capture_exception(e)
            if session is not None:
                await session.close()
            await close_db()
            raise
        try:
            yield
        finally:
            if session is not None:
                try:
                    await app.state.session_ctx.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning("api session close failed: %s", e)
            shutdown_observability()
            await close_db()

    return _lifespan


__all__ = ["create_app"]
