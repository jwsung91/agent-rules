"""Exercise relocated shell commands with fake Docker and host AI CLIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="Docker lifecycle scripts target Linux/WSL with Bash",
)


@pytest.fixture
def shell_environment(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    log = tmp_path / "calls.jsonl"
    launcher = f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
with open(os.environ["SCRIPT_CALLS"], "a") as stream:
    stream.write(json.dumps({
        "tool": name, "args": sys.argv[1:], "cwd": os.getcwd(),
        "workspace": os.environ.get("AGENT_RULES_WORKSPACE"),
        "container_workspace": os.environ.get("AGENT_RULES_CONTAINER_WORKSPACE"),
    }) + "\\n")
if name == "python" and sys.argv[1] == "-":
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
if name in {"codex", "claude"}:
    print("fake CLI" if sys.argv[1] == "--version" else '{"loggedIn": true}')
'''
    for path in [venv / "bin/python", *(tools / name for name in ["docker", "curl", "codex", "claude"])]:
        path.write_text(launcher)
        path.chmod(0o755)
    token = tmp_path / "bridge-token"
    token.write_text("test-token-already-created")
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    env = os.environ.copy()
    env.update(
        PATH=str(tools) + os.pathsep + env["PATH"],
        SCRIPT_CALLS=str(log),
        AGENT_RULES_VENV=str(venv),
        AGENT_RULES_BRIDGE_TOKEN=str(token),
        AGENT_RULES_CODEX=str(tools / "codex"),
        AGENT_RULES_CLAUDE=str(tools / "claude"),
    )
    for key in ["AGENT_RULES_WORKSPACE", "AGENT_RULES_CONTAINER_WORKSPACE", "AGENT_RULES_PORT", "PYTHONPATH"]:
        env.pop(key, None)
    return env, log, workspace


@pytest.mark.parametrize("script", ["start", "stop", "check"])
def test_docker_command_from_outside_checkout(tmp_path, shell_environment, script):
    env, log, workspace = shell_environment
    arguments = ["--port", "8877", str(workspace)] if script == "start" else []
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/docker" / f"{script}.sh"), *arguments],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(Path(call["cwd"]) == ROOT for call in calls)
    if script in {"start", "check"}:
        for provider, auth in [("codex", ["login", "status"]), ("claude", ["auth", "status"])]:
            assert [call["args"] for call in calls if call["tool"] == provider] == [["--version"], auth]
        assert "[ok  ]" in result.stdout
    if script == "start":
        docker = next(call for call in calls if call["tool"] == "docker")
        assert docker["args"] == ["compose", "up", "--build", "-d"]
        assert docker["workspace"] == docker["container_workspace"] == str(workspace)
        bridge = calls[-1]
        assert bridge["tool"] == "python"
        assert bridge["args"] == [
            "scripts/ai_bridge.py", "--workspace", str(workspace),
            "--token-file", env["AGENT_RULES_BRIDGE_TOKEN"],
            "--url", "http://127.0.0.1:8877",
        ]
    elif script == "stop":
        assert calls[0]["args"] == ["compose", "down"]
        assert calls[0]["workspace"] == str(ROOT)
