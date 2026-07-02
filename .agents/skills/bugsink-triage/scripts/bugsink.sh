#!/usr/bin/env bash
# Bugsink API helper for the progress project.
#
# Usage: bugsink.sh <METHOD> <path> [json-body]
#   METHOD : GET | POST | DELETE
#   path   : API path under /api/canonical/0/ , e.g. "/issues/?project=2"
#   body   : optional JSON body for POST
#
# Reads the Bearer token from ~/.bugsink_token (override with BUGSINK_TOKEN_FILE)
# and hits http://192.168.5.50:8770 (override with BUGSINK_BASE_URL).
set -euo pipefail

TOKEN_FILE="${BUGSINK_TOKEN_FILE:-$HOME/.bugsink_token}"
BASE_URL="${BUGSINK_BASE_URL:-http://192.168.5.50:8770}"
API_ROOT="$BASE_URL/api/canonical/0"

if [ ! -f "$TOKEN_FILE" ]; then
  echo "Token file not found: $TOKEN_FILE" >&2
  echo "Create a token in the Bugsink UI (superuser) and run:" >&2
  echo "  printf '%s' '<token>' > $TOKEN_FILE && chmod 600 $TOKEN_FILE" >&2
  exit 1
fi
TOKEN=$(cat "$TOKEN_FILE")

METHOD=${1:?METHOD required (GET|POST|DELETE)}
PATH_=${2:?API path required, e.g. /issues/?project=2}
BODY=${3:-}

if [ -n "$BODY" ]; then
  curl -sS -X "$METHOD" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    --data "$BODY" \
    "${API_ROOT}${PATH_}"
else
  curl -sS -X "$METHOD" \
    -H "Authorization: Bearer $TOKEN" \
    "${API_ROOT}${PATH_}"
fi
