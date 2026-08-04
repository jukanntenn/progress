#!/usr/bin/env python3
"""One-shot migration from the legacy peewee DB to the redesign tortoise DB.

The legacy DB (peewee, pre-redesign) and the new DB (tortoise-orm) share the
same SQLite backend and compatible datetime on-disk format, but differ in a
few table names (``batch``→``batches``, ``proposal_trackers``→
``proposal_tracker_states``) and in how configuration is stored: the legacy
schema keeps editable app config in a single ``app_config.data`` JSON blob,
while the redesign splits it into per-section rows in a ``config`` table.

This script is **idempotent against an empty new DB only** — it refuses to
write into a new DB that already holds data, so a re-run never clobbers live
state. It migrates:

- all state tables (repositories / reports / batches / owners / changelog and
  proposal trackers / proposals) verbatim (column-for-column),
- the legacy ``app_config.data`` blob into the new ``config`` table, split into
  the ``core`` / ``repo`` / ``changelog`` / ``proposal`` sections.

Field-level mapping was validated against a real production dump. Notable
transforms:
  - ``notification.channels[].timeout`` (feishu) is dropped — not in the new
    schema (``extra="forbid"`` would reject it).
  - ``repositories``/``github_owners`` rows are also projected into the
    ``repo`` config section so the tracker's reconcile pass does not GC them.
  - ``github.proxy`` is carried over (restored in the new ``GitHubConfig``).
  - ``analysis`` is left empty (provider/model/api_key filled via the Web UI —
    the legacy ``claude_code`` CLI provider has no redesign equivalent).

Usage (inside the repo, where ``src/`` is importable)::

    uv run python scripts/migrate_from_legacy.py --old /path/to/old/progress.db --new /path/to/new/progress.db
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path
import sqlite3
import sys
from typing import Any

from tortoise import Tortoise

from progress.config.root import CoreConfig
from progress.db.models.report import Report
from progress.db.tortoise_config import build_tortoise_config
from progress.integrations.registry import discover_integrations
from progress.utils.timezone import now_utc

logger = logging.getLogger("migrate")


# Legacy table name -> (new table name, ordered column list to copy verbatim).
# Column order matches the new tortoise schema so INSERT lines up with columns.
TABLE_MAP: list[tuple[str, str, list[str]]] = [
    (
        "repositories",
        "repositories",
        [
            "id",
            "name",
            "url",
            "branch",
            "enabled",
            "last_commit_hash",
            "last_check_time",
            "last_release_tag",
            "last_release_commit_hash",
            "last_release_check_time",
            "created_at",
            "updated_at",
        ],
    ),
    (
        "reports",
        "reports",
        [
            "id",
            "report_type",
            "repo_id",
            "title",
            "commit_hash",
            "previous_commit_hash",
            "commit_count",
            "markpost_url",
            "content",
            "created_at",
        ],
    ),
    (
        "batch",
        "batches",
        ["id", "report_id", "title", "markpost_url", "seq", "created_at", "updated_at"],
    ),
    (
        "github_owners",
        "github_owners",
        [
            "id",
            "owner_type",
            "name",
            "enabled",
            "last_check_time",
            "last_tracked_repo",
            "created_at",
            "updated_at",
        ],
    ),
    (
        "changelog_trackers",
        "changelog_trackers",
        [
            "id",
            "name",
            "url",
            "parser_type",
            "enabled",
            "last_seen_version",
            "last_check_time",
            "created_at",
            "updated_at",
        ],
    ),
    (
        "proposal_trackers",
        "proposal_tracker_states",
        ["id", "kind", "last_seen_commit", "last_check_time", "created_at", "updated_at"],
    ),
    (
        "proposals",
        "proposals",
        ["id", "tracker_id", "number", "title", "raw_status", "status", "created_at", "updated_at"],
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", required=True, help="Path to the legacy peewee progress.db (read-only).")
    parser.add_argument(
        "--new", required=True, help="Path to the new tortoise progress.db (created/overwritten schema)."
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging.")
    return parser.parse_args()


def setup_logging(verbose: bool = False) -> None:
    handler_out = logging.StreamHandler(sys.stdout)
    handler_out.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler_out.addFilter(lambda record: record.levelno <= logging.INFO)
    handler_err = logging.StreamHandler(sys.stderr)
    handler_err.setLevel(logging.WARNING)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[handler_out, handler_err])


def strip_feishu_timeout(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop ``timeout`` from feishu channels (not in the new schema)."""
    out: list[dict[str, Any]] = []
    for ch in channels:
        if ch.get("type") == "feishu" and "timeout" in ch:
            ch = {k: v for k, v in ch.items() if k != "timeout"}  # noqa: PLW2901
        out.append(ch)
    return out


def build_core_section(blob: dict[str, Any]) -> dict[str, Any]:
    """Project the legacy app_config blob into the new ``core`` config section."""
    github = blob.get("github", {})
    markpost = blob.get("markpost", {})
    channels = blob.get("notification", {}).get("channels", [])
    return {
        "language": blob.get("language", "en"),
        "timezone": blob.get("timezone", "UTC"),
        "github": {
            "gh_token": github.get("gh_token", ""),
            "proxy": github.get("proxy", ""),
        },
        # analysis left empty — filled via Web UI after migration.
        "markpost": {
            "enabled": markpost.get("enabled", False),
            "url": markpost.get("url", ""),
            "max_batch_size": markpost.get("max_batch_size", 1048576),
        },
        "notification": {"channels": strip_feishu_timeout(channels)},
        # web/observability left empty — infrastructure, filled via Web UI.
    }


def build_repo_section(old: sqlite3.Connection) -> dict[str, Any]:
    """Build the ``repo`` config section from the repositories/github_owners tables.

    The tracker's reconcile pass deletes rows absent from this section, so it
    MUST mirror every tracked repo/owner — otherwise migrated checkpoints are
    GC'd on first run.
    """
    repos = [
        {"url": r[0], "branch": r[1], "enabled": bool(r[2])}
        for r in old.execute("SELECT url, branch, enabled FROM repositories ORDER BY id").fetchall()
    ]
    owners = [
        {"type": o[0], "name": o[1], "enabled": bool(o[2])}
        for o in old.execute("SELECT owner_type, name, enabled FROM github_owners ORDER BY id").fetchall()
    ]
    return {"repos": repos, "owners": owners, "first_run_lookback_commits": 3}


def build_changelog_section(blob: dict[str, Any]) -> dict[str, Any]:
    return {"trackers": blob.get("changelog_trackers", [])}


def build_proposal_section(blob: dict[str, Any]) -> dict[str, Any]:
    return {"trackers": blob.get("proposal_trackers", [])}


async def advance_owner_watermarks(conn, *, days: int = 3) -> None:

    new_watermark = (now_utc() - timedelta(days=days)).isoformat()
    rows = (await conn.execute_query("SELECT id, name, last_tracked_repo FROM github_owners"))[1]
    count = 0
    for row in rows:
        owner_id, name, old_value = row[0], row[1], row[2]
        await conn.execute_query(
            "UPDATE github_owners SET last_tracked_repo = ? WHERE id = ?",
            [new_watermark, owner_id],
        )
        logger.info("  owner %s watermark: %s -> %s", name, old_value or "(empty)", new_watermark)
        count += 1
    logger.info("advanced %d owner watermarks to %s (now - %dd)", count, new_watermark, days)


async def new_db_is_empty(db_url: str) -> bool:
    """True if the new DB has no migrated state tables yet."""

    await Tortoise.init(config=build_tortoise_config(db_url), _enable_global_fallback=True)
    try:
        return await Report.all().count() == 0
    finally:
        await Tortoise.close_connections()


async def migrate(args: argparse.Namespace) -> int:
    old_path = Path(args.old)
    new_path = Path(args.new)
    if not old_path.exists():
        logger.error("legacy DB not found: %s", old_path)
        return 2

    new_path.parent.mkdir(parents=True, exist_ok=True)
    # ``--new`` is the DB file path directly (not a state_home dir). The new app
    # always reads ``<state_home>/progress.db``, so in production you typically
    # pass ``<state_home>/progress.db`` here. We build the URL pointing at the
    # exact file (with the same WAL pragmas as build_db_url) rather than going
    # through build_db_url, which hardcodes the ``progress.db`` name.
    new_db_url = (
        f"sqlite://{new_path}?journal_mode=WAL&synchronous=NORMAL&busy_timeout=5000&foreign_keys=ON&cache_size=-64000"
    )

    # Safety: refuse to clobber a new DB that already holds reports.
    if new_path.exists() and not await new_db_is_empty(new_db_url):
        logger.error(
            "new DB %s already contains data — refusing to overwrite. "
            "Drop it first (rm %s*) if you really want a fresh migration.",
            new_path,
            new_path,
        )
        return 2

    old = sqlite3.connect(str(old_path))
    old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    old.row_factory = sqlite3.Row
    blob_row = old.execute("SELECT data FROM app_config WHERE id = 1").fetchone()
    if blob_row is None:
        logger.warning("no app_config row in legacy DB — migrating state tables only")
        blob: dict[str, Any] = {}
    else:
        blob = json.loads(blob_row["data"])

    await Tortoise.init(config=build_tortoise_config(new_db_url), _enable_global_fallback=True)
    await Tortoise.generate_schemas()
    conn = Tortoise.get_connection("default")

    logger.info("migrating state tables...")
    copied: dict[str, tuple[int, int]] = {}
    for old_table, new_table, cols in TABLE_MAP:
        rows = old.execute(f"SELECT {', '.join(cols)} FROM {old_table}").fetchall()
        placeholders = ",".join(["?"] * len(cols))
        for row in rows:
            await conn.execute_query(
                f'INSERT OR REPLACE INTO "{new_table}" ({", ".join(cols)}) VALUES ({placeholders})',
                list(row),
            )
        old_count = old.execute(f"SELECT COUNT(*) FROM {old_table}").fetchone()[0]
        copied[new_table] = (len(rows), old_count)
        logger.info("  %-26s %d rows (legacy %d)", new_table, len(rows), old_count)

    logger.info("migrating config sections...")
    sections = {
        "core": build_core_section(blob),
        "repo": build_repo_section(old),
        "changelog": build_changelog_section(blob),
        "proposal": build_proposal_section(blob),
    }
    for name, data in sections.items():
        validated = _validate_section(name, data)
        await conn.execute_query(
            'INSERT OR REPLACE INTO "config" (section, data, updated_at) VALUES (?, ?, datetime("now"))',
            [name, json.dumps(validated, separators=(",", ":"))],
        )
        logger.info("  config[%s] %d bytes", name, len(json.dumps(validated)))

    old.close()

    await advance_owner_watermarks(conn)

    # Verification report.
    logger.info("verification:")
    ok = True
    for new_table, (_migrated, legacy) in copied.items():
        actual = (await conn.execute_query(f'SELECT COUNT(*) FROM "{new_table}"'))[1][0][0]
        status = "OK" if actual == legacy else "MISMATCH"
        if status != "OK":
            ok = False
        logger.info("  %-26s new=%d legacy=%d [%s]", new_table, actual, legacy, status)

    await Tortoise.close_connections()
    if not ok:
        logger.error("row-count verification failed — inspect the new DB before using it")
        return 1
    logger.info("migration complete: %s", new_path)
    return 0


def _validate_section(section: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate a config section through the new schema before persisting.

    Mirrors ``progress.db.set_config`` semantics: the ``core`` section is stored
    verbatim (SecretStr fields stay plaintext, matching what the Web UI/API
    round-trips) — only validated, not re-dumped, because
    ``CoreConfig.model_dump(mode="json")`` masks SecretStr to ``"**********"``
    and would erase the real gh_token/webhook_url being migrated.
    """
    if not isinstance(data, dict):
        raise ValueError(f"config section '{section}' payload must be a JSON object")
    if section == "core":
        CoreConfig.model_validate(data)  # validate only; persist original dict
        return data

    integration_cls = discover_integrations().get(section)
    if integration_cls is None:
        return data
    config_schema = getattr(integration_cls, "config_schema", None)
    if config_schema is None:
        return data
    validated = config_schema.model_validate(data)
    return validated.model_dump(mode="json")


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    if str(Path("src")) not in sys.path:
        sys.path.insert(0, "src")
    return asyncio.run(migrate(args))


if __name__ == "__main__":
    raise SystemExit(main())
