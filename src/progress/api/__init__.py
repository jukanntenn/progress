import os

from fastapi import APIRouter, FastAPI

from .routes import config, reports, rss


def create_app(config_obj=None) -> FastAPI:
    from ..config import Config
    from ..config_store import (
        build_runtime_config,
        load_app_config,
        migrate_blob_schema,
        seed_app_config_if_needed,
        seed_lists_if_needed,
    )
    from ..db import close_db, create_tables, init_db, resolve_db_path

    if config_obj is None:
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config_obj = Config.load_from_file(config_file)
    else:
        config_file = None

    app = FastAPI(title="Progress API")

    db_path = resolve_db_path(config_obj.data_dir, config_file)
    init_db(db_path)
    create_tables()

    seed_app_config_if_needed(config_obj.model_dump(mode="json"))
    migrate_blob_schema()
    seed_lists_if_needed(config_obj)
    loaded = load_app_config()
    if loaded is not None:
        blob_data, _ = loaded
        config_obj = build_runtime_config(
            blob_data,
            {
                "data_dir": config_obj.data_dir,
                "workspace_dir": config_obj.workspace_dir,
                "observability": config_obj.observability.model_dump(mode="json"),
            },
        )

    app.state.config = config_obj
    app.state.timezone = config_obj.get_timezone()

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(reports.router)
    api_router.include_router(config.router)
    api_router.include_router(rss.router)
    app.include_router(api_router)

    from ..telemetry import (
        instrument_fastapi_app,
        setup_observability,
        shutdown_observability,
    )

    setup_observability(config_obj.observability, component="api")
    instrument_fastapi_app(app)

    @app.on_event("shutdown")
    def shutdown_db():
        shutdown_observability()
        close_db()

    return app
