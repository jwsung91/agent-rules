# Host AI Bridge

`scripts/ai_bridge.py` connects the Docker GUI to Codex or Claude Code installed
on the host. It polls authenticated jobs over loopback and runs the chosen host
CLI with its existing login. Direct local GUI execution does not need a bridge.

## Prerequisites

- Python 3.10+, Git, and `requirements-gui.txt` installed in the host environment.
- The chosen AI CLI installed and logged in on that host.
- A running Docker GUI with the same bridge token mounted through
  `AGENT_RULES_BRIDGE_TOKEN` and the same physical workspace mounted through
  `AGENT_RULES_WORKSPACE`.

For Linux/WSL, [Docker GUI setup](docker-gui.md) provides
`scripts/docker/start.sh`, which starts both the GUI and bridge. The commands
below are for manually starting or restarting the host worker.

## Create the token and run

Run with the Python environment containing the GUI dependencies:

```bash
python scripts/ai_bridge.py --token-file /private/path/bridge-token --init-token
python scripts/ai_bridge.py \
  --workspace /absolute/path/to/repository-parent \
  --token-file /private/path/bridge-token
```

Token initialization is a one-time action and refuses to overwrite an existing
file. The same token must be configured in Docker. Keep one bridge worker per
GUI instance, leave its terminal open, and stop it with Ctrl+C.

## Options

| Option | Behavior |
| --- | --- |
| `--token-file FILE` | Required shared token file |
| `--init-token` | Create the token file and exit; no workspace required |
| `--workspace DIR` | Required when polling; the host directory mounted into the GUI |
| `--url URL` | Loopback HTTP URL; defaults to `http://127.0.0.1:8765` |
| `--codex PATH` | Override the host Codex executable |
| `--claude PATH` | Override the host Claude Code executable |
| `--memory-root DIR` | Permit an additional memory directory; may be repeated |

```bash
python scripts/ai_bridge.py \
  --workspace /absolute/path/to/repository-parent \
  --token-file /private/path/bridge-token \
  --url http://127.0.0.1:8766 \
  --codex /absolute/path/to/codex \
  --memory-root /absolute/path/to/shared-memories
```

Set the matching `AGENT_RULES_PORT` when starting Docker on another port.
Additional memory selections use host absolute paths. They must stay within
the workspace, the configured default memory directories, or an allowed
`--memory-root`. Project jobs cannot escape the mounted workspace.

## Connection problems

- If the GUI is unavailable or rejects the token, confirm the URL, running
  container, and matching token file. The worker retries polling when disconnected.
- On Linux/WSL, `scripts/docker/check.sh codex claude` checks installation and
  login without consuming AI usage. Use executable overrides if needed.
- If a project is rejected, confirm the host workspace matches the mounted
  workspace. Symlink projects and traversal outside it are rejected.

AI analysis uses the host account's allowance. A lost result is not persisted or
automatically re-executed; retrying analysis can consume usage again. Review
proposals in the GUI before previewing and applying deployment changes.
See [Docker GUI setup](docker-gui.md) for Windows, mounts, and token rotation.
