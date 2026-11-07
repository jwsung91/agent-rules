# Shared venv setup for the Linux/WSL launch scripts. Source this file from the
# agent-rules checkout root; do not run it directly.

# ensure_venv VENV: create VENV if needed, then install requirements-gui.txt.
# The install runs every time: it finishes quickly when the pinned packages are
# already present, picks up requirement updates, and repairs a venv whose
# earlier install failed.
ensure_venv() {
  local venv="$1"
  if [[ ! -x "$venv/bin/python" ]]; then
    python3 -m venv "$venv"
  fi
  "$venv/bin/python" -m pip install -q --disable-pip-version-check -r requirements-gui.txt
}
