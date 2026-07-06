import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifespan: initialize DB, seed config, and tear down on exit.

    DB init/seeding runs here (inside the running event loop) so tortoise-orm
    binds its connections to the serving loop. The prior code did this work
    eagerly at app construction; the observable ordering is preserved — the DB
    is ready before any request is served, and closed on shutdown.
    """
    from ..config import Config
    from ..config_store import (
        build_runtime_config,
        load_app_config,
        migrate_blob_schema,
        seed_app_config_if_needed,
        seed_lists_if_needed,
    )
    from ..db import close_db, create_tables, init_db, resolve_db_path
    from ..telemetry import setup_observability

    config_obj = app.state.config
    config_file = app.state.config_file
    db_path = resolve_db_path(config_obj.data_dir, config_file)
    await init_db(db_path)
    await create_tables()
    await seed_app_config_if_needed(config_obj.model_dump(mode="json"))
    await migrate_blob_schema()
    await seed_lists_if_needed(config_obj)
    loaded = await load_app_config()
    if loaded is not None:
        blob_data, _ = loaded
        app.state.config = build_runtime_config(
            blob_data,
            {
                "data_dir": config_obj.data_dir,
                "workspace_dir": config_obj.workspace_dir,
                "observability": config_obj.observability.model_dump(mode="json"),
            },
        )
        app.state.timezone = app.state.config.get_timezone()

    setup_observability(config_obj.observability, component="api")

    try:
        yield
    finally:
        from ..telemetry import shutdown_observability

        shutdown_observability()
        await close_db()


def create_app(config_obj=None) -> FastAPI:
    """Build the FastAPI app.

    DB initialization and config seeding run in the lifespan (on startup),
    preserving the prior behavior where they completed before the first
    request. The app object itself is constructed synchronously here; the
    ``config_obj`` is stashed on ``app.state`` for the lifespan to consume.
    """
    from ..config import Config
    from ..telemetry import instrument_fastapi_app

    if config_obj is None:
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config_obj = Config.load_from_file(config_file)
    else:
        config_file = None

    app = FastAPI(title="Progress API", lifespan=_lifespan)
    app.state.config = config_obj
    app.state.config_file = config_file
    app.state.timezone = config_obj.get_timezone()

    api_router = APIRouter(prefix="/api/v1")
    from .routes import config, reports, rss

    api_router.include_router(reports.router)
    api_router.include_router(config.router)
    api_router.include_router(rss.router)
    app.include_router(api_router)

    instrument_fastapi_app(app)

    return app
