import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import config, reports, rss


def create_app(config_obj=None) -> FastAPI:
    from ..config import Config
    from ..consts import DATABASE_PATH
    from ..db import close_db, create_tables, init_db

    if config_obj is None:
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config_obj = Config.load_from_file(config_file)

    app = FastAPI(title="Progress API")

    app.state.config = config_obj
    app.state.timezone = config_obj.get_timezone()

    db_path = os.environ.get("PROGRESS_DB_PATH", DATABASE_PATH)
    init_db(db_path)
    create_tables()

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(reports.router)
    api_router.include_router(config.router)
    api_router.include_router(rss.router)
    app.include_router(api_router)

    web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if web_dist.exists():
        assets_dir = web_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}")
        def spa_fallback(path: str):
            if "." in path.split("/")[-1]:
                file_path = web_dist / path
                if file_path.exists():
                    return FileResponse(file_path)
            return FileResponse(web_dist / "index.html")

    @app.on_event("shutdown")
    def shutdown_db():
        close_db()

    return app
