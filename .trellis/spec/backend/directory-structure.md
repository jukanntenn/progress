# Directory Structure

> How backend code is organized in this project.

---

## Overview

This project uses a modular Python package structure under `src/progress/`. Each module has a single responsibility and exports a clear public API. The project follows the "src layout" pattern where source code is separated from project root.

---

## Directory Layout

```
src/progress/
├── __init__.py              # Package initialization
├── cli.py                   # CLI entry point (Click commands)
├── config.py                # Configuration loading (Pydantic + TOML)
├── consts.py                # Constants and default values
├── enums.py                 # Enum definitions
├── errors.py                # Custom exception classes
├── i18n.py                  # Internationalization (gettext)
├── log.py                   # Logging configuration
├── utils/                   # Utility functions
│   ├── __init__.py
│   └── markpost.py          # Markpost API client
├── db/                      # Database layer
│   ├── __init__.py          # DB initialization and helpers
│   ├── models.py            # Peewee ORM models
│   └── migration_*.py       # Schema migrations
├── api/                     # FastAPI web layer
│   ├── __init__.py          # App factory (create_app)
│   ├── markdown.py          # Markdown rendering
│   └── routes/              # API route modules
│       ├── __init__.py
│       ├── reports.py       # Reports API
│       ├── config.py        # Config API
│       └── rss.py           # RSS feed API
├── notification/            # Notification system
│   ├── __init__.py          # Factory and exports
│   ├── base.py              # Protocol definitions
│   ├── config.py            # Notification config models
│   ├── channels/            # Notification channels
│   │   ├── __init__.py
│   │   ├── feishu.py        # Feishu webhook
│   │   ├── email.py         # Email (SMTP)
│   │   └── console.py       # Console output
│   └── messages/            # Message formatters
│       ├── __init__.py
│       ├── base.py
│       └── feishu.py
├── contrib/                 # Contributed features
│   ├── repo/                # Repository tracking
│   ├── proposal/            # Proposal tracking
│   └── changelog/           # Changelog tracking
├── ai/                      # AI analysis
│   └── analyzers/
│       └── claude_code.py   # Claude Code integration
├── storages.py              # Storage backends (DB, file, markpost)
└── templates/               # Jinja2 templates
    ├── aggregated_report.j2
    ├── analysis_prompt.j2
    └── ...
```

---

## Module Organization

### Adding a New Feature Module

1. Create a new directory under `src/progress/` with a descriptive name
2. Add `__init__.py` with public exports
3. Keep related functionality together
4. Follow the pattern: `feature/__init__.py`, `feature/models.py`, `feature/services.py`

### Example: Adding a New API Route

```python
# src/progress/api/routes/new_feature.py
from fastapi import APIRouter

router = APIRouter(prefix="/new-feature", tags=["new-feature"])

@router.get("")
def list_items():
    ...
```

Then register in `src/progress/api/__init__.py`:

```python
from .routes.new_feature import router as new_feature_router
# In create_app():
app.include_router(new_feature_router, prefix="/api/v1")
```

---

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Package names | lowercase, underscores | `notification/`, `proposal_tracking/` |
| Module names | lowercase, underscores | `cli.py`, `db_models.py` |
| Class names | PascalCase | `ConfigException`, `RepositoryManager` |
| Function names | snake_case | `load_from_file()`, `get_timezone()` |
| Constants | UPPER_SNAKE_CASE | `DATABASE_PATH`, `PAGE_SIZE` |
| Private functions | Leading underscore | `_send_notification()` |

---

## Import Organization

All imports must be placed at the top of the file, grouped in this order:

1. Standard library imports
2. Third-party imports
3. Local application imports

Example from `cli.py`:

```python
import logging
import os
from datetime import datetime
from pathlib import Path, PurePath

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .ai.analyzers.claude_code import ClaudeCodeAnalyzer
from .config import Config
from .consts import DATABASE_PATH
```

---

## Examples

Well-organized modules to reference:

- **`notification/`** - Clean separation of channels, messages, and config
- **`api/routes/`** - Consistent FastAPI router pattern
- **`db/`** - Centralized database models and helpers
- **`config.py`** - Pydantic models for configuration validation
