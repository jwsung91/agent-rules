# Docker GUI with host AI

Docker contains only the Python deployment program, web server and Git. It does
not install or run Codex or Claude Code. The host runs `scripts/ai_bridge.py`,
which polls the local GUI for AI requests and invokes the host's existing CLI.
Existing CLI authentication and project memories remain on the host.
Direct Python GUI execution still calls CLIs directly and needs no bridge.

```text
Browser -> Docker GUI -> mounted repository files (preview/apply)
                 ^
                 | authenticated requests/results, polled over loopback
          Host ai_bridge.py -> host Codex / Claude -> AI service
```

No host listener, Docker socket, AI credential mount, special seccomp policy or
privileged container is needed. The bridge token authenticates this local link;
it is separate from Codex/Claude credentials and never returned to the browser.
Only one host worker should run for a GUI instance.

## Linux or WSL setup

Run from the agent-rules checkout. The host needs Python 3.10+, Git, the GUI
Python dependencies, and whichever AI CLI you use. Install and log in to the CLI
on the host as usual. For WSL repositories, run the bridge and CLI in that same
WSL distribution.

```bash
python3 -m venv ~/.venvs/agent-rules
~/.venvs/agent-rules/bin/python -m pip install -r requirements-gui.txt
export AGENT_RULES_BRIDGE_TOKEN="$HOME/.config/agent-rules/bridge-token"
~/.venvs/agent-rules/bin/python scripts/ai_bridge.py --token-file "$AGENT_RULES_BRIDGE_TOKEN" --init-token
export SOURCE_COMMIT="$(git rev-parse HEAD)"
export AGENT_RULES_WORKSPACE=/absolute/path/to/repository-parent
export AGENT_RULES_UID="$(id -u)"
export AGENT_RULES_GID="$(id -g)"
docker compose up --build -d
~/.venvs/agent-rules/bin/python scripts/ai_bridge.py \
  --workspace "$AGENT_RULES_WORKSPACE" --token-file "$AGENT_RULES_BRIDGE_TOKEN"
```

Token creation is a one-time step; it refuses to overwrite an existing token.
The bridge runs in the foreground; leave that terminal open. Use `--codex` and
`--claude` with absolute executable paths if the CLI is not on the host PATH.
The token file is created with owner-only permissions on Linux. UID/GID must
match the host user to read it and write the mounted repositories. Do not work
around ownership errors by globally trusting all Git repositories.

### Start and stop scripts

`docker/start.sh` performs the steps above: it creates the venv and token on
first use, starts the GUI, then runs the bridge in the foreground.

```bash
docker/start.sh [--port PORT] /absolute/path/to/repository-parent
docker/stop.sh
docker/check.sh [codex|claude]...
```

`check.sh` reports whether each host CLI is installed and logged in, without
consuming AI usage; it exits 1 when none of the checked CLIs is ready.

`--port` defaults to `AGENT_RULES_PORT` or 8765 and is also passed to the
bridge. `AGENT_RULES_VENV` and `AGENT_RULES_BRIDGE_TOKEN` override the default
venv and token paths. Stop the bridge with Ctrl+C before running `stop.sh`.

## Native Windows setup

Use Docker Desktop's Linux containers and a host PowerShell terminal. Native
Windows repositories use Windows CLI installations; WSL repositories use the
Linux instructions above.

```powershell
py -3 -m venv "$env:LOCALAPPDATA\agent-rules-venv"
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
$env:AGENT_RULES_BRIDGE_TOKEN = "$env:LOCALAPPDATA\agent-rules-bridge-token"
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" scripts/ai_bridge.py --token-file $env:AGENT_RULES_BRIDGE_TOKEN --init-token
$env:SOURCE_COMMIT = git rev-parse HEAD
$env:AGENT_RULES_WORKSPACE = 'C:\workspace'
docker compose up --build -d
& "$env:LOCALAPPDATA\agent-rules-venv\Scripts\python.exe" scripts/ai_bridge.py --workspace $env:AGENT_RULES_WORKSPACE --token-file $env:AGENT_RULES_BRIDGE_TOKEN
```

The token file inherits Windows directory ACLs; store it in your private user
profile. Docker Desktop must be able to mount the token and workspace files.

## Use and path mapping

Open `http://127.0.0.1:8765`. The AI dialog explicitly shows that execution is on
the host. Choose Codex or Claude, check the connection, and request a proposal.
The Docker deployment workspace `/workspace/project` maps to
`<bridge --workspace>/project` on the host. Set both workspaces to the same
physical folder. Symlink projects, absolute paths and parent traversal in bridge
jobs are rejected. AI requests outside this initial mounted workspace are also
rejected, even if the GUI browses another container directory.

Home memories are discovered on the host, so Claude's project memory key uses
the original host path. **Additional memory paths are host absolute paths**,
not container paths. They must be under the workspace, `$CODEX_HOME/memories`,
`$CLAUDE_CONFIG_DIR/projects`, or an explicit host `--memory-root /path`.
No memory mounts are needed. Only selected content is supplied to the chosen
CLI. The CLI uses its existing account; AI analysis consumes that account's
allowance and can send project code and selected memories to its service.

The bridge accepts only connection, model-list, memory-list, context and analysis
jobs. It cannot receive arbitrary shell commands or apply deployment changes.
AI output still passes through review, preview and explicit apply in the GUI.
If the bridge is stopped, AI requests report that it is disconnected; normal
rule/skill deployment continues. Restart it and retry the AI request. Requests
are not stored on disk or automatically retried after execution. A lost response
can require repeating analysis and consuming usage again.

Git worktrees and submodules require their referenced Git directories to exist
inside the container mounts; ordinary clones are simplest. Additional host
folders need explicit mounts for deployment. Folder browsing does not grant
access to unmounted host directories.

## Ports, update and stop

Compose publishes only `127.0.0.1:8765`. Set `AGENT_RULES_PORT=8766` if occupied
and pass `--url http://127.0.0.1:8766` to the bridge. Internal and external ports
match to preserve Host/Origin checks. Do not expose the GUI through a public
proxy; it is for one trusted local user. Bridge requests require a separate
secret and reject cross-origin browser requests. The container runs as non-root,
drops all capabilities, and retains Docker's default seccomp policy.

Build from a clean, current checkout. `.source-commit` records `SOURCE_COMMIT`
because `.git` is excluded from the image. Pull main, update that variable, and
rebuild to update the deployed rules. Sync refuses a stale source version.
Restart the host bridge from the matching checkout when updating its protocol.

Stop the bridge with Ctrl+C, then stop the GUI:

```bash
docker compose logs --tail=100 gui
docker compose down
```

Host CLI credentials, memories and repositories are unaffected by container
rebuild/removal. The bridge token file remains on the host. To rotate it, stop
both processes, create a new token file, update `AGENT_RULES_BRIDGE_TOKEN`, and
restart both with that file. Never commit or share the token.
