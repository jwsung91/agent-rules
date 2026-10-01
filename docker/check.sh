#!/usr/bin/env bash
# Check that the host AI CLIs used by the bridge are installed and logged in.
# Usage: docker/check.sh [codex|claude]...   (default: both)
# Exits 1 when none of the checked CLIs is ready. No AI usage is consumed.
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${AGENT_RULES_VENV:-$HOME/.venvs/agent-rules}/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "venv not found: $PY (run docker/start.sh once or see docs/docker-gui.md)" >&2
  exit 1
fi

exec "$PY" - "${@:-codex claude}" <<'EOF'
import sys

sys.path.insert(0, "scripts")
from agent_rules.gui_ai import connection

providers = " ".join(sys.argv[1:]).split()
ready = False
for provider in providers:
    if provider not in {"codex", "claude"}:
        sys.exit("usage: docker/check.sh [codex|claude]...")
    result = connection(provider)
    ready = ready or result["ready"]
    mark = "ok  " if result["ready"] else "FAIL"
    print(f"[{mark}] {provider}: {result['message']} {result['path']}".rstrip())
sys.exit(0 if ready else 1)
EOF
