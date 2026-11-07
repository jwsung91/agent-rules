#!/usr/bin/env bash
# Start the agent-rules deployment GUI with one command (Linux/WSL).
# Usage: ./start.sh [--docker|--local] [--port PORT] [/path/to/workspace]
#   --docker  Docker GUI plus host AI bridge (default when Docker Compose works)
#   --local   GUI directly on this machine (default otherwise)
# The workspace defaults to the folder that contains this checkout.
# Stop: Ctrl+C, then ./stop.sh for the Docker GUI.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
mode=""
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker) mode=docker; shift ;;
    --local) mode=local; shift ;;
    *) args+=("$1"); shift ;;
  esac
done

if [[ -z "$mode" ]]; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    mode=docker
  else
    mode=local
  fi
fi

echo "agent-rules GUI: $mode mode" >&2
exec "$here/scripts/$mode/start.sh" "${args[@]+"${args[@]}"}"
