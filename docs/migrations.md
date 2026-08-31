# Database Migrations

Progress uses [tortoise-orm](https://github.com/tortoise/tortoise-orm)'s built-in migration CLI (`python -m tortoise`). Aerich does not support tortoise-orm ≥1.0; this project does **not** use it.

Migrations live per-app, next to each app's models:

| App label | Migrations directory |
|-----------|----------------------|
| `core` | `src/progress/db/migrations/` |
| `repo` | `src/progress/integrations/repo/migrations/` |
| `changelog` | `src/progress/integrations/changelog/migrations/` |
| `proposal` | `src/progress/integrations/proposal/migrations/` |
| `feed` | `src/progress/integrations/feed/migrations/` |

The app labels are derived from `build_tortoise_config()` in `src/progress/db/tortoise_config.py`, so a new integration is picked up automatically once it registers a `models_module` / `migrations` package.

## Wrapper

The long `uv run tortoise -c progress.db.tortoise_config.TORTOISE_ORM ...` is wrapped by `scripts/migration.py`. Use it instead of calling tortoise directly:

| Command | What it does |
|---------|--------------|
| `make <name>` | Generate a migration from model changes (`<name>` required, semantic). |
| `apply` | Apply pending migrations to the DB. |
| `sql <app> <id>` | Print the SQL for a migration (preview, no DB change). |
| `down <app> [id]` | Roll back; default to the previous migration. |
| `drift` | Regenerate, diff against committed files, restore. Exits non-zero on drift. |

## Workflow

### 1. Change a model

Edit the tortoise model in the owning package (e.g. `src/progress/db/models/report.py`).

### 2. Generate the migration

```bash
uv run python scripts/migration.py make add_report_index
```

The `<name>` is required and becomes part of the file name (`0002_add_report_index.py`). Always use a semantic name — never commit the default timestamped name.

### 3. Preview the SQL before applying

```bash
uv run python scripts/migration.py sql core 0002_add_report_index
```

Inspect the output to make sure the generated DDL matches the intent.

### 4. Apply locally

```bash
uv run python scripts/migration.py apply
```

Startup (`init_db`) also applies pending migrations automatically, so the next `uv run progress run` / `serve` will apply them too.

### 5. Commit the migration file

The new `migrations/<app>/000N_<name>.py` is a source artifact — commit it alongside the model change. One model change = one migration file.

### 6. CI checks for drift

`ci.yml`'s drift-checks job runs `scripts/migration.py drift`: it snapshots the committed migrations, regenerates them, and diffs. A model change without a matching migration file fails the check:

```
migration drift detected: run `uv run python scripts/migration.py make <name>`
and commit the generated migration.
```

Run `drift` locally before pushing to catch it early:

```bash
uv run python scripts/migration.py drift
```

## Rollback

```bash
uv run python scripts/migration.py down core                 # previous migration
uv run python scripts/migration.py down core 0001_initial    # specific target
```

Downgrades mutate the DB schema; the migration files on disk are **not** deleted.

## Adding a new integration app

When a new integration registers a `models_module` and a `migrations` package, its app label appears in `build_tortoise_config()["apps"]` automatically. Generate the initial migration with the app label:

```bash
uv run python scripts/migration.py make initial
```

The wrapper derives migration directories from the live config, so `drift` will include the new app without any hardcoded list to update.
