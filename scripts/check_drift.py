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
  - ``cd web && pnpm install``       (frontend deps, for the type-drift check)

All checks are **non-destructive**: generated artifacts (openapi.json, .pot,
schema.ts) are regenerated to temp files and diffed, never written to the
committed path. A clean run leaves the working tree untouched. Generated files
are also exempt from prek's mutating hooks (see prek.toml ``exclude`` and
``web/.prettierignore``), so a generator's raw output is the canonical form.

Usage::

    uv run python scripts/check_drift.py
"""

from __future__ import annotations

from collections.abc import Callable
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
LOCALE_POT = PROJECT_ROOT / "src" / "progress" / "locales" / "progress.pot"
OPENAPI_JSON = WEB_DIR / "openapi.json"
SCHEMA_TS = WEB_DIR / "src" / "api" / "schema.ts"

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


def _tempfile(suffix: str) -> Path:
    """Return a fresh closed temp file path (caller unlinks it)."""
    fd, name = tempfile.mkstemp(prefix="drift-", suffix=suffix)
    os.close(fd)
    return Path(name)


def _pnpm() -> str:
    """Locate pnpm; falls back to nvm-installed binaries for shells whose PATH
    lacks them (e.g. prek's hook environment) — CI always has pnpm on PATH.
    Prepends the node bin dir to PATH so node is reachable for the spawned
    subprocesses too."""
    found = shutil.which("pnpm")
    if found:
        return "pnpm"
    candidates = sorted(Path.home().glob(".nvm/versions/node/*/bin"))
    if candidates:
        node_bin = candidates[-1]
        os.environ["PATH"] = str(node_bin) + os.pathsep + os.environ.get("PATH", "")
        return str(node_bin / "pnpm")
    return "pnpm"


def _strip_pot_creation_date(text: str) -> str:
    """Drop the non-deterministic ``POT-Creation-Date`` line and trailing EOL.

    Babel stamps ``POT-Creation-Date`` with ``datetime.now()``; it carries no
    information for drift detection, so it is removed before comparing. Trailing
    newlines are normalized too so Babel's raw double-newline compares equal
    regardless of any historical end-of-file processing.
    """
    kept = "\n".join(line for line in text.splitlines() if not line.startswith('"POT-Creation-Date:'))
    return kept.rstrip()


# ---------------------------------------------------------------------------
# Individual checks. Each returns 0 on success, non-zero on failure, and is
# responsible for printing its own diagnostic detail on failure.
# ---------------------------------------------------------------------------


def check_deptry() -> int:
    return _run(["uv", "run", "deptry", "."]).returncode


def check_import_linter() -> int:
    return _run(["uv", "run", "lint-imports", "--no-cache"]).returncode


def check_openapi_drift() -> int:
    """Regenerate openapi.json to a temp file; fail if it differs from committed."""
    tmp = _tempfile(".json")
    try:
        gen = _run_captured(["uv", "run", "python", "scripts/export_openapi.py", "--output", str(tmp)])
        if gen.returncode != 0:
            print(gen.stderr or gen.stdout)
            return gen.returncode
        diff = subprocess.run(["diff", "-u", str(OPENAPI_JSON), str(tmp)], capture_output=True, text=True, check=False)
        if diff.returncode != 0:
            print(diff.stdout)
        return diff.returncode
    finally:
        tmp.unlink(missing_ok=True)


def check_frontend_type_drift() -> int:
    """Generate schema.ts to a temp file (raw) and diff against the committed copy."""
    tmp = _tempfile(".ts")
    try:
        # Run with cwd=web, not `--dir web`: a corepack pnpm shim resolves the
        # pinned packageManager version from the CWD's package.json and never
        # sees `--dir`, so a root invocation launches the default pnpm and
        # fails its own version check before openapi-typescript can run.
        gen = _run_captured([_pnpm(), "exec", "openapi-typescript", "openapi.json", "-o", str(tmp)], cwd=WEB_DIR)
        if gen.returncode != 0:
            print(gen.stderr or gen.stdout)
            return gen.returncode
        diff = subprocess.run(["diff", "-u", str(SCHEMA_TS), str(tmp)], capture_output=True, text=True, check=False)
        if diff.returncode != 0:
            print(diff.stdout)
        return diff.returncode
    finally:
        tmp.unlink(missing_ok=True)


def check_pot_drift() -> int:
    """Extract .pot to a temp file; diff against HEAD (POT-Creation-Date stripped)."""
    tmp = _tempfile(".pot")
    try:
        extract = _run_captured(
            [
                "uv",
                "run",
                "pybabel",
                "extract",
                "-F",
                "babel.cfg",
                "-o",
                str(tmp),
                "--project=Progress",
                "--version=0.0.1",
                ".",
            ]
        )
        if extract.returncode != 0:
            print(extract.stderr or extract.stdout)
            return extract.returncode
        committed = _strip_pot_creation_date(LOCALE_POT.read_text(encoding="utf-8"))
        current = _strip_pot_creation_date(tmp.read_text(encoding="utf-8"))
        if committed == current:
            return 0
        print("--- committed (HEAD)        vs    freshly extracted (working tree) ---")
        for line in difflib.unified_diff(
            committed.splitlines(),
            current.splitlines(),
            fromfile="HEAD:progress.pot (POT-Creation-Date stripped)",
            tofile="fresh extract (POT-Creation-Date stripped)",
            lineterm="",
        ):
            print(line)
        return 1
    finally:
        tmp.unlink(missing_ok=True)


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
