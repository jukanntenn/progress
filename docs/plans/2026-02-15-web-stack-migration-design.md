# Web Stack Migration Design

Migrate from Flask + Jinja2 templates to FastAPI + React (Vite + shadcn/ui + Tailwind CSS + pnpm).

## Summary

- **Backend:** FastAPI replaces Flask, API endpoints move to `/api/v1/*`
- **Frontend:** React + TypeScript + Vite + shadcn/ui + Tailwind CSS
- **Data fetching:** SWR
- **Routing:** React Router
- **State:** React hooks only
- **Deployment:** Single deployment, FastAPI serves built frontend assets
- **Dev workflow:** Vite dev server proxies to FastAPI, both hot reload

## Project Structure

```
src/progress/
├── web/                          # Frontend root
│   ├── src/
│   │   ├── components/
│   │   │   └── ui/               # shadcn/ui components
│   │   ├── pages/
│   │   │   ├── ReportList.tsx    # /
│   │   │   ├── ReportDetail.tsx  # /report/:id
│   │   │   └── Config.tsx        # /config
│   │   ├── hooks/
│   │   │   └── api.ts            # SWR hooks
│   │   ├── lib/
│   │   │   └── utils.ts          # cn() helper
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── tsconfig.json
│   └── components.json
├── api.py                        # FastAPI app (new)
└── web.py                        # DELETE
```

## Backend (FastAPI)

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/reports` | Paginated report list |
| GET | `/api/v1/reports/{id}` | Single report |
| GET | `/api/v1/config` | Get configuration |
| POST | `/api/v1/config` | Save configuration |
| POST | `/api/v1/config/validate` | Validate TOML |
| GET | `/api/v1/timezones` | List timezones |
| GET | `/api/v1/rss` | RSS feed |

### Static File Serving

```python
app.mount("/assets", StaticFiles(directory="web/dist/assets"))

@app.get("/{path:path}")
def spa_fallback():
    return FileResponse("web/dist/index.html")
```

### Dependencies

Add:
- `fastapi>=0.115.0`
- `uvicorn[standard]>=0.32.0`

Remove:
- `flask>=3.0.0`
- `gunicorn>=23.0.0`

## Frontend

### Dependencies

```json
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0",
    "swr": "^2.2.5",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4"
  }
}
```

### Vite Config

- Dev server on `:5173`
- Proxy `/api/*` to FastAPI on `:8000`
- Build output to `dist/`

### Pages

1. **ReportList** - Paginated list, links to config/RSS
2. **ReportDetail** - Markdown content, back link, external link
3. **Config** - Visual editor + TOML toggle, channels/repos CRUD

### shadcn/ui Components

button, card, input, label, checkbox, select, dialog, toast, table, tabs, textarea

## Development Workflow

```bash
# Terminal 1: Backend
uv run uvicorn progress.api:app --reload --port 8000

# Terminal 2: Frontend
cd src/progress/web && pnpm dev
```

Access at `http://localhost:5173`

## Production Build

```bash
cd src/progress/web && pnpm build
uv run uvicorn progress.api:app --host 0.0.0.0 --port 8000
```

## Docker

Multi-stage build: Node for frontend, Python for backend.

## Files to Change

### Delete
- `src/progress/web.py`
- `src/progress/templates/web/*.html` (6 files)

### Modify
- `pyproject.toml` - Swap deps
- `src/progress/cli.py` - Update serve command
- `docker/Dockerfile` - Add frontend build stage

### Create
- `src/progress/api.py`
- `src/progress/web/` (~15-20 files)
