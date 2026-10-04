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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
import logging
import os
from typing import Any

from fastapi import FastAPI
import sentry_sdk

from progress import __version__
from progress.api.errors import register_exception_handlers
from progress.api.middleware import register_middleware
from progress.api.routes import register_routers
from progress.config.loader import load_config
from progress.kernel import root_context
from progress.runtime import compose_serve
from progress.runtime.composition import Composer
from progress.runtime.plugin_install import ensure_plugin_path

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


def _install_sighup(composer: Any) -> None:
    """L1 explicit trigger: SIGHUP recomposes the running tree."""
    import asyncio  # noqa: PLC0415
    import signal  # noqa: PLC0415

    loop = asyncio.get_running_loop()

    async def _recompose() -> None:
        try:
            await composer.recompose()
        except Exception:
            logging.getLogger(__name__).exception("SIGHUP recompose failed; tree unchanged")

    def _on_signal() -> None:
        loop.create_task(_recompose())  # noqa: RUF006

    try:  # noqa: SIM105
        loop.add_signal_handler(signal.SIGHUP, _on_signal)
    except NotImplementedError:
        pass


def _maybe_dev_plugin_watch(ctx: Any, cfg: Any) -> Any:
    """L2 (default off): watch third-party plugin sources and hot-replace.

    Enabled by ``PROGRESS_DEV_PLUGIN_WATCH=1`` (the serve command sets it
    from ``--dev-plugin-watch``); watches plugin packages under
    ``<state_home>/plugins``.
    """
    if os.environ.get("PROGRESS_DEV_PLUGIN_WATCH", "").strip() not in {"1", "true", "yes"}:
        return None
    from progress.runtime.dev_reload import DevPluginWatcher  # noqa: PLC0415
    from progress.runtime.plugin_install import plugins_dir  # noqa: PLC0415

    watcher = DevPluginWatcher(ctx)
    for package in sorted(plugins_dir(cfg.state_home).glob("*/__init__.py")):
        watcher.watch(package)
    watcher.start()
    logging.getLogger(__name__).info("dev plugin watch armed over %s", plugins_dir(cfg.state_home))
    return watcher


def _remove_sighup() -> None:
    import signal  # noqa: PLC0415

    try:  # noqa: SIM105
        asyncio.get_running_loop().remove_signal_handler(signal.SIGHUP)
    except (NotImplementedError, RuntimeError):
        pass


def _dev_cors_enabled() -> bool:
    """CORS is dev-only (spec 12). Toggled by ``PROGRESS_DEV_CORS=1``."""
    return os.environ.get(DEV_CORS_ENV, "").strip() in {"1", "true", "yes"}


def _progress_version() -> str:

    return __version__


def _lifespan_factory(config_path: str | None):
    """Build a lifespan that boots the shared composition tree.

    The ASGI protocol requires a lifespan callable; this shim is the only
    thing left of the old hand-written startup sequence — ordering knowledge
    lives in ``progress.runtime.compose_serve`` and is expressed as service
    dependencies.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            cfg = load_config(config_path)
            ensure_plugin_path(cfg.state_home)
            ctx = root_context()
            composer = Composer(
                ctx,
                profile="serve",
                cfg=cfg,
                base_entries_factory=lambda: compose_serve(cfg, config_path=config_path, app=app),
            )
            composer.set_config_path(config_path)
            await composer.mount_initial()
            app.state.ctx = ctx
            app.state.composer = composer
            _install_sighup(composer)
            watcher = _maybe_dev_plugin_watch(ctx, cfg)
            try:
                yield
            finally:
                if watcher is not None:
                    await watcher.stop()
                _remove_sighup()
                await composer.dispose()
        except Exception as e:
            logger.exception("api lifespan startup failed")
            with suppress(Exception):
                sentry_sdk.capture_exception(e)
            raise

    return _lifespan


__all__ = ["create_app"]
