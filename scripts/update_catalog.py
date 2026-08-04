#!/usr/bin/env python3
"""Initialize or update a .po catalog from a .pot template (spec 11).

Why not ``pybabel update`` / ``pybabel init``?
-----------------------------------------------
The CLI infers the locale from the directory name and calls
``Locale.parse(name)``, which rejects BCP-47 lowercase names like ``zh-hans``
(spec 11 mandates lowercase). This helper uses Babel's Python API directly
(``read_po``/``write_po``) with ``locale=None`` to sidestep the parse step
while producing the same .po format.

The update logic mirrors ``pybabel update``:
  - New msgids from the .pot are added (marked fuzzy if the .po had no
    translation, or matched by similarity to existing entries).
  - Obsolete msgids (in .po but not in .pot) are kept as ``#~`` entries.
  - Existing translations and flags are preserved.

Usage::

    uv run python scripts/update_catalog.py \\
        --pot src/progress/locales/progress.pot \\
        --locale-dir src/progress/locales \\
        --domain progress \\
        --locale zh-hans
"""

from __future__ import annotations

import argparse
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po


def update_catalog(pot_path: Path, po_path: Path, domain: str, locale: str) -> None:
    """Merge ``pot_path`` into ``po_path``, creating ``po_path`` if missing."""
    with pot_path.open("rb") as f:
        template = read_po(f, locale=None, domain=domain)

    if po_path.exists():
        with po_path.open("rb") as f:
            existing = read_po(f, locale=None, domain=domain)
        # Babel's Catalog.update() merges new messages and marks obsoletes.
        existing.update(template)
        catalog = existing
    else:
        # Fresh catalog from the template.
        catalog = Catalog(locale=None, domain=domain)
        catalog.update(template)

    po_path.parent.mkdir(parents=True, exist_ok=True)
    with po_path.open("wb") as f:
        write_po(f, catalog, omit_header=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Init or update a .po catalog from a .pot.")
    parser.add_argument("--pot", required=True, type=Path, help="Path to the .pot template.")
    parser.add_argument("--locale-dir", required=True, type=Path, help="Locales root directory.")
    parser.add_argument("--domain", required=True, help="Message domain (e.g. 'progress').")
    parser.add_argument("--locale", required=True, help="Locale code (e.g. 'zh-hans').")
    args = parser.parse_args()

    po_path = args.locale_dir / args.locale / "LC_MESSAGES" / f"{args.domain}.po"
    update_catalog(args.pot, po_path, args.domain, args.locale)
    print(f"[update_catalog] {args.pot} -> {po_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
