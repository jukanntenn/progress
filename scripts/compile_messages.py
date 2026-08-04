#!/usr/bin/env python3
"""Compile .po catalogs to .mo binaries using Babel's API (spec 11).

Why not ``pybabel compile``?
----------------------------
The CLI infers the locale from the directory name and calls
``Locale.parse(name)``, which rejects BCP-47 lowercase names like ``zh-hans``
(spec 11 mandates lowercase). Calling ``babel.messages.mofile.write_mo``
directly with ``locale=None`` sidesteps the parse step while producing the
exact same .mo format that ``gettext.GNUTranslations`` loads at runtime.

Usage::

    uv run python scripts/compile_messages.py [LOCALE_DIR] [DOMAIN]
"""

from __future__ import annotations

from pathlib import Path
import sys

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

DEFAULT_LOCALE_DIR = "src/progress/locales"
DEFAULT_DOMAIN = "progress"


def compile_catalog(po_path: Path, domain: str, use_fuzzy: bool = True) -> Path:
    """Compile a single .po file to .mo. Returns the .mo path."""
    mo_path = po_path.with_suffix(".mo")
    with po_path.open("rb") as f:
        catalog = read_po(f, locale=None, domain=domain)
    with mo_path.open("wb") as f:
        write_mo(f, catalog, use_fuzzy=use_fuzzy)
    return mo_path


def compile_dir(locale_dir: Path, domain: str, use_fuzzy: bool = True) -> int:
    """Compile every ``<domain>.po`` under ``locale_dir``. Returns count."""
    if not locale_dir.is_dir():
        print(f"[compile_messages] no locale directory at {locale_dir} — nothing to compile")
        return 0

    count = 0
    for po_path in sorted(locale_dir.rglob(f"{domain}.po")):
        mo_path = compile_catalog(po_path, domain, use_fuzzy=use_fuzzy)
        print(f"[compile_messages] {po_path} -> {mo_path}")
        count += 1

    print(f"[compile_messages] compiled {count} catalog(s)")
    return count


def main() -> int:
    locale_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_LOCALE_DIR)
    domain = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DOMAIN
    compile_dir(locale_dir, domain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
