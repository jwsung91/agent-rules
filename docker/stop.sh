#!/usr/bin/env bash
# Stop the Docker GUI. Stop the host bridge first with Ctrl+C.
set -euo pipefail

cd "$(dirname "$0")/.."

# compose validates required variables even for down; values are unused.
export SOURCE_COMMIT="${SOURCE_COMMIT:-unused}"
export AGENT_RULES_WORKSPACE="${AGENT_RULES_WORKSPACE:-$PWD}"
export AGENT_RULES_BRIDGE_TOKEN="${AGENT_RULES_BRIDGE_TOKEN:-$PWD}"

exec docker compose down
