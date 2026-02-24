# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

This project uses **Peewee ORM** with **SQLite** as the database backend. The database layer is organized under `src/progress/db/` with models defined in `models.py`.

Key characteristics:
- SQLite for simplicity and portability
- Peewee ORM for model definitions and queries
- `DatabaseProxy` for deferred database binding (supports testing)
- Thread-safe metadata for concurrent access

---

## Query Patterns

### Basic Queries

```python
from progress.db.models import Repository, Report

# Get single record
repo = Repository.get_or_none(Repository.name == "vitejs/vite")

# Filter and order
reports = Report.select().where(
    Report.repo.is_null()
).order_by(Report.created_at.desc())

# Pagination
reports = list(query.paginate(page, page_size))

# Count
total = query.count()
```

### Update Operations

```python
# Update with query
Report.update(markpost_url=url).where(
    Report.id == report_id
).execute()

# Update via model instance
repo.last_commit_hash = new_hash
repo.save()
```

### Foreign Key Relationships

```python
# In models.py
class Report(BaseModel):
    repo = ForeignKeyField(
        Repository,
        backref="reports",      # Enables repo.reports
        on_delete="CASCADE",    # Cascade deletes
        null=True,
    )
```

### Batch Operations

```python
# Insert multiple records
Repository.insert_many(repos_data).execute()

# Bulk update
Repository.update(enabled=False).where(
    Repository.name.in_(disabled_repos)
).execute()
```

---

## Migrations

### Creating Migrations

1. Create a new migration file: `src/progress/db/migration_<description>.py`
2. Follow the pattern from existing migrations:

```python
# src/progress/db/migration_add_owner_monitoring.py
import logging

from peewee import BooleanField, CharField, TextField

logger = logging.getLogger(__name__)


def migrate():
    """Add owner monitoring fields."""
    from . import database
    from .models import Repository

    # Check if column exists
    cursor = database.execute_sql("PRAGMA table_info(repositories)")
    columns = [row[1] for row in cursor.fetchall()]

    if "owner_name" not in columns:
        database.add_column("repositories", "owner_name", CharField(null=True))
        logger.info("Added owner_name column to repositories")
```

3. Call the migration in `models.py`:

```python
def create_tables():
    database.create_tables([Repository, Report], safe=True)
    migrate_database()  # Runs all migrations
```

### Migration Order

Migrations run on every startup (idempotent). Each migration should:
1. Check if the change is already applied
2. Apply the change if needed
3. Log the result

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Table names | Plural, lowercase | `repositories`, `reports` |
| Model names | Singular, PascalCase | `Repository`, `Report` |
| Primary key | Auto-named `id` | `id = AutoField()` |
| Foreign keys | Singular model name | `repo`, `eip`, `rust_rfc` |
| Timestamp fields | `created_at`, `updated_at` | `created_at = DateTimeField()` |
| Boolean flags | `is_<state>` or `<state>` | `enabled`, `notified` |

---

## Model Definition Pattern

```python
class Repository(BaseModel):
    """Repository model"""

    name = CharField()
    url = CharField(unique=True)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "repositories"

    def save(self, *args, **kwargs):
        """Override save to auto-update updated_at"""
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)
```

---

## Database Initialization

```python
# In db/__init__.py
from .models import database_proxy, create_tables

def init_db(db_path: str):
    """Initialize database connection."""
    database = SqliteDatabase(db_path)
    database_proxy.initialize(database)
    return database

def close_db():
    """Close database connection."""
    from .models import database_proxy
    if not database_proxy.is_closed():
        database_proxy.close()
```

---

## Common Mistakes

### 1. Forgetting to close database connections

```python
# Wrong - connection left open
def some_function():
    init_db(DATABASE_PATH)
    # ... work ...
    # Missing close_db()

# Correct
def some_function():
    try:
        init_db(DATABASE_PATH)
        # ... work ...
    finally:
        close_db()
```

### 2. Not using `get_or_none` for optional lookups

```python
# Wrong - raises DoesNotExist exception
repo = Repository.get(Repository.name == name)

# Correct - returns None if not found
repo = Repository.get_or_none(Repository.name == name)
if repo is None:
    # Handle missing record
```

### 3. Querying before database initialization

```python
# Wrong - database_proxy not initialized
from progress.db.models import Repository
repo = Repository.get_or_none(...)  # Error!

# Correct - initialize first
from progress.db import init_db, create_tables
init_db(DATABASE_PATH)
create_tables()
# Now queries work
```

### 4. Not using `safe=True` in create_tables

```python
# Wrong - errors if tables exist
database.create_tables([Repository, Report])

# Correct - skips existing tables
database.create_tables([Repository, Report], safe=True)
```

---

## Testing with Database

Use temporary databases for tests:

```python
@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    create_tables()
    yield path
    close_db()
    os.unlink(path)
```
