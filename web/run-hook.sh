#!/usr/bin/env bash
# Run a web/ tool from the repo root, stripping the leading "web/" from each
# path so eslint/prettier (which expect paths relative to web/) resolve their
# flat config and plugins correctly.
#
# Usage from prek.toml:
#   entry = "bash web/run-hook.sh eslint --fix"
#   entry = "bash web/run-hook.sh prettier --write"
#
# prek passes repo-root-relative paths (web/src/foo.ts); this script cd's into
# web/ and rewrites them to src/foo.ts before handing them to the tool.

set -euo pipefail

tool="$1"
shift

cd "$(dirname "$0")"

args=()
for arg in "$@"; do
  if [[ "$arg" == web/* ]]; then
    args+=("${arg#web/}")
  else
    args+=("$arg")
  fi
done

exec "./node_modules/.bin/$tool" "${args[@]}"
