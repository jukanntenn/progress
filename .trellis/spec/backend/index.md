# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This project is a **GitHub project tracking tool** built with:
- **Python 3.12+** with **uv** package manager
- **FastAPI** for web API
- **Peewee ORM** with SQLite
- **Click** for CLI
- **Pydantic** for configuration and validation

---

## Quick Reference

| Topic | Key Points |
|-------|-----------|
| Package manager | `uv sync`, `uv run` |
| CLI entry point | `src/progress/cli.py` |
| Config loading | Pydantic + TOML with env overrides |
| Database | Peewee ORM, SQLite, migrations in `db/` |
| API routes | FastAPI routers in `api/routes/` |
| Exceptions | Hierarchical in `errors.py` |
| Logging | Standard `logging`, rotating file handler |

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Filled |
| [Database Guidelines](./database-guidelines.md) | Peewee ORM patterns, queries, migrations | Filled |
| [Error Handling](./error-handling.md) | Exception hierarchy, handling strategies | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns, testing | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | Filled |

---

## Key Patterns

### Configuration

```python
# Load from TOML file with env override support
cfg = Config.load_from_file("config.toml")

# Access nested config
cfg.github.gh_token
cfg.analysis.concurrency
```

### Database

```python
# Initialize and cleanup
init_db(DATABASE_PATH)
create_tables()
try:
    # ... work ...
finally:
    close_db()

# Query patterns
repo = Repository.get_or_none(Repository.name == name)
reports = list(Report.select().paginate(page, PAGE_SIZE))
```

### CLI Commands

```python
@click.group()
def cli():
    """CLI entry point"""

@cli.command()
@click.option("--config", "-c", default="config.toml")
def check(config: str):
    """Run repository checks"""
```

### API Routes

```python
router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("", response_model=PaginatedResponse)
def list_items(page: int = 1):
    ...
```

---

## Common Commands

```bash
# Install dependencies
uv sync

# Run application
uv run progress -c config.toml

# Run tests
uv run pytest -v

# Start dev server
uv run progress -c config.toml serve --reload
```

---

**Language**: All documentation should be written in **English**.
