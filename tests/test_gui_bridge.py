"""Host bridge authentication, routing and workspace boundary regression tests."""

import concurrent.futures
import sys
from pathlib import Path
import subprocess
import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_rules.gui_bridge import HostBridge, Job, Reply, host_target, run_job  # noqa: E402
from agent_rules.gui_service import DeploymentService, GuiError  # noqa: E402
from agent_rules.gui_web import create_app  # noqa: E402


@pytest.fixture
def bridge_app(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("a" * 48)
    monkeypatch.setenv("AGENT_RULES_BRIDGE_FILE", str(token_file))
    repo = tmp_path / "sample"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    app = create_app(DeploymentService(tmp_path), 8765, "browser-token")
    client = TestClient(
        app,
        base_url="http://127.0.0.1:8765",
        headers={"X-Session-Token": "browser-token"},
    )
    return client, app.state.host_bridge, repo


def test_bridge_auth_is_separate_and_not_returned_to_browser(bridge_app):
    client, bridge, _ = bridge_app
    session = client.get("/api/session").json()
    assert session["ai_execution"] == "host"
    assert bridge.token not in str(session)
    assert client.post("/api/bridge/poll", json={}).status_code == 403
    assert (
        client.post(
            "/api/bridge/poll",
            json={},
            headers={"X-Bridge-Token": bridge.token, "Origin": "http://evil.example"},
        ).status_code
        == 403
    )
    assert client.post(
        "/api/bridge/poll", json={}, headers={"X-Bridge-Token": bridge.token}
    ).json() == {"job": None}
    # The worker credential cannot apply repository changes.
    assert (
        client.post(
            "/api/apply",
            json={"token": "unused"},
            headers={"X-Session-Token": "", "X-Bridge-Token": bridge.token},
        ).status_code
        == 403
    )


def test_bridge_routes_relative_path_and_never_runs_container_cli(bridge_app):
    client, bridge, repo = bridge_app
    worker_headers = {"X-Bridge-Token": bridge.token}
    client.post("/api/bridge/poll", json={}, headers=worker_headers)
    with (
        mock.patch(
            "agent_rules.gui_ai.analyze",
            side_effect=AssertionError("container CLI must not run"),
        ),
        concurrent.futures.ThreadPoolExecutor() as executor,
    ):
        response = executor.submit(
            client.post,
            "/api/ai/analyze",
            json={"path": str(repo), "provider": "claude", "model": "sonnet"},
        )
        deadline = time.monotonic() + 5
        job = None
        while not job and time.monotonic() < deadline:
            job = client.post(
                "/api/bridge/poll", json={}, headers=worker_headers
            ).json()["job"]
            if not job:
                time.sleep(0.01)
        assert job and job["path"] == "sample" and job["provider"] == "claude"
        assert (
            client.post("/api/bridge/poll", json={}, headers=worker_headers).json()[
                "job"
            ]
            is None
        )
        result = {
            "id": job["id"],
            "result": {
                "rules": [],
                "questions": [],
                "memories_used": [],
                "memory_files": [],
            },
        }
        assert (
            client.post(
                "/api/bridge/result", json=result, headers=worker_headers
            ).status_code
            == 200
        )
        assert response.result(timeout=5).json()["rules"] == []
        assert (
            client.post(
                "/api/bridge/result", json=result, headers=worker_headers
            ).status_code
            == 409
        )


def test_bridge_disconnected_timeout_and_outside_mapping(tmp_path):
    bridge = HostBridge("a" * 48, tmp_path)
    with pytest.raises(GuiError, match="꺼져"):
        bridge.call("models")
    bridge.poll()
    with pytest.raises(GuiError, match="작업 경로"):
        bridge.call("analyze", repo=tmp_path.parent)
    with pytest.raises(GuiError, match="초과"):
        bridge.call("models", timeout=0.01)
    assert bridge.pending is None
    with pytest.raises(GuiError):
        bridge.complete(Reply(id="expired", result={}))


def test_host_paths_and_memory_limits(tmp_path):
    repo = tmp_path / "sample"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    assert host_target(tmp_path, "sample") == repo
    for path in ("../outside", "/outside", "C:/outside", "..\\outside"):
        with pytest.raises(ValueError):
            host_target(tmp_path, path)
    job = Job(
        id="test",
        action="analyze",
        provider="codex",
        path="sample",
        memories=[str(tmp_path.parent / "private.md")],
    )
    with pytest.raises(ValueError, match="memory-root"):
        run_job(job, tmp_path, [])
    job.memories = []
    with mock.patch(
        "agent_rules.gui_ai.analyze", return_value={"rules": []}
    ) as analyze:
        assert run_job(job, tmp_path, []) == {"rules": []}
        analyze.assert_called_once_with(repo, "", [], "codex")


def test_host_does_not_follow_project_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation not available")
    with pytest.raises(ValueError, match="심볼릭"):
        host_target(workspace, "linked")
