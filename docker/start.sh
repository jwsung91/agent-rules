#!/usr/bin/env bash
# Start the Docker GUI and the host AI bridge (Linux/WSL). See docs/docker-gui.md.
# Usage: docker/start.sh [--port PORT] /path/to/repository-parent
set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${AGENT_RULES_VENV:-$HOME/.venvs/agent-rules}"
PY="$VENV/bin/python"
export AGENT_RULES_BRIDGE_TOKEN="${AGENT_RULES_BRIDGE_TOKEN:-$HOME/.config/agent-rules/bridge-token}"
export SOURCE_COMMIT="$(git rev-parse HEAD)"
export AGENT_RULES_UID="$(id -u)"
export AGENT_RULES_GID="$(id -g)"
export AGENT_RULES_PORT="${AGENT_RULES_PORT:-8765}"

usage() {
  echo "usage: $0 [--port PORT] /path/to/repository-parent" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) [[ $# -ge 2 ]] || usage; AGENT_RULES_PORT="$2"; shift 2 ;;
    -*) usage ;;
    *) AGENT_RULES_WORKSPACE="$1"; shift ;;
  esac
done

[[ "$AGENT_RULES_PORT" =~ ^[0-9]+$ ]] && (( AGENT_RULES_PORT >= 1 && AGENT_RULES_PORT <= 65535 )) || usage
export AGENT_RULES_WORKSPACE="${AGENT_RULES_WORKSPACE:-}"
[[ -n "$AGENT_RULES_WORKSPACE" && -d "$AGENT_RULES_WORKSPACE" ]] || usage
AGENT_RULES_WORKSPACE="$(cd "$AGENT_RULES_WORKSPACE" && pwd)"

if [[ ! -x "$PY" ]]; then
  python3 -m venv "$VENV"
  "$PY" -m pip install -r requirements-gui.txt
fi

if [[ ! -f "$AGENT_RULES_BRIDGE_TOKEN" ]]; then
  "$PY" scripts/ai_bridge.py --token-file "$AGENT_RULES_BRIDGE_TOKEN" --init-token
fi

URL="http://127.0.0.1:$AGENT_RULES_PORT"
docker compose up --build -d

for _ in $(seq 60); do
  curl -fs -o /dev/null "$URL/" && break
  sleep 1
done
if ! curl -fs -o /dev/null "$URL/"; then
  echo "GUI did not respond at $URL; check: docker compose logs gui" >&2
  exit 1
fi
echo "GUI: $URL  (stop bridge: Ctrl+C, stop GUI: docker/stop.sh)"

exec "$PY" scripts/ai_bridge.py \
  --workspace "$AGENT_RULES_WORKSPACE" \
  --token-file "$AGENT_RULES_BRIDGE_TOKEN" \
  --url "$URL"
