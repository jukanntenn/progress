#!/usr/bin/env bash
# Extract translatable strings from Python and Jinja2 templates

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOCALE_DIR="$PROJECT_ROOT/src/progress/locales"
DOMAIN="progress"
PY_SRC="$PROJECT_ROOT/src/progress"
TEMPLATES="$PROJECT_ROOT/src/progress/templates"

echo "Extracting messages for domain: $DOMAIN"

mkdir -p "$LOCALE_DIR"

xgettext \
    --keyword=_ \
    --keyword=gettext \
    --language=Python \
    --from-code=UTF-8 \
    --output="$LOCALE_DIR/$DOMAIN.pot" \
    --package-name="Progress" \
    --package-version="0.0.1" \
    $(find "$PY_SRC" -name "*.py") \
    $(find "$TEMPLATES" -name "*.j2")

echo "POT file created: $LOCALE_DIR/$DOMAIN.pot"
echo "Done. Now create/translate .po files for each language."
echo "Example: mkdir -p src/progress/locales/zh-hans/LC_MESSAGES && msginit --locale=zh-hans --input=src/progress/locales/progress.pot --output=src/progress/locales/zh-hans/LC_MESSAGES/progress.po"
