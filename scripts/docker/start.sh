#!/usr/bin/env bash
# Start the Docker GUI and the host AI bridge (Linux/WSL). See docs/docker-gui.md.
# Usage: scripts/docker/start.sh [--port PORT] [/path/to/repository-parent]
# The workspace defaults to the folder that contains this checkout.
set -euo pipefail

CALLER="$PWD"
CHECKOUT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$CHECKOUT"
# shellcheck source=../lib/venv.sh
source scripts/lib/venv.sh

VENV="${AGENT_RULES_VENV:-$HOME/.venvs/agent-rules}"
PY="$VENV/bin/python"
export AGENT_RULES_BRIDGE_TOKEN="${AGENT_RULES_BRIDGE_TOKEN:-$HOME/.config/agent-rules/bridge-token}"
export SOURCE_COMMIT="$(git rev-parse HEAD)"
export AGENT_RULES_UID="$(id -u)"
export AGENT_RULES_GID="$(id -g)"
export AGENT_RULES_PORT="${AGENT_RULES_PORT:-8765}"

usage() {
  echo "usage: $0 [--port PORT] [/path/to/repository-parent]  (PORT: 1024-65535)" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) [[ $# -ge 2 ]] || usage; AGENT_RULES_PORT="$2"; shift 2 ;;
    -*) usage ;;
    *)
      # Resolve against the caller's directory, not the checkout.
      AGENT_RULES_WORKSPACE="$(cd "$CALLER" && cd -- "$1" 2>/dev/null && pwd)" || usage
      shift ;;
  esac
done

[[ "$AGENT_RULES_PORT" =~ ^[0-9]+$ ]] && (( AGENT_RULES_PORT >= 1024 && AGENT_RULES_PORT <= 65535 )) || usage
export AGENT_RULES_WORKSPACE="${AGENT_RULES_WORKSPACE:-$(dirname "$CHECKOUT")}"
[[ -d "$AGENT_RULES_WORKSPACE" ]] || usage
AGENT_RULES_WORKSPACE="$(cd "$AGENT_RULES_WORKSPACE" && pwd)"
# Mount at the host path so the GUI, logs and previews show real paths.
export AGENT_RULES_CONTAINER_WORKSPACE="$AGENT_RULES_WORKSPACE"

ensure_venv "$VENV"

if [[ ! -f "$AGENT_RULES_BRIDGE_TOKEN" ]]; then
  "$PY" scripts/ai_bridge.py --token-file "$AGENT_RULES_BRIDGE_TOKEN" --init-token
fi

# Deployment works without AI, so a missing CLI only warns.
AGENT_RULES_VENV="$VENV" scripts/docker/check.sh || echo "warning: no host AI CLI is ready; AI requests will fail" >&2

URL="http://127.0.0.1:$AGENT_RULES_PORT"

# A bridge left over from an earlier start keeps running old code against the
# rebuilt GUI; stop it so a restart is a single command.
for pid in $(pgrep -f -- "scripts/ai_bridge.py .*--token-file $AGENT_RULES_BRIDGE_TOKEN" || true); do
  echo "Stopping the previous host AI bridge (PID $pid)"
  kill -INT "$pid" 2>/dev/null || true
done

docker compose up --build -d

for _ in $(seq 60); do
  curl -fs -o /dev/null "$URL/" && break
  sleep 1
done
if ! curl -fs -o /dev/null "$URL/"; then
  echo "GUI did not respond at $URL; check: docker compose logs gui" >&2
  exit 1
fi
echo "GUI: $URL  (stop bridge: Ctrl+C, stop GUI: scripts/docker/stop.sh)"

exec "$PY" scripts/ai_bridge.py \
  --workspace "$AGENT_RULES_WORKSPACE" \
  --token-file "$AGENT_RULES_BRIDGE_TOKEN" \
  --url "$URL"
