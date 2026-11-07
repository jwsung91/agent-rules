"""Exercise the Linux/WSL launch scripts with fake Docker, pip, and host AI CLIs."""

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
    reason="Launch scripts target Linux/WSL with Bash",
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
        # The existing venv is still reconciled with the pinned requirements.
        assert calls[0]["tool"] == "python"
        assert calls[0]["args"][:4] == ["-m", "pip", "install", "-q"]
        assert calls[0]["args"][-2:] == ["-r", "requirements-gui.txt"]
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


@pytest.mark.parametrize("port", ["80", "1023", "65536", "abc"])
def test_docker_start_rejects_ports_the_gui_refuses(tmp_path, shell_environment, port):
    env, log, workspace = shell_environment
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/docker/start.sh"), "--port", port, str(workspace)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 2
    assert "1024-65535" in result.stderr
    assert not log.exists()


def test_local_start_from_outside_checkout(tmp_path, shell_environment):
    env, log, workspace = shell_environment
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/local/start.sh"), workspace.name, "--port", "8866"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(Path(call["cwd"]) == ROOT for call in calls)
    assert [call["tool"] for call in calls] == ["python", "python"]
    assert calls[0]["args"][:3] == ["-m", "pip", "install"]
    # The relative workspace resolves against the caller, not the checkout.
    assert calls[1]["args"] == [
        "scripts/gui.py", "--workspace", str(workspace), "--port", "8866",
    ]


def test_local_start_rejects_missing_workspace(tmp_path, shell_environment):
    env, log, _ = shell_environment
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/local/start.sh"), "missing-folder"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert not log.exists()


@pytest.mark.parametrize("arguments", [[], ["--port", "8866"]])
def test_local_start_defaults_to_checkout_parent(tmp_path, shell_environment, arguments):
    env, log, _ = shell_environment
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/local/start.sh"), *arguments],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[-1]["args"] == ["scripts/gui.py", "--workspace", str(ROOT.parent), *arguments]


def test_docker_start_resolves_relative_workspace_and_default(tmp_path, shell_environment):
    env, log, workspace = shell_environment
    for arguments, expected in (([workspace.name], workspace), ([], ROOT.parent)):
        log.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/docker/start.sh"), *arguments],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        docker = next(json.loads(line) for line in log.read_text().splitlines()
                      if json.loads(line)["tool"] == "docker")
        assert docker["workspace"] == docker["container_workspace"] == str(expected)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/docker/start.sh"), "missing-folder"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 2 and "usage:" in result.stderr


def test_docker_start_stops_previous_bridge(tmp_path, shell_environment):
    env, log, workspace = shell_environment
    stale = subprocess.Popen(
        [sys.executable, "-c",
         "import signal, sys, time\n"
         "signal.signal(signal.SIGINT, lambda *_: sys.exit(42))\n"
         "time.sleep(30)",
         "scripts/ai_bridge.py", "--workspace", str(workspace),
         "--token-file", env["AGENT_RULES_BRIDGE_TOKEN"]],
    )
    try:
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/docker/start.sh"), str(workspace)],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"Stopping the previous host AI bridge (PID {stale.pid})" in result.stdout
        assert stale.wait(timeout=5) == 42
    finally:
        stale.kill()


@pytest.mark.parametrize(
    ("arguments", "mode", "tool"),
    [(["--local"], "local", "python"), ([], "docker", "docker")],
)
def test_root_start_selects_mode(tmp_path, shell_environment, arguments, mode, tool):
    env, log, workspace = shell_environment
    result = subprocess.run(
        ["bash", str(ROOT / "start.sh"), *arguments, "--port", "8877", str(workspace)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"agent-rules GUI: {mode} mode" in result.stderr
    tools = [json.loads(line)["tool"] for line in log.read_text().splitlines()]
    assert tool in tools
    if mode == "local":
        assert "docker" not in tools


def test_root_stop_runs_compose_down(tmp_path, shell_environment):
    env, log, _ = shell_environment
    result = subprocess.run(
        ["bash", str(ROOT / "stop.sh")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(log.read_text().splitlines()[0])["args"] == ["compose", "down"]
