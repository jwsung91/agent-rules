# Usage Guides

Run commands from the `agent-rules` checkout unless a guide says otherwise.
Python tools require Python 3.10+ and Git. GUI and bridge commands additionally
need `requirements-gui.txt`; TOML batch lists need Python 3.11+.

## Choose a tool

| Goal | Command | Guide |
| --- | --- | --- |
| Install, sync, check, or remove rules and skills | `python scripts/adopt.py` | [Scripted adoption](scripted-adoption.md) |
| Build a candidate repository list | `python scripts/generate_batch_list.py` | [Batch-list generation](batch-list.md) |
| Preview and apply deployment in a browser | `python scripts/gui.py` | [Local GUI](local-gui.md) |
| Run the GUI in Docker on Linux/WSL | `scripts/docker/start.sh`, `stop.sh`, `check.sh` | [Docker GUI](docker-gui.md) |
| Connect Docker GUI requests to host AI CLIs | `python scripts/ai_bridge.py` | [Host AI bridge](host-ai-bridge.md) |
| Record live shared-skill behavior | `python scripts/forward_test.py` | [Forward testing](forward-testing.md) |
| Adopt entrypoints by hand | Manual edits | [Lightweight adoption](lightweight-adoption.md) |

Every public Python command supports `--help`. The Docker shell scripts are for
Linux/WSL; the Docker guide includes manual PowerShell instructions for Windows.
Docker shell commands now live under `scripts/docker/`; replace older
`docker/start.sh`, `docker/stop.sh`, and `docker/check.sh` shortcuts.

## Working with the rules

- [Claude and Codex workflow](claude-codex-workflow.md): primary and review roles.
- [Skill authoring](skill-authoring.md): shared skill contracts and metadata.
- [Architecture](architecture.md): file responsibilities and dependencies.
- [Cross-agent validation](cross-agent-validation.md): evaluation method,
  historical results, and known limitations.
