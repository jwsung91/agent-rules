#!/usr/bin/env bash
# Start the local web GUI without Docker (Linux/WSL). See docs/local-gui.md.
# Usage: scripts/local/start.sh /path/to/workspace [gui.py options...]
set -euo pipefail

usage() {
  echo "usage: $0 /path/to/workspace [gui.py options...]" >&2
  exit 2
}

[[ $# -ge 1 && "$1" != -* && -d "$1" ]] || usage
# Resolve before changing directory so relative workspace paths keep working.
WORKSPACE="$(cd "$1" && pwd)"
shift

cd "$(dirname "$0")/../.."
# shellcheck source=../lib/venv.sh
source scripts/lib/venv.sh

VENV="${AGENT_RULES_VENV:-$HOME/.venvs/agent-rules}"
ensure_venv "$VENV"

exec "$VENV/bin/python" scripts/gui.py --workspace "$WORKSPACE" "$@"
