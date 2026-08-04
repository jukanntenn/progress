#!/usr/bin/env python3
"""Thin wrapper over the tortoise-orm migration CLI.

Tortoise-orm ships its own migration CLI (``python -m tortoise``); aerich is
deprecated for tortoise>=1.0. This script wraps the long
``uv run tortoise -c progress.db.tortoise_config.TORTOISE_ORM <cmd>`` invocation
behind short, memorable subcommands and enforces a semantic naming convention
for generated migrations.

Subcommands:
    make [name]      Generate a migration from model changes (name required).
    apply            Apply pending migrations to the DB.
    sql <app> <id>   Print the SQL for a migration (preview, no DB change).
    down <app> [id]  Roll back; default to the previous migration.
    drift            Detect migration drift: regenerate in place, diff against
                     the committed files, clean up. Exits non-zero on drift.

Usage:
    uv run python scripts/migration.py make add_report_index
    uv run python scripts/migration.py apply
    uv run python scripts/migration.py sql core 0001_initial
    uv run python scripts/migration.py down core
    uv run python scripts/migration.py drift
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from progress.db.tortoise_config import _get_tortoise_orm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TORTOISE_CONFIG = "progress.db.tortoise_config.TORTOISE_ORM"
# App labels are derived from the tortoise config so the drift check never goes
# stale when an integration is added/removed. Built lazily to avoid importing
# the app at module load.
_APP_LABELS_CACHE: list[str] | None = None


def _tortoise(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``uv run tortoise -c <config> <args>`` in the project root."""
    return subprocess.run(
        ["uv", "run", "tortoise", "-c", TORTOISE_CONFIG, *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )


def _app_labels() -> list[str]:
    """Return the app labels configured in TORTOISE_ORM (core + integrations)."""
    global _APP_LABELS_CACHE
    if _APP_LABELS_CACHE is None:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))

        _APP_LABELS_CACHE = sorted(_get_tortoise_orm()["apps"].keys())
    return _APP_LABELS_CACHE


def _migration_dirs() -> list[Path]:
    """Return the committed migrations directories for every app."""
    labels = _app_labels()
    dirs: list[Path] = []
    for label in labels:
        if label == "core":
            dirs.append(PROJECT_ROOT / "src" / "progress" / "db" / "migrations")
        else:
            dirs.append(PROJECT_ROOT / "src" / "progress" / "integrations" / label / "migrations")
    return [d for d in dirs if d.exists()]


def _run_live(*args: str) -> int:
    """Run tortoise with inherited stdio (interactive output, exit code)."""
    return subprocess.run(
        ["uv", "run", "tortoise", "-c", TORTOISE_CONFIG, *args],
        cwd=str(PROJECT_ROOT),
    ).returncode


def cmd_make(args: argparse.Namespace) -> int:
    if not args.name:
        print("error: `make` requires a migration name, e.g. `make add_report_index`", file=sys.stderr)
        return 2
    return _run_live("makemigrations", "-n", args.name)


def cmd_apply(_args: argparse.Namespace) -> int:
    return _run_live("migrate")


def cmd_sql(args: argparse.Namespace) -> int:
    return _run_live("sqlmigrate", args.app, args.migration)


def cmd_down(args: argparse.Namespace) -> int:
    cmd = ["downgrade", args.app]
    if args.migration:
        cmd.append(args.migration)
    return _run_live(*cmd)


def cmd_drift(_args: argparse.Namespace) -> int:
    """Detect migration drift: snapshot, regenerate, diff, restore.

    A model change without a matching migration file shows up as a new/changed
    ``.py`` in the diff. Exits 0 when committed migrations match a fresh
    ``makemigrations`` run, non-zero otherwise. The working tree is restored
    even on failure so no stray generated files are left behind.
    """
    dirs = _migration_dirs()
    if not dirs:
        print("no migration directories found", file=sys.stderr)
        return 1

    snapshot_root = Path(tempfile.mkdtemp(prefix="migration-drift-"))
    try:
        # Snapshot committed .py files (skip __pycache__).
        for d in dirs:
            rel = d.relative_to(PROJECT_ROOT)
            dest = snapshot_root / rel
            dest.mkdir(parents=True, exist_ok=True)
            for py in d.glob("*.py"):
                shutil.copy2(py, dest / py.name)

        # Regenerate migrations in place.
        result = _tortoise("makemigrations")
        if result.returncode != 0:
            print("makemigrations failed:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

        # Diff each app's snapshot against the (possibly regenerated) source.
        drifted = False
        for d in dirs:
            rel = d.relative_to(PROJECT_ROOT)
            snap = snapshot_root / rel
            diff = subprocess.run(
                ["diff", "-r", "--exclude=__pycache__", str(snap), str(d)],
                capture_output=True,
                text=True,
            )
            if diff.returncode != 0:
                drifted = True
                print(f"drift detected in {rel}:", file=sys.stderr)
                print(diff.stdout, file=sys.stderr)

        if drifted:
            print(
                "\nmigration drift detected: run `uv run python scripts/migration.py make <name>` "
                "and commit the generated migration.",
                file=sys.stderr,
            )
            return 1
        print("no migration drift")
        return 0
    finally:
        # Restore committed migration files from the snapshot so a clean
        # makemigrations run leaves no stray generated files behind.
        for d in dirs:
            rel = d.relative_to(PROJECT_ROOT)
            snap = snapshot_root / rel
            if not snap.exists():
                continue
            # Remove files the regeneration may have added.
            for py in d.glob("*.py"):
                if not (snap / py.name).exists():
                    py.unlink()
            # Restore possibly-modified files to their committed state.
            for py in snap.glob("*.py"):
                shutil.copy2(py, d / py.name)
            # Clean bytecode caches regenerated alongside.
            for pycache in d.glob("__pycache__"):
                shutil.rmtree(pycache, ignore_errors=True)
        shutil.rmtree(snapshot_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_make = sub.add_parser("make", help="Generate a migration from model changes (name required).")
    p_make.add_argument("name", nargs="?", help="Semantic name, e.g. add_report_index.")
    p_make.set_defaults(func=cmd_make)

    p_apply = sub.add_parser("apply", help="Apply pending migrations.")
    p_apply.set_defaults(func=cmd_apply)

    p_sql = sub.add_parser("sql", help="Print SQL for a migration (preview).")
    p_sql.add_argument("app", help="App label, e.g. core / repo / changelog.")
    p_sql.add_argument("migration", help="Migration id, e.g. 0001_initial.")
    p_sql.set_defaults(func=cmd_sql)

    p_down = sub.add_parser("down", help="Roll back migrations.")
    p_down.add_argument("app", help="App label.")
    p_down.add_argument("migration", nargs="?", help="Target migration id (default: previous).")
    p_down.set_defaults(func=cmd_down)

    p_drift = sub.add_parser("drift", help="Detect migration drift (CI check).")
    p_drift.set_defaults(func=cmd_drift)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
