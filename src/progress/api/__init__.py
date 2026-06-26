import os

from fastapi import APIRouter, FastAPI

from .routes import config, reports, rss


def create_app(config_obj=None) -> FastAPI:
    from ..config import Config
    from ..db import close_db, create_tables, init_db, resolve_db_path

    if config_obj is None:
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config_obj = Config.load_from_file(config_file)
    else:
        config_file = None

    app = FastAPI(title="Progress API")

    app.state.config = config_obj
    app.state.timezone = config_obj.get_timezone()

    db_path = resolve_db_path(config_obj.data_dir, config_file)
    init_db(db_path)
    create_tables()

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(reports.router)
    api_router.include_router(config.router)
    api_router.include_router(rss.router)
    app.include_router(api_router)

    @app.on_event("shutdown")
    def shutdown_db():
        close_db()

    return app
