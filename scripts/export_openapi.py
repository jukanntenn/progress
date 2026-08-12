#!/usr/bin/env python3
"""Export the OpenAPI schema from the FastAPI app (spec 12).

The schema is committed to ``web/openapi.json`` as a contract artifact. CI
regenerates it (via ``--output`` to a temp path) to detect schema drift and to
generate TypeScript types for the frontend.

The committed bytes are the raw ``json.dump`` output (indent=2). A generated
file is kept verbatim and is NOT piped through Prettier; ``web/.prettierignore``
lists it so no formatter touches it (see docs/agent-hooks.md / project drift
conventions). A single trailing newline is written so the file has a clean
POSIX EOF.

Usage:
    python scripts/export_openapi.py [--output web/openapi.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Add src to path so we can import progress.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from progress.api import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "web" / "openapi.json"


def main() -> None:
    """Export OpenAPI schema to the output path (raw JSON, one trailing newline)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output path (default: web/openapi.json).")
    args = parser.parse_args()

    schema = create_app().openapi()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"OpenAPI schema exported to {args.output}")


if __name__ == "__main__":
    main()
