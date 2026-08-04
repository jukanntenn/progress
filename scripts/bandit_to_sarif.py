#!/usr/bin/env python3
"""Convert bandit JSON output to SARIF v2.1.0 for the GitHub Security tab.

Why this exists: bandit's native ``-f`` formats are csv/html/json/xml/yaml/txt.
The only SARIF formatter (``bandit-sarif-formatter``) is archived (2026-06) and
drags in ``pbr``/``setuptools``/``sarif-om``/``jschema-to-python``, which has
historically conflicted with bandit's pyproject config reader. This script is a
self-contained stdlib-only converter so CI stays dependency-light.

Usage::

    uv run bandit -c pyproject.toml -r src/ -f json -o bandit.json || true
    uv run python scripts/bandit_to_sarif.py bandit.json bandit.sarif

SARIF spec reference: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
Bandit JSON shape: https://bandit.readthedocs.io/en/latest/plugins/index.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

BANDIT_GUID = "9b82f8a0-0b8e-4f4a-9c7e-0e8b9f0b9f9b"
LEVEL_MAP = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}


def convert(bandit: dict[str, Any]) -> dict[str, Any]:
    results = bandit.get("results", [])
    rules: list[dict[str, Any]] = []
    rule_index: dict[str, int] = {}
    sarif_results: list[dict[str, Any]] = []
    for r in results:
        test_id = r.get("test_id", "B000")
        if test_id not in rule_index:
            rule_index[test_id] = len(rules)
            rules.append(
                {
                    "id": test_id,
                    "name": test_id,
                    "shortDescription": {"text": r.get("test_name", test_id)},
                    "fullDescription": {"text": r.get("issue_text", "")},
                    "helpUri": r.get("more_info", "") or "https://bandit.readthedocs.io/",
                    "defaultConfiguration": {"level": LEVEL_MAP.get(r.get("issue_severity", "LOW"), "note")},
                    "properties": {"tags": ["security", f"confidence:{r.get('issue_confidence', 'MEDIUM')}"]},
                }
            )
        loc = r.get("filename", "")
        line = int(r.get("line_number", 1) or 1)
        sarif_results.append(
            {
                "ruleId": test_id,
                "ruleIndex": rule_index[test_id],
                "level": LEVEL_MAP.get(r.get("issue_severity", "LOW"), "note"),
                "message": {"text": r.get("issue_text", "")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": loc},
                            "region": {"startLine": line},
                        }
                    }
                ],
                "partialFingerprints": {"primaryLocationLineHash": f"{loc}:{line}:{test_id}"},
            }
        )
    return {
        "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cs01/schemas/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Bandit",
                        "informationUri": "https://github.com/PyCQA/bandit",
                        "version": bandit.get("version", "unknown"),
                        "guid": BANDIT_GUID,
                        "rules": rules,
                    }
                },
                "results": sarif_results,
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert bandit JSON to SARIF v2.1.0.")
    parser.add_argument("input", help="bandit JSON file path (or '-' for stdin)")
    parser.add_argument("output", help="SARIF output file path (or '-' for stdout)")
    args = parser.parse_args()

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    bandit = json.loads(raw)
    sarif = convert(bandit)
    out = json.dumps(sarif, indent=2)
    if args.output == "-":
        print(out)
    else:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"SARIF written to {args.output} ({len(sarif['runs'][0]['results'])} results)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
