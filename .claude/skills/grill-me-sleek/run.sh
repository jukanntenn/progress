#!/usr/bin/env bash
# Grill-Me-Sleek wrapper — self-locates server.py regardless of CWD.
# Usage mirrors server.py:
#   bash run.sh << 'EOF'            # push questions (non-blocking, returns URL)
#     <json_data>
#   EOF
#   bash run.sh '<json_data>'       # push questions (non-blocking, returns URL)
#   bash run.sh --wait              # block until user submits answers
#   bash run.sh --done              # signal session complete
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/server.py" "$@"
