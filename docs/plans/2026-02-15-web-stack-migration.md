# Web Stack Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate from Flask + Jinja2 templates to FastAPI + React (Vite + shadcn/ui + Tailwind CSS + pnpm) with hot reload support.

**Architecture:** FastAPI backend serves API endpoints at `/api/v1/*` and static frontend assets. React frontend built with Vite, proxied to FastAPI during development. Single deployment model.

**Tech Stack:** FastAPI, uvicorn, React 18, TypeScript, Vite 5, shadcn/ui, Tailwind CSS 3, pnpm, SWR, React Router 6

---

## Phase 1: Backend Migration (FastAPI)

### Task 1: Update Python Dependencies

**Files:**
- Modify: `pyproject.toml:6-23`

**Step 1: Add FastAPI dependencies**

Replace Flask/Gunicorn with FastAPI/Uvicorn in `pyproject.toml`:

```toml
dependencies = [
    "click>=8.3.1",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "feedgen>=0.9.0",
    "jinja2>=3.1.0",
    "markdown-it-py>=3.0.0",
    "peewee>=3.18.3",
    "requests>=2.32.5",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
    "mdit-py-plugins>=0.4.0",
    "tomlkit>=0.13.0",
    "gitpython>=3.1.46",
    "PyGithub>=2.8.1",
    "pytz>=2024.1",
    "urllib3>=2.6.3",
]
```

**Step 2: Run uv sync**

```bash
uv sync
```

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: replace flask/gunicorn with fastapi/uvicorn"
```

---

### Task 2: Create FastAPI Application

**Files:**
- Create: `src/progress/api.py`
- Create: `src/progress/api/__init__.py`
- Create: `src/progress/api/routes/__init__.py`
- Create: `src/progress/api/routes/reports.py`
- Create: `src/progress/api/routes/config.py`
- Create: `src/progress/api/routes/rss.py`

**Step 1: Create API package structure**

```bash
mkdir -p src/progress/api/routes
touch src/progress/api/__init__.py
touch src/progress/api/routes/__init__.py
```

**Step 2: Write reports route**

Create `src/progress/api/routes/reports.py`:

```python
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...consts import DATABASE_PATH
from ...db import create_tables, init_db
from ...db.models import Report

router = APIRouter(prefix="/reports", tags=["reports"])

PAGE_SIZE = 50


class ReportResponse(BaseModel):
    id: int
    title: str | None
    created_at: str
    markpost_url: str | None


class ReportDetailResponse(BaseModel):
    id: int
    title: str | None
    created_at: str
    markpost_url: str | None
    content: str


class PaginatedReportsResponse(BaseModel):
    reports: list[ReportResponse]
    page: int
    total_pages: int
    total: int
    has_prev: bool
    has_next: bool


def format_datetime(dt, timezone) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt)
            return parsed.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return dt
    return str(dt)


@router.get("", response_model=PaginatedReportsResponse)
def list_reports(page: int = 1, timezone_str: str = "UTC"):
    import pytz
    timezone = pytz.timezone(timezone_str)

    if page < 1:
        page = 1

    query = (
        Report.select().where(Report.repo.is_null()).order_by(Report.created_at.desc())
    )

    total = query.count()
    reports = list(query.paginate(page, PAGE_SIZE))

    report_list = []
    for report in reports:
        report_list.append(
            ReportResponse(
                id=report.id,
                title=report.title,
                created_at=format_datetime(report.created_at, timezone),
                markpost_url=report.markpost_url,
            )
        )

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE or 1

    return PaginatedReportsResponse(
        reports=report_list,
        page=page,
        total_pages=total_pages,
        total=total,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(report_id: int, timezone_str: str = "UTC"):
    import pytz
    timezone = pytz.timezone(timezone_str)

    report = Report.get_or_none(Report.id == report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.repo is not None:
        raise HTTPException(status_code=404, detail="Report not found")

    return ReportDetailResponse(
        id=report.id,
        title=report.title,
        created_at=format_datetime(report.created_at, timezone),
        markpost_url=report.markpost_url,
        content=report.content or "",
    )
```

**Step 3: Write config route**

Create `src/progress/api/routes/config.py`:

```python
import os
import shutil
from pathlib import Path

import pytz
import tomlkit
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...errors import ConfigException

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    success: bool = True
    data: dict
    toml: str
    path: str
    comments: dict


class ConfigSaveRequest(BaseModel):
    toml: str | None = None
    config: dict | None = None


class ConfigSaveResponse(BaseModel):
    success: bool
    message: str | None = None
    toml: str | None = None
    error: str | None = None


class ConfigValidateRequest(BaseModel):
    toml: str


class ConfigValidateResponse(BaseModel):
    success: bool
    message: str | None = None
    data: dict | None = None
    error: str | None = None


class TimezonesResponse(BaseModel):
    success: bool = True
    timezones: list[str]


def get_config_path() -> str:
    env_path = os.environ.get("CONFIG_FILE")
    if env_path:
        return env_path

    common_paths = [
        "config/simple.toml",
        "config/docker.toml",
        "config/full.toml",
        "/app/config.toml",
        "config.toml",
    ]

    for path in common_paths:
        if Path(path).is_file():
            return path

    return "/app/config.toml"


def read_config_file() -> tuple[str, str]:
    config_path = get_config_path()
    path = Path(config_path)

    if not path.exists():
        raise ConfigException(f"Configuration file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return content, config_path


def write_config_file(content: str):
    config_path = get_config_path()
    path = Path(config_path)

    try:
        tomlkit.loads(content)
    except Exception as e:
        raise ConfigException(f"Invalid TOML syntax: {str(e)}")

    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)

    shutil.move(str(temp_path), str(path))


def config_to_dict(toml_content: str) -> dict:
    return tomlkit.loads(toml_content)


def extract_comments(toml_content: str) -> dict:
    doc = tomlkit.loads(toml_content)
    comments = {}

    def extract_from_table(table, prefix=""):
        for key, item in table.items():
            path = f"{prefix}.{key}" if prefix else key

            if hasattr(item, "trivia") and item.trivia.comment:
                comments[path] = item.trivia.comment.strip()

            if isinstance(item, tomlkit.items.Table):
                extract_from_table(item, path)
            elif isinstance(item, tomlkit.items.InlineTable):
                for k, v in item.items():
                    nested_path = f"{path}.{k}"
                    if hasattr(v, "trivia") and v.trivia.comment:
                        comments[nested_path] = v.trivia.comment.strip()

    for key, value in doc.items():
        if hasattr(value, "trivia") and value.trivia.comment:
            comments[key] = value.trivia.comment.strip()
        if hasattr(value, "items"):
            extract_from_table(value, key)

    return comments


def _update_toml_document(doc, config_dict):
    from tomlkit.items import AoT

    for key, value in config_dict.items():
        if isinstance(value, dict) and key not in doc:
            doc[key] = tomlkit.table()
            _update_toml_document(doc[key], value)
        elif isinstance(value, dict):
            _update_toml_document(doc[key], value)
        elif isinstance(value, list):
            aot = AoT([])
            for item in value:
                if isinstance(item, dict):
                    table = tomlkit.table()
                    for k, v in item.items():
                        table[k] = v
                    aot.append(table)
                else:
                    aot.append(item)
            doc[key] = aot
        else:
            doc[key] = value

    _remove_empty_values(doc)


def _remove_empty_values(table):
    keys_to_remove = []

    for key, value in table.items():
        if isinstance(value, tomlkit.items.Table):
            _remove_empty_values(value)
        elif isinstance(value, str) and value == "":
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del table[key]


@router.get("", response_model=ConfigResponse)
def get_config():
    try:
        toml_content, config_path = read_config_file()
        config_dict = config_to_dict(toml_content)
        comments = extract_comments(toml_content)

        return ConfigResponse(
            data=config_dict,
            toml=toml_content,
            path=config_path,
            comments=comments,
        )
    except ConfigException as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("", response_model=ConfigSaveResponse)
def save_config(request: ConfigSaveRequest):
    if not request.toml and not request.config:
        raise HTTPException(status_code=400, detail="No data provided")

    if request.toml:
        toml_content = request.toml
    else:
        toml_content, _ = read_config_file()
        doc = tomlkit.loads(toml_content)
        _update_toml_document(doc, request.config)
        toml_content = doc.as_string()

    try:
        write_config_file(toml_content)
        return ConfigSaveResponse(
            success=True,
            message="Configuration saved successfully",
            toml=toml_content,
        )
    except ConfigException as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/validate", response_model=ConfigValidateResponse)
def validate_config(request: ConfigValidateRequest):
    try:
        config_dict = config_to_dict(request.toml)
        return ConfigValidateResponse(
            success=True,
            message="Configuration is valid",
            data=config_dict,
        )
    except Exception as e:
        return ConfigValidateResponse(
            success=False,
            error=str(e),
        )


@router.get("/timezones", response_model=TimezonesResponse)
def get_timezones():
    return TimezonesResponse(timezones=sorted(pytz.all_timezones))
```

**Step 4: Write RSS route**

Create `src/progress/api/routes/rss.py`:

```python
from datetime import datetime

import pytz
from fastapi import APIRouter, Request
from fastapi.responses import Response
from feedgen.feed import FeedGenerator

from ...db.models import Report

router = APIRouter(tags=["rss"])


def render_markdown(content: str) -> str:
    from markdown_it import MarkdownIt
    from mdit_py_plugins.footnote import footnote_plugin
    from mdit_py_plugins.front_matter import front_matter_plugin

    if not content:
        return ""
    mdit = (
        MarkdownIt("commonmark", {"breaks": True, "html": True})
        .use(front_matter_plugin)
        .use(footnote_plugin)
    )
    return mdit.render(content)


@router.get("/rss")
def get_rss(request: Request, timezone_str: str = "UTC", language: str = "en"):
    timezone = pytz.timezone(timezone_str)

    fg = FeedGenerator()
    fg.title("Progress Reports")
    fg.link(href=str(request.base_url))
    fg.description("Open source project progress reports")
    fg.language(language)

    reports = (
        Report.select()
        .where(Report.repo.is_null())
        .order_by(Report.created_at.desc())
        .limit(50)
    )

    for report in reports:
        fe = fg.add_entry()
        fe.title(report.title or "Untitled Report")
        fe.link(href=f"{request.base_url}report/{report.id}")

        content = render_markdown(report.content or "")
        fe.content(content)

        if report.created_at:
            if isinstance(report.created_at, datetime):
                created_at = report.created_at.astimezone(timezone)
            else:
                created_at = report.created_at
            fe.published(
                created_at.strftime("%a, %d %b %Y %H:%M:%S %Z")
                if isinstance(created_at, datetime)
                else str(created_at)
            )
            fe.updated(
                created_at.strftime("%a, %d %b %Y %H:%M:%S %Z")
                if isinstance(created_at, datetime)
                else str(created_at)
            )

    rss_feed = fg.rss_str(pretty=True)
    return Response(
        content=rss_feed,
        media_type="application/rss+xml; charset=utf-8",
    )
```

**Step 5: Write main API module**

Create `src/progress/api/__init__.py`:

```python
from fastapi import FastAPI

from .routes import config, reports, rss


def create_app(config=None):
    from ..config import Config
    from ..consts import DATABASE_PATH
    from ..db import close_db, create_tables, init_db

    if config is None:
        import os
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config = Config.load_from_file(config_file)

    app = FastAPI(title="Progress API")

    app.state.config = config
    app.state.timezone = config.get_timezone()

    init_db(DATABASE_PATH)
    create_tables()

    api_router = FastAPI(prefix="/api/v1")
    api_router.include_router(reports.router)
    api_router.include_router(config.router)
    api_router.include_router(rss.router)
    app.mount("/api/v1", api_router)

    @app.on_event("shutdown")
    def shutdown_db():
        close_db()

    return app
```

**Step 6: Create routes __init__**

Create `src/progress/api/routes/__init__.py`:

```python
from . import config, reports, rss

__all__ = ["config", "reports", "rss"]
```

**Step 7: Commit**

```bash
git add src/progress/api/
git commit -m "feat(api): add FastAPI application with reports, config, and RSS routes"
```

---

### Task 3: Update CLI Serve Command

**Files:**
- Modify: `src/progress/cli.py:914-961`

**Step 1: Update imports**

Add at top of `cli.py` after existing imports:

```python
from .api import create_app as create_fastapi_app
```

Remove the Flask import:
```python
# Remove: from .web import create_app
```

**Step 2: Update serve command**

Replace the `serve` command function:

```python
@cli.command(name="serve")
@click.option("--host", "-h", default=None, help="Override host from config")
@click.option("--port", "-p", default=None, type=int, help="Override port from config")
@click.option("--reload/--no-reload", default=True, help="Enable/disable auto-reload")
@click.pass_context
def serve(ctx, host, port, reload):
    """Start development server with hot reload."""
    import uvicorn

    config_path = ctx.obj["config_path"]

    try:
        logger.info(f"Loading configuration file: {config_path}")
        cfg = Config.load_from_file(config_path)

        initialize(ui_language=cfg.language)

        host = host or cfg.web.host
        port = port or cfg.web.port

        if reload:
            logger.warning(
                "Hot reload is enabled. This should NOT be used in production."
            )

        os.environ["CONFIG_FILE"] = config_path

        logger.info(f"Starting server on {host}:{port}")
        logger.info(f"Hot reload: {'enabled' if reload else 'disabled'}")

        uvicorn.run(
            "progress.api:create_app",
            host=host,
            port=port,
            reload=reload,
            factory=True,
        )

    except ProgressException as e:
        logger.error(f"Application error: {e}", exc_info=True)
        raise click.ClickException(str(e))
    except Exception as e:
        logger.error(f"Program execution failed: {e}", exc_info=True)
        raise click.ClickException(str(e))
```

**Step 3: Add os import**

Add `import os` at the top of the file with other imports.

**Step 4: Commit**

```bash
git add src/progress/cli.py
git commit -m "feat(cli): update serve command to use uvicorn with FastAPI"
```

---

### Task 4: Add Static File Serving to FastAPI

**Files:**
- Modify: `src/progress/api/__init__.py`

**Step 1: Add static file serving and SPA fallback**

Update `src/progress/api/__init__.py`:

```python
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routes import config, reports, rss


def create_app(config=None):
    from ..config import Config
    from ..consts import DATABASE_PATH
    from ..db import close_db, create_tables, init_db

    if config is None:
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config = Config.load_from_file(config_file)

    app = FastAPI(title="Progress API")

    app.state.config = config
    app.state.timezone = config.get_timezone()

    init_db(DATABASE_PATH)
    create_tables()

    api_router = FastAPI(prefix="/api/v1")
    api_router.include_router(reports.router)
    api_router.include_router(config.router)
    api_router.include_router(rss.router)
    app.mount("/api/v1", api_router)

    web_dist = Path(__file__).parent.parent / "web" / "dist"
    if web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

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
```

**Step 2: Commit**

```bash
git add src/progress/api/__init__.py
git commit -m "feat(api): add static file serving and SPA fallback for frontend"
```

---

### Task 5: Write Tests for API Routes

**Files:**
- Create: `tests/api/__init__.py`
- Create: `tests/api/test_reports.py`
- Create: `tests/api/test_config.py`

**Step 1: Create test directory**

```bash
mkdir -p tests/api
touch tests/api/__init__.py
```

**Step 2: Write reports test**

Create `tests/api/test_reports.py`:

```python
import pytest
from fastapi.testclient import TestClient


def test_list_reports_empty_db(monkeypatch):
    from progress.api import create_app
    from progress.db import close_db, create_tables, init_db
    from progress.consts import DATABASE_PATH

    monkeypatch.setenv("CONFIG_FILE", "config/simple.toml")

    init_db(DATABASE_PATH)
    create_tables()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/reports")
    assert response.status_code == 200
    data = response.json()
    assert "reports" in data
    assert "page" in data
    assert "total_pages" in data

    close_db()


def test_get_report_not_found(monkeypatch):
    from progress.api import create_app
    from progress.db import close_db, create_tables, init_db
    from progress.consts import DATABASE_PATH

    monkeypatch.setenv("CONFIG_FILE", "config/simple.toml")

    init_db(DATABASE_PATH)
    create_tables()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/reports/99999")
    assert response.status_code == 404

    close_db()
```

**Step 3: Write config test**

Create `tests/api/test_config.py`:

```python
import pytest
from fastapi.testclient import TestClient


def test_get_timezones(monkeypatch):
    from progress.api import create_app
    from progress.db import close_db, create_tables, init_db
    from progress.consts import DATABASE_PATH

    monkeypatch.setenv("CONFIG_FILE", "config/simple.toml")

    init_db(DATABASE_PATH)
    create_tables()

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/config/timezones")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "UTC" in data["timezones"]
    assert len(data["timezones"]) > 0

    close_db()


def test_validate_config_invalid_toml(monkeypatch):
    from progress.api import create_app
    from progress.db import close_db, create_tables, init_db
    from progress.consts import DATABASE_PATH

    monkeypatch.setenv("CONFIG_FILE", "config/simple.toml")

    init_db(DATABASE_PATH)
    create_tables()

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/config/validate",
        json={"toml": "invalid [toml"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False

    close_db()
```

**Step 4: Run tests**

```bash
uv run pytest tests/api/ -v
```

**Step 5: Commit**

```bash
git add tests/api/
git commit -m "test(api): add tests for reports and config routes"
```

---

## Phase 2: Frontend Setup

### Task 6: Initialize Frontend Project

**Files:**
- Create: `src/progress/web/package.json`
- Create: `src/progress/web/tsconfig.json`
- Create: `src/progress/web/tsconfig.node.json`
- Create: `src/progress/web/vite.config.ts`
- Create: `src/progress/web/tailwind.config.ts`
- Create: `src/progress/web/postcss.config.js`
- Create: `src/progress/web/index.html`
- Create: `src/progress/web/src/main.tsx`
- Create: `src/progress/web/src/App.tsx`
- Create: `src/progress/web/src/index.css`

**Step 1: Create directory structure**

```bash
mkdir -p src/progress/web/src/components/ui
mkdir -p src/progress/web/src/pages
mkdir -p src/progress/web/src/hooks
mkdir -p src/progress/web/src/lib
mkdir -p src/progress/web/public
```

**Step 2: Create package.json**

Create `src/progress/web/package.json`:

```json
{
  "name": "progress-web",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint ."
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0",
    "swr": "^2.2.5",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4",
    "class-variance-authority": "^0.7.1",
    "lucide-react": "^0.460.0"
  },
  "devDependencies": {
    "@types/node": "^22.9.0",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.10"
  }
}
```

**Step 3: Create tsconfig.json**

Create `src/progress/web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

**Step 4: Create tsconfig.node.json**

Create `src/progress/web/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

**Step 5: Create vite.config.ts**

Create `src/progress/web/vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
```

**Step 6: Create tailwind.config.ts**

Create `src/progress/web/tailwind.config.ts`:

```typescript
import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'media',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        gray: {
          50: '#f9fafb',
          100: '#f3f4f6',
          200: '#e5e7eb',
          300: '#d1d5db',
          400: '#9ca3af',
          500: '#6b7280',
          600: '#4b5563',
          700: '#374151',
          800: '#1f2937',
          900: '#111827',
          950: '#0b0f19',
        },
      },
    },
  },
  plugins: [],
}

export default config
```

**Step 7: Create postcss.config.js**

Create `src/progress/web/postcss.config.js`:

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

**Step 8: Create index.html**

Create `src/progress/web/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Progress Reports</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**Step 9: Create index.css**

Create `src/progress/web/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  @apply bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800 min-h-screen p-5;
}

.prose h1 {
  @apply text-3xl mt-10 mb-5 pb-3 border-b border-gray-200 dark:border-gray-700 font-bold tracking-tight;
}
.prose h2 {
  @apply text-2xl mt-10 mb-5 pb-3 border-b-2 border-gray-200 dark:border-gray-700 font-bold;
}
.prose h3 {
  @apply text-xl mt-8 mb-4 font-semibold relative pl-4;
}
.prose h3::before {
  content: '';
  @apply absolute left-0 top-0.5 bottom-0.5 w-1 bg-gradient-to-b from-blue-600 to-blue-700 rounded;
}
.prose p {
  @apply mb-6 leading-relaxed;
}
.prose ul, .prose ol {
  @apply mb-6 pl-7;
}
.prose li {
  @apply mb-2 leading-relaxed;
}
.prose code {
  @apply bg-gray-100 dark:bg-gray-900 px-1.5 py-0.5 rounded text-sm border border-gray-200 dark:border-gray-700 break-words;
}
.prose pre {
  @apply bg-gray-900 p-5 rounded-lg overflow-x-auto mb-6 border border-gray-700;
}
.prose pre code {
  @apply bg-transparent p-0 border-0;
}
.prose a {
  @apply text-blue-600 dark:text-blue-400 no-underline hover:underline;
}
.prose blockquote {
  @apply border-l-4 border-blue-500 pl-5 py-5 pr-7 bg-gradient-to-r from-blue-50 to-white dark:from-gray-800 dark:to-gray-900 rounded-r-lg mb-6;
}
.prose table {
  @apply w-full border-collapse mb-6 rounded-lg overflow-hidden;
}
.prose th, .prose td {
  @apply border border-gray-200 dark:border-gray-700 px-4 py-3 text-left;
}
.prose th {
  @apply bg-gray-50 dark:bg-gray-800 font-semibold;
}
```

**Step 10: Create main.tsx**

Create `src/progress/web/src/main.tsx`:

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
```

**Step 11: Create App.tsx**

Create `src/progress/web/src/App.tsx`:

```tsx
import { Routes, Route } from 'react-router-dom'
import ReportList from './pages/ReportList'
import ReportDetail from './pages/ReportDetail'
import Config from './pages/Config'

function App() {
  return (
    <Routes>
      <Route path="/" element={<ReportList />} />
      <Route path="/report/:id" element={<ReportDetail />} />
      <Route path="/config" element={<Config />} />
    </Routes>
  )
}

export default App
```

**Step 12: Commit**

```bash
git add src/progress/web/
git commit -m "feat(web): initialize React frontend with Vite, TypeScript, Tailwind"
```

---

### Task 7: Add Utility Functions

**Files:**
- Create: `src/progress/web/src/lib/utils.ts`

**Step 1: Create utils.ts**

Create `src/progress/web/src/lib/utils.ts`:

```typescript
import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

**Step 2: Commit**

```bash
git add src/progress/web/src/lib/utils.ts
git commit -m "feat(web): add cn utility for className merging"
```

---

### Task 8: Add shadcn/ui Components

**Files:**
- Create: `src/progress/web/src/components/ui/button.tsx`
- Create: `src/progress/web/src/components/ui/card.tsx`
- Create: `src/progress/web/src/components/ui/input.tsx`
- Create: `src/progress/web/src/components/ui/label.tsx`
- Create: `src/progress/web/src/components/ui/textarea.tsx`
- Create: `src/progress/web/src/components/ui/checkbox.tsx`
- Create: `src/progress/web/src/components/ui/select.tsx`
- Create: `src/progress/web/src/components/ui/dialog.tsx`
- Create: `src/progress/web/src/components/ui/toast.tsx`
- Create: `src/progress/web/src/components/ui/tabs.tsx`

**Step 1: Create Button component**

Create `src/progress/web/src/components/ui/button.tsx`:

```tsx
import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-lg text-sm font-medium transition-all hover:-translate-y-px disabled:opacity-50 disabled:pointer-events-none',
  {
    variants: {
      variant: {
        default: 'bg-blue-600 text-white hover:bg-blue-700',
        outline: 'border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700',
        ghost: 'hover:bg-gray-100 dark:hover:bg-gray-800',
        destructive: 'bg-red-500 text-white hover:bg-red-600',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-8 px-3 text-xs',
        lg: 'h-12 px-6',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
```

**Step 2: Create Card component**

Create `src/progress/web/src/components/ui/card.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700',
      className
    )}
    {...props}
  />
))
Card.displayName = 'Card'

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('p-6 border-b border-gray-200 dark:border-gray-700', className)}
    {...props}
  />
))
CardHeader.displayName = 'CardHeader'

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('p-6', className)} {...props} />
))
CardContent.displayName = 'CardContent'

export { Card, CardHeader, CardContent }
```

**Step 3: Create Input component**

Create `src/progress/web/src/components/ui/input.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = 'Input'

export { Input }
```

**Step 4: Create Label component**

Create `src/progress/web/src/components/ui/label.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn('block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1', className)}
    {...props}
  />
))
Label.displayName = 'Label'

export { Label }
```

**Step 5: Create Textarea component**

Create `src/progress/web/src/components/ui/textarea.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          'w-full p-4 font-mono text-sm bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 border-0 resize-none focus:outline-none rounded-lg',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Textarea.displayName = 'Textarea'

export { Textarea }
```

**Step 6: Create Checkbox component**

Create `src/progress/web/src/components/ui/checkbox.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface CheckboxProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, ...props }, ref) => {
    return (
      <input
        type="checkbox"
        className={cn(
          'rounded border-gray-300 text-blue-600 focus:ring-blue-500',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Checkbox.displayName = 'Checkbox'

export { Checkbox }
```

**Step 7: Create Select component**

Create `src/progress/web/src/components/ui/select.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <select
        className={cn(
          'w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:outline-none',
          className
        )}
        ref={ref}
        {...props}
      >
        {children}
      </select>
    )
  }
)
Select.displayName = 'Select'

export { Select }
```

**Step 8: Create Dialog component**

Create `src/progress/web/src/components/ui/dialog.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
}

const Dialog: React.FC<DialogProps> = ({ open, onClose, title, children }) => {
  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full mx-4">
        <div className="flex justify-between items-center p-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

export { Dialog }
```

**Step 9: Create Toast component**

Create `src/progress/web/src/components/ui/toast.tsx`:

```tsx
import React, { createContext, useContext, useState, useCallback } from 'react'
import { cn } from '@/lib/utils'

type ToastType = 'success' | 'error' | 'info' | 'warning'

interface Toast {
  id: number
  message: string
  type: ToastType
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}

const colors: Record<ToastType, string> = {
  success: 'bg-green-500',
  error: 'bg-red-500',
  info: 'bg-blue-500',
  warning: 'bg-yellow-500',
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Date.now()
    setToasts((prev) => [...prev, { id, message, type }])

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3000)
  }, [])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              `${colors[toast.type]} text-white px-4 py-3 rounded-lg shadow-lg text-sm animate-slide-in`
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
```

**Step 10: Create Tabs component**

Create `src/progress/web/src/components/ui/tabs.tsx`:

```tsx
import * as React from 'react'
import { cn } from '@/lib/utils'

interface TabsProps {
  value: string
  onValueChange: (value: string) => void
  children: React.ReactNode
}

interface TabsListProps {
  children: React.ReactNode
  className?: string
}

interface TabsTriggerProps {
  value: string
  children: React.ReactNode
}

interface TabsContentProps {
  value: string
  children: React.ReactNode
}

const TabsContext = React.createContext<{
  value: string
  onValueChange: (value: string) => void
} | null>(null)

const Tabs: React.FC<TabsProps> = ({ value, onValueChange, children }) => (
  <TabsContext.Provider value={{ value, onValueChange }}>
    {children}
  </TabsContext.Provider>
)

const TabsList: React.FC<TabsListProps> = ({ children, className }) => (
  <div className={cn('flex gap-2', className)}>{children}</div>
)

const TabsTrigger: React.FC<TabsTriggerProps> = ({ value, children }) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error('TabsTrigger must be used within Tabs')

  const isActive = context.value === value

  return (
    <button
      onClick={() => context.onValueChange(value)}
      className={cn(
        'px-3 py-1.5 text-sm font-medium rounded-lg transition-colors',
        isActive
          ? 'bg-blue-600 text-white'
          : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
      )}
    >
      {children}
    </button>
  )
}

const TabsContent: React.FC<TabsContentProps> = ({ value, children }) => {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error('TabsContent must be used within Tabs')

  if (context.value !== value) return null
  return <>{children}</>
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
```

**Step 11: Update App.tsx with ToastProvider**

Update `src/progress/web/src/App.tsx`:

```tsx
import { Routes, Route } from 'react-router-dom'
import { ToastProvider } from './components/ui/toast'
import ReportList from './pages/ReportList'
import ReportDetail from './pages/ReportDetail'
import Config from './pages/Config'

function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/" element={<ReportList />} />
        <Route path="/report/:id" element={<ReportDetail />} />
        <Route path="/config" element={<Config />} />
      </Routes>
    </ToastProvider>
  )
}

export default App
```

**Step 12: Commit**

```bash
git add src/progress/web/src/components/
git commit -m "feat(web): add shadcn-style UI components"
```

---

### Task 9: Add SWR Hooks for API

**Files:**
- Create: `src/progress/web/src/hooks/api.ts`

**Step 1: Create API hooks**

Create `src/progress/web/src/hooks/api.ts`:

```typescript
import useSWR from 'swr'

const fetcher = async (url: string) => {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error('Failed to fetch')
  }
  return res.json()
}

export interface Report {
  id: number
  title: string | null
  created_at: string
  markpost_url: string | null
}

export interface ReportDetail extends Report {
  content: string
}

export interface PaginatedReports {
  reports: Report[]
  page: number
  total_pages: number
  total: number
  has_prev: boolean
  has_next: boolean
}

export function useReports(page: number = 1) {
  return useSWR<PaginatedReports>(`/api/v1/reports?page=${page}`, fetcher)
}

export function useReport(id: number | undefined) {
  return useSWR<ReportDetail>(id ? `/api/v1/reports/${id}` : null, fetcher)
}

export interface ConfigData {
  success: boolean
  data: Record<string, unknown>
  toml: string
  path: string
  comments: Record<string, string>
}

export function useConfig() {
  return useSWR<ConfigData>('/api/v1/config', fetcher)
}

export function useTimezones() {
  return useSWR<{ success: boolean; timezones: string[] }>('/api/v1/config/timezones', fetcher)
}

export async function saveConfigToml(toml: string): Promise<{ success: boolean; toml: string; error?: string }> {
  const res = await fetch('/api/v1/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toml }),
  })
  return res.json()
}

export async function saveConfigData(config: Record<string, unknown>): Promise<{ success: boolean; toml: string; error?: string }> {
  const res = await fetch('/api/v1/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  })
  return res.json()
}

export async function validateConfig(toml: string): Promise<{ success: boolean; error?: string }> {
  const res = await fetch('/api/v1/config/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toml }),
  })
  return res.json()
}
```

**Step 2: Commit**

```bash
git add src/progress/web/src/hooks/api.ts
git commit -m "feat(web): add SWR hooks for API endpoints"
```

---

### Task 10: Implement ReportList Page

**Files:**
- Create: `src/progress/web/src/pages/ReportList.tsx`

**Step 1: Create ReportList page**

Create `src/progress/web/src/pages/ReportList.tsx`:

```tsx
import { Link, useSearchParams } from 'react-router-dom'
import { useReports } from '@/hooks/api'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

export default function ReportList() {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parseInt(searchParams.get('page') || '1', 10)
  const { data, error, isLoading } = useReports(page)

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto my-8 px-8 py-10">
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto my-8 px-8 py-10">
        <p className="text-red-500">Failed to load reports</p>
      </div>
    )
  }

  const handlePageChange = (newPage: number) => {
    setSearchParams({ page: newPage.toString() })
  }

  return (
    <div className="max-w-2xl mx-auto my-8 px-8 py-10 lg:my-10">
      <Card>
        <CardHeader>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 tracking-tight lg:text-2xl">
            Progress Reports
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {data?.total || 0} reports total
          </p>
        </CardHeader>
        <CardContent>
          <div className="mb-8">
            <Link to="/config">
              <Button variant="outline" className="mr-2.5 mb-7">
                Configuration
              </Button>
            </Link>
            <a href="/api/v1/rss">
              <Button variant="outline">RSS Feed</Button>
            </a>
          </div>

          <ul className="list-none">
            {data?.reports.map((report) => (
              <li
                key={report.id}
                className="py-5 border-b border-gray-200 dark:border-gray-700 last:border-b-0"
              >
                <Link
                  to={`/report/${report.id}`}
                  className="text-lg font-semibold text-blue-600 dark:text-blue-400 block mb-1.5 hover:text-blue-700 dark:hover:text-blue-300 transition-colors lg:text-base"
                >
                  {report.title || 'Untitled Report'}
                </Link>
                <div className="text-sm text-gray-600 dark:text-gray-400">
                  {report.created_at}
                  {report.markpost_url && (
                    <a
                      href={report.markpost_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-2 px-2 py-0.5 text-xs border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-700 transition-all hover:-translate-y-px"
                    >
                      View External ↗
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>

          <div className="flex justify-center items-center gap-5 mt-8 pt-5 border-t border-gray-200 dark:border-gray-700">
            <Button
              variant="outline"
              disabled={!data?.has_prev}
              onClick={() => handlePageChange(page - 1)}
              className={!data?.has_prev ? 'opacity-60 pointer-events-none' : ''}
            >
              Previous
            </Button>

            <span className="text-sm text-gray-600 dark:text-gray-400">
              Page {data?.page || 1} of {data?.total_pages || 1}
            </span>

            <Button
              variant="outline"
              disabled={!data?.has_next}
              onClick={() => handlePageChange(page + 1)}
              className={!data?.has_next ? 'opacity-60 pointer-events-none' : ''}
            >
              Next
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add src/progress/web/src/pages/ReportList.tsx
git commit -m "feat(web): implement ReportList page with pagination"
```

---

### Task 11: Implement ReportDetail Page

**Files:**
- Create: `src/progress/web/src/pages/ReportDetail.tsx`

**Step 1: Install markdown-it dependency**

Add to `src/progress/web/package.json`:

```json
"react-markdown": "^9.0.1",
```

Then run:

```bash
cd src/progress/web && pnpm add react-markdown
```

**Step 2: Create ReportDetail page**

Create `src/progress/web/src/pages/ReportDetail.tsx`:

```tsx
import { useParams, Link } from 'react-router-dom'
import { useReport } from '@/hooks/api'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import ReactMarkdown from 'react-markdown'

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>()
  const reportId = id ? parseInt(id, 10) : undefined
  const { data: report, error, isLoading } = useReport(reportId)

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto my-8 px-8 py-10">
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="max-w-3xl mx-auto my-8 px-8 py-10">
        <Card>
          <CardContent>
            <p className="text-red-500">Report not found</p>
            <Link to="/" className="text-blue-600 dark:text-blue-400 hover:underline">
              Back to list
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto my-8 px-8 py-10 lg:my-10">
      <Card>
        <CardContent>
          <Link
            to="/"
            className="inline-flex items-center text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 mb-5 transition-colors"
          >
            ← Back to list
          </Link>
          <div className="mb-8 pb-5 border-b border-gray-200 dark:border-gray-700">
            <h1 className="text-3xl font-bold mb-2.5 text-gray-900 dark:text-gray-100 tracking-tight lg:text-2xl">
              {report.title || 'Untitled Report'}
            </h1>
            <div className="text-sm text-gray-600 dark:text-gray-400">
              {report.created_at}
              {report.markpost_url && (
                <a
                  href={report.markpost_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-2.5 px-2.5 py-1 text-xs border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-700 transition-all hover:-translate-y-px"
                >
                  View External ↗
                </a>
              )}
            </div>
          </div>
          <div className="prose prose-gray dark:prose-invert max-w-none text-base leading-relaxed">
            <ReactMarkdown>{report.content}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

**Step 3: Commit**

```bash
git add src/progress/web/src/pages/ReportDetail.tsx src/progress/web/package.json
git commit -m "feat(web): implement ReportDetail page with markdown rendering"
```

---

### Task 12: Implement Config Page

**Files:**
- Create: `src/progress/web/src/pages/Config.tsx`

**Step 1: Create Config page**

Create `src/progress/web/src/pages/Config.tsx`:

```tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import useSWR from 'swr'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/components/ui/toast'
import { useConfig, saveConfigToml, validateConfig } from '@/hooks/api'

export default function Config() {
  const { data, error, isLoading, mutate } = useConfig()
  const [tomlContent, setTomlContent] = useState('')
  const [isModified, setIsModified] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const { showToast } = useToast()

  useState(() => {
    if (data?.toml) {
      setTomlContent(data.toml)
    }
  })

  const handleTomlChange = (value: string) => {
    setTomlContent(value)
    setIsModified(value !== data?.toml)
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const validation = await validateConfig(tomlContent)
      if (!validation.success) {
        showToast('Validation failed: ' + validation.error, 'error')
        return
      }

      const result = await saveConfigToml(tomlContent)
      if (result.success) {
        showToast('Configuration saved successfully!', 'success')
        setIsModified(false)
        mutate()
      } else {
        showToast('Save failed: ' + result.error, 'error')
      }
    } catch (e) {
      showToast('Save error: ' + (e as Error).message, 'error')
    } finally {
      setIsSaving(false)
    }
  }

  const handleReset = () => {
    if (confirm('Reset to original configuration? Unsaved changes will be lost.')) {
      setTomlContent(data?.toml || '')
      setIsModified(false)
    }
  }

  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto my-8 px-8 py-10">
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-6xl mx-auto my-8 px-8 py-10">
        <Card>
          <CardContent>
            <p className="text-red-500">Failed to load configuration</p>
            <Link to="/" className="text-blue-600 dark:text-blue-400 hover:underline">
              Back to list
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto my-8 px-8 py-10 lg:my-10">
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <Link
              to="/"
              className="text-xl font-bold text-gray-900 dark:text-white"
            >
              Progress
            </Link>
            <div className="flex items-center gap-3">
              <Button variant="outline" onClick={handleReset}>
                Reset
              </Button>
              <Button onClick={handleSave} disabled={!isModified || isSaving}>
                {isSaving ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              Configuration Editor
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Path: {data?.path}
            </p>
          </div>
          <Textarea
            value={tomlContent}
            onChange={(e) => handleTomlChange(e.target.value)}
            className="h-[calc(100vh-300px)]"
            spellCheck={false}
          />
          <div className="mt-4 flex items-center gap-2 text-sm">
            <span
              className={`w-2 h-2 rounded-full ${
                isModified ? 'bg-yellow-500' : 'bg-green-500'
              }`}
            />
            <span className="text-gray-600 dark:text-gray-400">
              {isModified ? 'Unsaved changes' : 'Valid TOML'}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add src/progress/web/src/pages/Config.tsx
git commit -m "feat(web): implement Config page with TOML editor"
```

---

### Task 13: Install Dependencies and Test Build

**Step 1: Install pnpm (if not available)**

```bash
corepack enable
corepack prepare pnpm@latest --activate
```

**Step 2: Install frontend dependencies**

```bash
cd src/progress/web && pnpm install
```

**Step 3: Test development server**

```bash
cd src/progress/web && pnpm dev
```

Verify the dev server starts on port 5173.

**Step 4: Test production build**

```bash
cd src/progress/web && pnpm build
```

Verify the build completes without errors and creates `dist/` directory.

**Step 5: Commit lock file**

```bash
git add src/progress/web/pnpm-lock.yaml
git commit -m "chore(web): add pnpm lock file"
```

---

## Phase 3: Docker Update

### Task 14: Update Dockerfile for Multi-Stage Build

**Files:**
- Modify: `docker/Dockerfile`

**Step 1: Update Dockerfile**

Replace entire `docker/Dockerfile`:

```dockerfile
# Stage 1: Frontend build
FROM node:20-slim AS frontend

WORKDIR /app/src/progress/web

RUN corepack enable pnpm

COPY src/progress/web/package.json src/progress/web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install

COPY src/progress/web/ ./
RUN pnpm build

# Stage 2: Python builder
FROM python:3.13-slim AS builder

ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    gettext \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    export PATH="/root/.local/bin:$PATH" && \
    uv --version

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

ENV PATH="/root/.local/bin:$PATH"
RUN uv pip install --system -e .

# Compile i18n translation files
RUN if [ -d "/app/src/progress/locales" ]; then \
        find /app/src/progress/locales -name "*.po" | while read po_file; do \
            mo_file="${po_file%.po}.mo"; \
            mkdir -p "$(dirname "$mo_file")"; \
            msgfmt -o "$mo_file" "$po_file" || echo "Failed to compile $po_file"; \
        done; \
        echo "i18n files compiled"; \
    else \
        echo "No locales directory found, skipping i18n compilation"; \
    fi

# Stage 3: Production image
FROM python:3.13-slim

ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    curl \
    ca-certificates \
    npm \
    && rm -rf /var/lib/apt/lists/*

ENV SUPERCRONIC_VERSION=v0.2.33

RUN SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH} \
    && curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && supercronic -version || echo "Supercronic installed for ${TARGETARCH}"

RUN npm install -g @anthropic-ai/claude-code

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.local/bin /root/.local/bin
COPY --from=builder /app/src/progress/locales /app/src/progress/locales

# Copy frontend build
COPY --from=frontend /app/src/progress/web/dist /app/src/progress/web/dist

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN mkdir -p /app/data

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

**Step 2: Commit**

```bash
git add docker/Dockerfile
git commit -m "feat(docker): add multi-stage build for frontend and backend"
```

---

## Phase 4: Cleanup

### Task 15: Remove Flask and Jinja2 Templates

**Files:**
- Delete: `src/progress/web.py`
- Delete: `src/progress/templates/web/list.html`
- Delete: `src/progress/templates/web/detail.html`
- Delete: `src/progress/templates/web/config.html`
- Delete: `src/progress/templates/web/404.html`
- Delete: `src/progress/templates/web/_config_editor.html`
- Delete: `src/progress/templates/web/_config_sidebar.html`

**Step 1: Delete Flask app**

```bash
rm src/progress/web.py
```

**Step 2: Delete Jinja2 templates**

```bash
rm -rf src/progress/templates/web/
```

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove Flask app and Jinja2 templates"
```

---

### Task 16: Update .gitignore

**Files:**
- Modify: `.gitignore`

**Step 1: Add frontend build artifacts**

Add to `.gitignore`:

```
# Frontend build
src/progress/web/dist/
src/progress/web/node_modules/
```

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore frontend build artifacts"
```

---

### Task 17: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `guides/dev.md`

**Step 1: Update CLAUDE.md**

Update the Tech Stack section:

```markdown
## Tech Stack

- Programming Language: Python 3.12+
- Package and Project Manager: uv 0.9+
- CLI Framework: Click 8.3+
- Web Framework: FastAPI 0.115+
- Frontend: React 18 + TypeScript + Vite 5 + shadcn/ui + Tailwind CSS
- Frontend Package Manager: pnpm
- RSS Generation: feedgen
- Markdown Rendering: react-markdown
- Containerized development and deployment: Docker
- Git Operations: GitPython 3.1.46+
- GitHub API: PyGithub 2.8.1+
- GitHub CLI: GitHub CLI (gh) - only for initial repository clone
- AI Assistant: Claude Code
```

Update the Commands section:

```markdown
## Commands

- Install dependencies: `uv sync`
- Install frontend dependencies: `cd src/progress/web && pnpm install`
- Run application: `uv run progress -c config.toml`
- Run unit tests: `uv run pytest -v`
- Start dev server (backend): `uv run uvicorn progress.api:app --reload --port 8000`
- Start dev server (frontend): `cd src/progress/web && pnpm dev`
```

**Step 2: Update guides/dev.md**

Add development server instructions:

```markdown
## Development Server

### Backend (FastAPI)

```bash
uv run uvicorn progress.api:app --reload --port 8000
```

### Frontend (Vite)

```bash
cd src/progress/web
pnpm dev
```

The frontend dev server runs on port 5173 and proxies API requests to the backend on port 8000.
```

**Step 3: Commit**

```bash
git add CLAUDE.md guides/dev.md
git commit -m "docs: update tech stack and development instructions"
```

---

### Task 18: Final Integration Test

**Step 1: Run all Python tests**

```bash
uv run pytest -v
```

**Step 2: Build frontend**

```bash
cd src/progress/web && pnpm build
```

**Step 3: Start production server**

```bash
uv run uvicorn progress.api:app --host 0.0.0.0 --port 8000
```

**Step 4: Verify endpoints**

- `http://localhost:8000/` - Report list
- `http://localhost:8000/report/1` - Report detail
- `http://localhost:8000/config` - Config editor
- `http://localhost:8000/api/v1/reports` - API endpoint
- `http://localhost:8000/api/v1/rss` - RSS feed

**Step 5: Commit final state**

```bash
git add -A
git commit -m "feat: complete web stack migration to FastAPI + React"
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| Phase 1 | 1-5 | Backend migration to FastAPI |
| Phase 2 | 6-13 | Frontend setup with React + Vite |
| Phase 3 | 14 | Docker multi-stage build |
| Phase 4 | 15-18 | Cleanup and documentation |
