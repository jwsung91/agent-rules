# Local Deployment GUI

The GUI runs directly as a Python process. It uses the existing deployment
planner, checks, and writer; no Docker, database, Node.js runtime, or frontend
build is needed. Dependencies are separate from the standard-library CLI.

## Linux and WSL

Run from the agent-rules checkout with Python 3.10+ and Git installed:

```bash
python3 -m venv ~/.venvs/agent-rules
~/.venvs/agent-rules/bin/python -m pip install -r requirements-gui.txt
~/.venvs/agent-rules/bin/python scripts/gui.py --workspace /home/rain/workspace/jwsung91
```

If venv creation is unavailable, install your distribution's Python venv
package first. Visit `http://127.0.0.1:8765` from the same machine. WSL users can
open that URL in a Windows browser when localhost forwarding is available.
`--open-browser` optionally uses the server environment's browser handler; WSL
users can open the URL manually if that environment has no browser handler.
Use `--port 8766` when the default port is occupied. Stop with Ctrl+C.

## Native Windows

Run in PowerShell from the checkout:

```powershell
py -3 -m venv "$env:LOCALAPPDATA\agent-rules-venv"
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" scripts/gui.py --workspace C:\workspace --open-browser
```

Use a Linux path when the server runs in WSL, and a Windows path when running
native Windows Python. The server accesses its own filesystem, not the browser
computer's filesystem.

## Headless Linux

Keep the server bound to loopback and forward its port over SSH:

```bash
ssh -L 8765:127.0.0.1:8765 user@linux-host
```

Start the server on the Linux host, then open the local forwarded URL in your
browser. Use the same local and remote port so origin checks match. The GUI is
for one trusted local user, not a public or multi-user service.

## Workflow

1. Start with an explicit `--workspace`. Discovery searches to depth three,
   stops at Git repositories, skips symlink directories, and excludes the
   agent-rules source checkout. No repository is selected automatically.
2. Select intended repositories. The search field filters the list; selections
   persist when filtered. The selected count includes hidden selections.
3. Choose an agent, operation, visibility, and whether to install shared skills.
   Automatic mode uses recorded profiles and syncs existing adoptions; new
   repositories default to Codex installation. Visibility is explicitly selected
   and defaults to local; choose tracked for shared installations.
4. Run **상태 확인** for the actual health report. Initial discovery only reports
   whether installation metadata exists; it does not claim version currency.
5. Run **변경 미리보기** to inspect files, baselines, `.gitignore` changes, and
   conflicts. Baseline files are included because they will also be written.
6. **선택한 변경 적용** becomes available only when every selected repository has
   a valid preview. Results and failures are logged per repository.

A preview expires after 15 minutes and can be applied once. Changing the UI
selection or options discards its preview. The server also rejects a preview
when managed target files, source content, Git index, or Git configuration
change. Refresh after restarting the server. Do not concurrently edit affected
files or run another deployment process while applying; this is not a filesystem
transaction or a lock against external programs.

Operations are serialized within this server, and each batch is processed
sequentially. A failure does not roll back successful repositories. A disk or
permission error during writing can leave partial changes; inspect the log and
run a fresh health check. Closing the tab does not reliably cancel a request
already executing on the server. Logs and preview tokens live only in memory.

## Scope and local access

The first version supports discovery, checks, installation, sync, and diffs.
Use the CLI for removal, force overwrite, local rule copies, custom boundary or
validation arguments, and persistent batch lists. Existing local settings are
preserved by the same merge engine as the CLI. Suggested validation commands are
not executed by the GUI. The GUI does not commit, push, or need signing keys.

The server binds only to `127.0.0.1`, validates Host and Origin, requires a
session token for API operations, and serves no external scripts. Do not expose
it through a public proxy. Paths must stay within the startup workspace; the GUI
refuses symlinks in managed output paths. This is not protection against other
processes running as the same OS user.

## Implementation and validation

- `scripts/gui.py`: direct-execution launcher and optional browser opening.
- `scripts/agent_rules/gui_web.py`: loopback HTTP API and bundled static assets.
- `scripts/agent_rules/gui_service.py`: structured previews and approval state,
  delegating to existing planning, applying, checking, and discovery modules.
- `scripts/agent_rules/web/`: plain HTML, CSS, and JavaScript.
- `tests/test_gui.py`: temporary-repository workflows, stale previews, access
  restrictions, conflicting files, and failure reporting.

Install `requirements-dev.txt` to run the full suite including GUI tests.
