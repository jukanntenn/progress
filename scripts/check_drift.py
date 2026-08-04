#!/usr/bin/env python3
"""Run every drift / regression check that CI runs, identically, locally.

This is the single source of truth for drift checks: CI's ``drift-checks`` job
calls this script, so ``uv run python scripts/check_drift.py`` locally tells
you exactly whether CI will go green on push. The two paths can never drift
apart.

The seven checks (each prints a banner + [OK]/[FAIL] summary):

  1. deptry             — declared-but-unused / used-but-undeclared deps.
  2. import-linter      — forbidden cross-layer imports ([tool.importlinter]).
  3. OpenAPI drift      — web/openapi.json matches what FastAPI produces.
  4. Frontend types     — web/src/api/schema.ts matches openapi.json.
  5. i18n .pot drift    — progress.pot matches freshly extracted strings
                          (POT-Creation-Date stripped — non-deterministic).
  6. i18n catalog lint  — no fuzzy / empty / obsolete .po entries.
  7. Migration drift    — every model change has a matching migration.

Prerequisites (same as CI):
  - ``uv sync --extra dev``          (backend dev deps)
  - ``pnpm --dir web install``       (frontend deps, for the type-drift check)

A clean working tree is **not** required — checks diff against HEAD, so
uncommitted source changes surface as drift (intentional; commit or stash first
to isolate a single check).

Side effects: the OpenAPI and .pot checks leave their freshly regenerated
artifacts on disk (mirroring CI). Re-commit them if the regeneration is the
intended update, otherwise ``git checkout -- <path>`` to discard.

Usage::

    uv run python scripts/check_drift.py
"""

from __future__ import annotations

from collections.abc import Callable
import difflib
import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCALE_POT = PROJECT_ROOT / "src/progress/locales/progress.pot"
OPENAPI_JSON = PROJECT_ROOT / "web/openapi.json"
SCHEMA_TS = PROJECT_ROOT / "web/src/api/schema.ts"

# ANSI color codes; disabled when stdout is not a tty or NO_COLOR is set.
_USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
if _USE_COLOR:
    BOLD = "\033[1m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    RESET = "\033[0m"
else:
    BOLD = BLUE = GREEN = RED = RESET = ""


def _run(cmd: list[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[bytes]:
    """Run cmd, inheriting stdout/stderr so output streams live. Returns result."""
    return subprocess.run(cmd, cwd=str(cwd), check=False)


def _run_captured(cmd: list[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    """Run cmd, capturing stdout/stderr. Returns result (caller inspects .returncode)."""
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)


def _git_show_head_blob(path: str) -> str:
    """Return the content of `path` at HEAD, or empty string if untracked at HEAD."""
    result = _run_captured(["git", "show", f"HEAD:{path}"])
    return result.stdout if result.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Individual checks. Each returns 0 on success, non-zero on failure, and is
# responsible for printing its own diagnostic detail on failure.
# ---------------------------------------------------------------------------


def check_deptry() -> int:
    return _run(["uv", "run", "deptry", "."]).returncode


def check_import_linter() -> int:
    return _run(["uv", "run", "lint-imports", "--no-cache"]).returncode


def check_openapi_drift() -> int:
    """Regenerate openapi.json, fail if it differs from the committed copy."""
    gen = _run(["uv", "run", "python", "scripts/export_openapi.py"])
    if gen.returncode != 0:
        return gen.returncode
    diff = _run_captured(["git", "diff", "--exit-code", "--", "web/openapi.json"])
    if diff.returncode != 0:
        print(diff.stdout)
        return diff.returncode
    return 0


def check_frontend_type_drift() -> int:
    """Generate schema.ts.check from openapi.json, diff against committed schema.ts."""
    check_file = SCHEMA_TS.with_suffix(".ts.check")
    gen = _run_captured(
        ["pnpm", "--dir", "web", "exec", "openapi-typescript", "web/openapi.json", "-o", str(check_file)]
    )
    if gen.returncode != 0:
        print(gen.stderr or gen.stdout)
        return gen.returncode
    diff = subprocess.run(
        ["diff", "-u", str(SCHEMA_TS), str(check_file)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0:
        print(diff.stdout)
    check_file.unlink(missing_ok=True)
    return diff.returncode


def check_pot_drift() -> int:
    """Extract .pot fresh, diff against HEAD (POT-Creation-Date line stripped)."""
    extract = _run_captured(
        [
            "uv",
            "run",
            "pybabel",
            "extract",
            "-F",
            "babel.cfg",
            "-o",
            "src/progress/locales/progress.pot",
            "--project=Progress",
            "--version=0.0.1",
            ".",
        ]
    )
    if extract.returncode != 0:
        print(extract.stderr or extract.stdout)
        return extract.returncode
    # Normalize trailing newlines to match the committed copy (prek's
    # end-of-file-fixer rewrites Babel's double trailing newline to a single
    # one on commit). Without this the freshly extracted .pot would always
    # differ from HEAD and the check would never go green. Mirrors
    # scripts/makemessages.py's _normalize_eol.
    text = LOCALE_POT.read_text(encoding="utf-8")
    LOCALE_POT.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    committed = "\n".join(
        line
        for line in _git_show_head_blob("src/progress/locales/progress.pot").splitlines()
        if not line.startswith('"POT-Creation-Date:')
    )
    current_text = LOCALE_POT.read_text(encoding="utf-8")
    current = "\n".join(line for line in current_text.splitlines() if not line.startswith('"POT-Creation-Date:'))
    if committed == current:
        return 0
    # Show a compact diff so the failure is actionable.
    print("--- committed (HEAD)        vs    freshly extracted (working tree) ---")
    for line in difflib.unified_diff(
        committed.splitlines(),
        current.splitlines(),
        fromfile="HEAD:progress.pot (POT-Creation-Date stripped)",
        tofile="working-tree progress.pot (POT-Creation-Date stripped)",
        lineterm="",
    ):
        print(line)
    return 1


def check_i18n_catalog_lint() -> int:
    return _run(["uv", "run", "python", "scripts/check_translations.py"]).returncode


def check_migration_drift() -> int:
    return _run(["uv", "run", "python", "scripts/migration.py", "drift"]).returncode


CHECKS: list[tuple[str, Callable[[], int]]] = [
    ("deptry", check_deptry),
    ("import-linter", check_import_linter),
    ("openapi drift", check_openapi_drift),
    ("frontend type drift", check_frontend_type_drift),
    ("i18n .pot drift", check_pot_drift),
    ("i18n catalog lint", check_i18n_catalog_lint),
    ("migration drift", check_migration_drift),
]


def main() -> int:
    ran = 0
    failures: list[str] = []
    for name, check in CHECKS:
        print(f"\n{BOLD}{BLUE}== {name} =={RESET}")
        rc = check()
        ran += 1
        if rc == 0:
            print(f"{GREEN}[OK]{RESET} {name}")
        else:
            print(f"{RED}[FAIL]{RESET} {name}")
            failures.append(name)

    print()
    if not failures:
        print(f"{GREEN}{BOLD}All {ran} drift checks passed.{RESET}")
        return 0
    print(f"{RED}{BOLD}{len(failures)}/{ran} drift checks failed:{RESET}")
    for name in failures:
        print(f"  - {RED}{name}{RESET}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
