# Configuration Refactor: File → Database

A full design and implementation record of the work that moved Progress's
application configuration out of the TOML file and into the database, killed the
Ansible‑vs‑web‑UI overwrite conflict, and retired the TOML list‑config bloat.

**Status:** complete (P1 + P2 + test fix + P3). Backend suite: **466 passing**;
frontend: tsc / lint / 7 vitest tests green.

**Commits** (oldest → newest):

| Hash | Message |
|---|---|
| `779dd88` | `feat(config): back app config with versioned DB blob and JSON Schema API` |
| `3d223df` | `feat(web): drive config editor from JSON Schema; track web/src/lib` |
| `41f2352` | `refactor(config): move repos/owners from the blob to their DB tables (P2)` |
| `aacef3d` | `feat(web): manage repos/owners as table-backed lists in the config editor` |
| `4b88bd0` | `test(repo): mock check_releases in repository-manager first-check tests` |
| `0a422c6` | `fix(docker): mount config.toml read-only` |
| `3382b19` | `docs(config): document the DB-backed config model (TOML = seed + infra)` |

---

## 1. The problem

Progress configured everything via a single `config.toml`. Two pain points drove
the refactor:

1. **Ansible ↔ web‑UI conflict.** `config.toml` was mounted read‑write into the
   container. The web UI edited it via `POST /config` (rewriting the file), and
   Ansible templated it from `config.toml.j2`. A re‑deploy silently clobbered
   changes a user had made through the UI.
2. **TOML list‑config bloat.** Complex list settings — `repos`, `owners`,
   `notification.channels`, `changelog_trackers`, `proposal_trackers` — were all
   declared in TOML, which grew large and hard to maintain.

A secondary smell: the form was driven by a **665‑line hardcoded**
`build_config_editor_schema()` in `src/progress/api/routes/config.py` that
duplicated the pydantic `Config` model — two sources of truth.

## 2. Design decisions

The direction was pinned down via a structured design review (the
`grill‑me‑sleek` interview). The agreed model:

- **Database is the single source of truth** for application config. The TOML
  file is a **one‑time seed** plus the provider of **infrastructure** settings.
  After the first run the file's app‑config is ignored; crossing file↔DB is an
  **explicit** action (`progress config import` / `export`).
- **File/env keeps only true bootstrap** — `data_dir`, `workspace_dir`, db path,
  server bind/port, schedule cron, log level — the keys needed *before* the
  database can be opened (chicken‑and‑egg). Everything else (incl. `gh_token`,
  channels, repos, analysis) lives in the DB.
- **Ansible** manages only docker‑compose, the infra/seed TOML (first deploy),
  and secrets/vault. Re‑running it can no longer clobber runtime config because
  the app ignores the file's app‑config after seeding.
- **DB storage shape — hybrid:** scalar/nested settings in **one versioned JSON
  blob** (`app_config` table); `repos`/`owners` in their **existing structured
  tables** (`repositories` / `github_owners`), which already carry runtime state
  (`last_commit_hash`, `last_check_time`, …).
- **Optimistic locking** via a `version` integer on the blob (bili‑sync pattern);
  stale writes return `409`.
- **Schema source of truth:** pydantic‑first — keep the `Config` models
  canonical, emit JSON Schema via `model_json_schema()` enriched with UI hints,
  **delete** the hardcoded editor schema. Discriminated unions (notification
  channels) → JSON Schema `oneOf` via pydantic.
- **Secrets** stored in the DB, masked (`********`) in every GET; schema marks
  them `writeOnly` + `format: password`; a write updates a secret only when the
  submitted value differs from the mask.
- **Reload timing:** app config is read from the DB at the start of each
  scheduled tracking run and at API‑server startup — web‑UI changes apply on the
  next run, no restart.
- **Rollout:** phased (P1 blob + schema API → P2 repos/owners tables → P3
  deprecate TOML app‑config). Each phase shipped independently.

### Reference projects studied

- **bili‑sync** (Rust): pure‑DB config (file removed in 2.6.0); one JSON blob +
  a `version` integer for optimistic locking + watch channels for hot reload.
- **axonhub** (Go): dual‑layer, non‑overlapping — file (Viper) = infra/bootstrap
  only, **never written back**; DB `System` key‑value table (JSON values) = app
  behavior with cache invalidation. No merge/conflict because keys don't overlap.
- **JSON Schema spec** (`json-schema-spec`, v1/2026): `oneOf` + `const` for
  discriminated unions; `$ref`/`$defs` for reuse; `writeOnly`/`readOnly`/`format`
  for UI hints; UI widgets are **not** in core spec (ride on `format` /
  `json_schema_extra`).

## 3. Architecture

```
                       ┌─────────────────────────────────────────────┐
 config.toml (seed)    │  Infrastructure only at runtime:            │
 + env vars    ───────▶│  data_dir, workspace_dir, db path, schedule │
                       └───────────────┬─────────────────────────────┘
                                       │ first run only: seeds DB
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  Database (SQLite)                                            │
   │  ┌─────────────────────────┐   ┌───────────────────────────┐  │
   │  │ app_config (1 row)      │   │ repositories / github_owners│ │
   │  │  data JSON, version,    │   │  (url/branch/enabled +     │  │
   │  │  schema_version         │   │   runtime state)           │  │
   │  └─────────────┬───────────┘   └─────────────┬─────────────┘  │
   └────────────────┼─────────────────────────────┼────────────────┘
                    │                              │
        GET/POST /config              GET/PUT /config/repos
        GET /config/schema            GET/PUT /config/owners
                    │                              │
                    ▼                              ▼
            web UI Configuration page      web UI Repositories / Owners
            (driven by JSON Schema)         (table-backed lists)
```

- **Infra** is read every startup (env > file > defaults) because it's needed to
  open the DB.
- **App settings blob** is the source of truth after seeding; edited via the web
  UI / API under optimistic locking.
- **Repos/owners tables** are the source of truth for those entities; edited via
  dedicated read/replace endpoints.
- The TOML file is **read once** to seed, then ignored for app config.

## 4. Implementation

### Phase 1 — DB‑backed config blob + JSON‑Schema API (`779dd88`, `3d223df`)

**Backend**

- **`src/progress/db/models.py`** — new `AppConfig` model: single row
  (`id = 1`) with `version`, `schema_version`, `data` (JSON `TextField`),
  `updated_at`. Registered in `create_tables()` (`src/progress/db/__init__.py`).
- **`src/progress/config_store.py`** (new, ~390 lines) — the store:
  - `get_config_json_schema()` — `Config.model_json_schema()` with infra fields
    removed and `schemaVersion` stamped on.
  - `load_app_config()` → `(data, version)` or `None` (unseeded).
  - `seed_app_config_if_needed(seed_data)` — one‑shot file→blob seed.
  - `save_app_config(data, expected_version)` — validate, optimistic‑lock
    (`UPDATE … WHERE version = expected`, bump), return `(merged, new_version)`;
    raises `ConfigVersionConflict` on stale version.
  - `mask_secrets(data)` — schema‑driven walk (`writeOnly`/`format: password`,
    resolves `$ref`, `oneOf` discriminator, arrays) replacing secrets with
    `SECRET_MASK`.
  - `_merge_secret_placeholders(submitted, stored)` — restores stored secrets
    where the submission kept the mask, so unchanged secrets round‑trip.
  - `build_runtime_config(blob, infra)` — assemble the runtime `Config` from the
    blob plus infra fields.
  - `validate_config_dict(data)`, `import_app_config(data)`.
  - Constants: `APP_CONFIG_ID = 1`, `CURRENT_SCHEMA_VERSION`, `SECRET_MASK`,
    `INFRA_FIELDS`, `EXCLUDED_FROM_BLOB`, `ConfigVersionConflict`.
- **`src/progress/config.py` + `notification/config.py`** — added `Field(...)`
  metadata (titles, descriptions) and marked secrets (`gh_token`, Feishu
  `webhook_url`, email `password`, Markpost `url`) with
  `json_schema_extra={"format": "password", "writeOnly": True}`; `timezone` gets
  `format: "timezone"`. Notification channels were already a pydantic
  discriminated union, so the schema emits a clean `oneOf`.
- **`src/progress/api/routes/config.py`** — rewritten: `GET /config` →
  `{data, version}` (masked); `POST /config` → optimistic save (`409` on stale,
  `400` on validation); `GET /config/schema` → JSON Schema; `POST /config/validate`;
  `GET /config/timezones`. The 665‑line `build_config_editor_schema()` and the
  `editor_schema` module were **deleted**.
- **`src/progress/cli.py`** — `initialize_components()` now seeds the blob then
  builds the runtime `Config` from it (returns the runtime config to callers);
  new `progress config import` (file→DB) and `progress config export` (DB→file)
  commands.
- **`src/progress/api/__init__.py`** — `create_app()` seeds the blob and builds
  the runtime config at startup.

**Frontend**

- **`web/src/lib/config/schemaAdapter.ts`** — converts the served JSON Schema
  (top‑level properties, `$ref`/`$defs`, discriminated `oneOf` channels) into the
  `SectionSchema`/`FieldSchema` shapes the existing `ConfigSections` renderer
  already consumes (`object_list`, `discriminated_object_list`, `string_list`,
  `select`, `password`, `timezone`, …) — so the working list/discriminator UI is
  reused unchanged. Unit‑tested in `schemaAdapter.test.ts`.
- **`web/src/lib/api/config.ts`** — `{data, version}` payload, JSON‑Schema
  fetch, optimistic save (sends `version`, surfaces `409` by refetching),
  validation; TOML editing dropped.
- **`web/src/app/config/page.tsx`** — visual‑only editor with version tracking
  and a `409` refresh path; TOML mode removed (file no longer authoritative).
- **`.gitignore`** — fixed a pre‑existing bug: the Python‑boilerplate `lib/`
  pattern was hiding `web/src/lib`, so the frontend API client/utils/config
  source had **never been tracked**. Added `!web/src/lib/` and committed the
  directory (previously‑untracked source plus the new adapter).

**Two test‑infrastructure bugs found & fixed during P1**

1. **`.gitignore` `lib/` false‑positive** (above) — the active frontend's
   `web/src/lib` was entirely untracked while `web/src/app/**` imported from it.
2. **Pooled‑DB connection leak.** `close_db()` closes only the *current thread's*
   connection; the new config endpoints opened `AppConfig` connections on
   Starlette worker threads that weren't reclaimed, stalling a later
   `test_github` DB write. Fixed by closing all pooled connections in the test
   fixtures' teardown.

### Phase 2 — repos/owners → DB tables (`41f2352`, `aacef3d`)

**Backend**

- `repos` and `owners` removed from the blob (`EXCLUDED_FROM_BLOB` now includes
  them); `schema_version` bumped to **2** with a one‑time
  `migrate_blob_schema()` that strips any inline repos/owners from existing P1
  blobs.
- **`replace_repositories(desired, default_protocol)`** and
  **`replace_owners(desired)**`** added to `src/progress/contrib/repo/` —
  no‑network upsert + prune (owners keep their `enabled` flag instead of being
  deleted). These back the UI, `progress config import`, and first‑run seeding.
- The per‑run `repo_manager.sync(cfg.repos)` / `owner_manager.sync_owners()`
  **calls were removed** from the `check` command — tracking already reads from
  the tables via `list_enabled()` / `check_all()`. (`cfg.repos`/`cfg.owners` were
  only ever used by those sync calls.)
- `seed_lists_if_needed(file_cfg)` seeds the tables from the file on a fresh
  deploy (no‑op once populated); `create_app` and `_resolve_runtime_config` run
  it; `progress config import` also replaces repos/owners.
- New endpoints **`GET/PUT /config/repos`** and **`GET/PUT /config/owners`**
  (replace semantics; invalid input → `422`).

**Frontend**

- **`web/src/components/config/TableListSection.tsx`** — a table‑backed list
  section with its own per‑section Save (PUT replace), reusing the now‑exported
  `ObjectListField`. The page renders *Repositories* and *Owners* sections from
  `GET/PUT /config/{repos,owners}`, wired into the page nav + modification
  tracking. `useRepos`/`useOwners` hooks + `configKeys.repos/owners` added.

### Test fix — mock `check_releases` (`4b88bd0`)

Two `test_github.py` first‑check tests mocked `Repo.clone_or_update`/`Repo.update`
but **not** `Repo.check_releases`, so `manager.check()` fell through to a **live
anonymous GitHub API call** (PyGithub has no default timeout) and hung
indefinitely under degraded network/rate‑limiting — stalling the whole suite.
Mocked `check_releases` to return `None` (matching the sibling first‑check
test). The full suite now runs reliably (~4.6s, no hangs).

### Phase 3 — TOML as seed/infra (`0a422c6`, `3382b19`)

The conflict was already gone functionally (P1/P2); P3 makes the seed role
explicit and safe.

- **`docker/docker-compose.yml`** — `config.toml` mounted **read‑only** (the app
  no longer writes it; matches the README's documented `:ro` mount).
- **`guides/config.md`** — rewritten for the DB‑backed model (infra vs app vs
  tables, seed behavior, web UI editing, import/export, secret masking,
  precedence); feature notes reframed as DB‑managed.
- **`README.md` / `README_zh.md`** — Configuration sections describe the seed
  role and DB‑as‑source‑of‑truth; TOML examples retained as seed‑file reference.
- **`config.example.toml`** — header explains the seed+infra role and first‑run
  behavior.
- **`devops/ansible/templates/config.toml.j2`** — note that it is a first‑deploy
  seed and re‑running the template won't clobber DB edits.
- **`CLAUDE.md`** — dropped the stale `config/` directory entry, added
  `config_store.py` / the `db` package, and a *Configuration Architecture*
  section for future sessions.

## 5. Key files

| File | Role |
|---|---|
| `src/progress/config_store.py` | DB blob store: load/save, optimistic lock, seeding, migration, masking, schema, import/export |
| `src/progress/config.py` | Canonical pydantic `Config` models (schema source of truth; secret/timezone hints) |
| `src/progress/db/models.py` | `AppConfig` single‑row model |
| `src/progress/api/routes/config.py` | Blob + repos/owners endpoints, JSON Schema |
| `src/progress/contrib/repo/repository.py` | `replace_repositories()` (no‑network upsert+prune) |
| `src/progress/contrib/repo/owner.py` | `replace_owners()` |
| `src/progress/cli.py` | `_resolve_runtime_config`, `config import/export`, removed sync calls |
| `web/src/lib/config/schemaAdapter.ts` | JSON Schema → editor field shapes |
| `web/src/components/config/TableListSection.tsx` | Table‑backed repos/owners editor |
| `web/src/app/config/page.tsx` | Config page (blob editor + repos/owners) |
| `guides/config.md` | Canonical user/operator doc |

Deleted: `src/progress/editor_schema.py`, `tests/test_editor_schema.py`.

## 6. Testing

- **Backend:** 466 tests pass (`uv run pytest -q`, ~4.6s). New tests in
  `tests/test_config_store.py` (blob lifecycle, optimistic lock, masking round‑
  trip, schema exclusion, `migrate_blob_schema`, `seed_lists_if_needed`) and
  `tests/api/test_config.py` (blob + repos/owners endpoints).
- **Frontend:** `web/src/lib/config/schemaAdapter.test.ts` (7 tests) +
  `pnpm exec tsc --noEmit` clean + ESLint clean (one pre‑existing unrelated
  `compat` error in `eslint.config.mjs`).
- **Two test‑infra issues encountered and resolved:** the peewee‑pool connection
  leak (P1, fixed via full‑pool teardown) and the live‑network `check_releases`
  hang (fixed by mocking).

## 7. Known limitations / possible follow‑ups

- **`RepositoryManager.sync` / `OwnerManager.sync_owners` are now superseded**
  (the app uses `replace_repositories`/`replace_owners`). `sync_owners` is still
  covered by `tests/test_owner.py`; both are retained. Could be removed in a
  later cleanup.
- **Per‑repo protocol override** is not exposed in the repos CRUD UI; effective
  protocol is derived from the URL format + global `github.protocol`
  (`repo.py::_get_effective_protocol`), matching the prior sync behavior (which
  also never persisted a protocol column). Add a `protocol` column + UI if
  per‑repo SSH overrides are needed.
- **Owner‑discovered repos remain ephemeral** (report + notification only, not
  added to `repositories`). A "promote discovered → tracked" UI action is a
  possible enhancement.
- **App‑config env overrides are captured at seed time only.** Intentional (DB
  is sole source of truth); re‑import with `progress config import` to refresh.
- The legacy `src/progress/web/` frontend tree (SWR‑based) was left untouched;
  the active frontend is the root `web/`.

## 8. Operator summary

- **First deploy:** ship a `config.toml` (copy `config.example.toml`) with infra
  + the initial app config; the first run seeds the database.
- **Ongoing edits:** use the web UI (Configuration page; Repositories/Owners
  sections) — never edit the file expecting it to take effect.
- **File↔DB migration:** `progress config import` (file→DB, overwrites),
  `progress config export` (DB→file).
- **Ansible** only manages the seed file + secrets + compose; re‑running it does
  not affect the running configuration.
