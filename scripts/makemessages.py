#!/usr/bin/env python3
"""Extract translatable strings and update .po catalogs (spec 11).

Two steps:
  1. Extract -> .pot via ``pybabel extract`` with babel.cfg. Babel's
     DEFAULT_KEYWORDS cover ``_`` / ``gettext`` / ``ngettext``; the [jinja2]
     mapping in babel.cfg picks up template strings. CI diffs the .pot against
     the committed copy to detect drift.
  2. Init or update each locale's .po via the Python helper
     (scripts/update_catalog.py) instead of ``pybabel update`` / ``pybabel
     init``, because the CLI infers the locale from the directory name and
     rejects BCP-47 lowercase (zh-hans), while spec 11 mandates lowercase.

Path discipline: extraction runs from PROJECT_ROOT with ``.`` as the input
path so the .pot records relative source paths (e.g. ``src/progress/...``).
Passing an absolute path would bake machine-specific absolute paths into the
committed file, which the CI drift check (which extracts the same way) would
flag — so this must stay aligned with scripts/check_drift.py.

Usage::

    uv run python scripts/makemessages.py
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
LOCALE_DIR = PROJECT_ROOT / "src/progress/locales"
DOMAIN = "progress"
LOCALES = ["zh-hans"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run cmd in PROJECT_ROOT, streaming output. Raise on non-zero exit."""
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


def main() -> int:
    LOCALE_DIR.mkdir(parents=True, exist_ok=True)
    pot_path = LOCALE_DIR / f"{DOMAIN}.pot"

    print(f"[makemessages] extracting strings for domain: {DOMAIN}")
    _run(
        [
            "uv",
            "run",
            "pybabel",
            "extract",
            "-F",
            "babel.cfg",
            "-o",
            str(pot_path),
            "--project=Progress",
            "--version=0.0.1",
            ".",
        ]
    )
    print(f"[makemessages] pot file: {pot_path}")

    for locale in LOCALES:
        print(f"[makemessages] updating catalog for locale: {locale}")
        _run(
            [
                "uv",
                "run",
                "python",
                str(SCRIPTS_DIR / "update_catalog.py"),
                "--pot",
                str(pot_path),
                "--locale-dir",
                str(LOCALE_DIR),
                "--domain",
                DOMAIN,
                "--locale",
                locale,
            ]
        )

    print("[makemessages] done. translate fuzzy entries, then compile catalogs:")
    print("  uv run python scripts/compile_messages.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
