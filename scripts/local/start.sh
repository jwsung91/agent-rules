#!/usr/bin/env bash
# Start the local web GUI without Docker (Linux/WSL). See docs/local-gui.md.
# Usage: scripts/local/start.sh [/path/to/workspace] [gui.py options...]
# The workspace defaults to the folder that contains this checkout.
set -euo pipefail

usage() {
  echo "usage: $0 [/path/to/workspace] [gui.py options...]" >&2
  exit 2
}

CHECKOUT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKSPACE="$(dirname "$CHECKOUT")"
if [[ $# -ge 1 && "$1" != -* ]]; then
  [[ -d "$1" ]] || usage
  # Resolve before changing directory so relative workspace paths keep working.
  WORKSPACE="$(cd "$1" && pwd)"
  shift
fi

cd "$CHECKOUT"
# shellcheck source=scripts/lib/venv.sh
source scripts/lib/venv.sh

VENV="${AGENT_RULES_VENV:-$HOME/.venvs/agent-rules}"
ensure_venv "$VENV"

exec "$VENV/bin/python" scripts/gui.py --workspace "$WORKSPACE" "$@"
