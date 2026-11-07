#!/usr/bin/env bash
# Stop the Docker GUI started by ./start.sh. Stop the host bridge with Ctrl+C first.
# The local GUI stops with Ctrl+C in its terminal.
set -euo pipefail

exec "$(cd "$(dirname "$0")" && pwd)/scripts/docker/stop.sh" "$@"
