#!/usr/bin/env python3
"""Verify locale catalogs are complete and clean (spec 11).

Exits non-zero when any ``.po`` catalog under the locales dir has:
- a fuzzy entry (``#, fuzzy``) — a translator must resolve these,
- an empty ``msgstr`` for a non-empty ``msgid`` — missing translation,
- an obsolete entry (``#~``) — leftover from a removed msgid; these should be
  purged after a catalog update so the file stays a faithful mirror of the
  extracted ``.pot``.

Run locally via ``uv run python scripts/check_translations.py`` and wire into
CI to catch translation regressions (e.g. a template edit that drops or renames
a msgid without updating the catalog).
"""

from __future__ import annotations

from pathlib import Path
import sys

LOCALES_DIR = Path(__file__).resolve().parent.parent / "src" / "progress" / "locales"


def check_po(po_path: Path) -> list[str]:
    """Return a list of problems found in ``po_path`` (empty = clean)."""
    problems: list[str] = []
    text = po_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    fuzzy_count = sum(1 for line in lines if line.strip() == "#, fuzzy")
    if fuzzy_count:
        problems.append(
            f"{fuzzy_count} fuzzy entr{'y' if fuzzy_count == 1 else 'ies'} (resolve or drop the #, fuzzy marker)"
        )

    obsolete_count = sum(1 for line in lines if line.startswith("#~"))
    if obsolete_count:
        problems.append(
            f"{obsolete_count} obsolete entr{'y' if obsolete_count == 1 else 'ies'} (#~ — purge after catalog update)"
        )

    msgid = ""
    msgstr = ""
    in_entry = False
    empty_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("msgid "):
            msgid = stripped[len("msgid ") :]
            msgstr = ""
            in_entry = True
        elif stripped.startswith("msgstr "):
            msgstr = stripped[len("msgstr ") :]
        elif stripped == "" and in_entry:
            if msgid and msgid != '""' and msgstr == '""':
                empty_count += 1
            in_entry = False
    if empty_count:
        problems.append(f"{empty_count} empty msgstr (missing translation)")

    return problems


def main() -> int:
    if not LOCALES_DIR.is_dir():
        print(f"locales dir not found: {LOCALES_DIR}", file=sys.stderr)
        return 1

    po_files = sorted(LOCALES_DIR.rglob("*.po"))
    if not po_files:
        print(f"no .po catalogs under {LOCALES_DIR}", file=sys.stderr)
        return 1

    failures = 0
    for po in po_files:
        problems = check_po(po)
        rel = po.relative_to(LOCALES_DIR)
        if problems:
            failures += 1
            print(f"FAIL {rel}:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"OK   {rel}")

    if failures:
        print(f"\n{failures} catalog(s) need attention. Run scripts/makemessages.py then translate.", file=sys.stderr)
        return 1
    print(f"\nAll {len(po_files)} catalog(s) clean (no fuzzy / no empty / no obsolete).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
