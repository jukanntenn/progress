# PRFC: Configuration lives in the database; the TOML file is a one-time seed

Status: implemented

English | [中文](2026-06-26-config-database-single-source.zh.md)

## Problem

Progress configured everything through a single writable `config.toml` mounted into the container, and that shape failed twice. The web UI edited the file via `POST /config` while Ansible templated it from `config.toml.j2`, so every re-deploy silently clobbered changes a user had made through the UI — the deploy pipeline and the runtime fought over one file. And complex list settings — `repos`, `owners`, `notification.channels`, `changelog_trackers`, `proposal_trackers` — were all declared in TOML, which grew large and hard to maintain. A secondary smell: the web config editor was driven by a 665-line hand-written schema in `src/progress/api/routes/config.py` duplicating the pydantic model — two sources of truth for one form.

## Decision

**The database is the single source of truth for application config.** The TOML file is a one-time seed plus the provider of infrastructure settings; after the first run the file's app-config is ignored, and crossing file↔DB is an explicit action (`progress config import` / `export`).

**File and environment keep only true bootstrap settings** — `data_dir`, `workspace_dir`, the db path, server bind/port, schedule cron, log level — the keys needed before the database can be opened. Everything else (including `gh_token`, channels, repos, analysis) lives in the DB, editable through the web UI against the JSON Schema generated from the pydantic model (`get_config_json_schema()`), which closed the hand-written-schema duplication.

**DB storage is hybrid:** scalar and nested settings in one versioned JSON blob (the `app_config` table, with optimistic-lock version and secret masking on read); `repos` and `owners` in their existing structured tables (`repositories` / `github_owners`), which already carry runtime state (`last_commit_hash`, `last_check_time`).

**Ansible manages only docker-compose, the infra/seed TOML of the first deploy, and secrets/vault** — re-running it can never clobber runtime config, because the app ignores the file's app-config after seeding.

## Alternatives considered

**Keep the writable TOML file and coordinate writers.** It lost: the Ansible↔UI conflict is inherent to two owners of one file; sequencing or locking deploys around UI edits puts a distributed-systems problem where a single-source design removes it.

**Move bootstrap settings into the DB too.** It lost: chicken-and-egg — the db path and bind address are needed before the database can be opened; a bootstrap subset in file/env is the minimum that can exist.

**One row per config key instead of a versioned blob.** It lost: scalar/nested settings have no per-key runtime state, so per-key rows buy querying nothing while multiplying migration surface; `repos`/`owners` keep structured tables precisely because they do carry runtime state.

## Consequences

The config editor renders from the generated JSON Schema (one source of truth with the pydantic model); UI edits persist to the DB with optimistic locking (stale version → HTTP 409), secrets round-trip masked, and a restart never re-seeds an existing DB. The refactor's point-in-time documents (`docs/config-refactor.md`, `docs/verification-config-refactor.md`) were deleted once this record carried the durable why; current-state detail lives in `specs/redesign/02-config-system.md` and `docs/config.md`.
