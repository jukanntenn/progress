#!/usr/bin/env bash
# Compile .po files to .mo binary format

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOCALE_DIR="$PROJECT_ROOT/src/progress/locales"
DOMAIN="progress"

echo "Compiling message catalogs for domain: $DOMAIN"

find "$LOCALE_DIR" -name "$DOMAIN.po" | while read -r PO_FILE; do
    MO_FILE="${PO_FILE%.po}.mo"
    echo "Compiling: $PO_FILE -> $MO_FILE"
    msgfmt --output-file="$MO_FILE" "$PO_FILE"
done

echo "Done. Message catalogs compiled."
