from __future__ import annotations

import sys
from pathlib import Path
import subprocess
from unittest import mock

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_rules.gui_service import DeploymentService  # noqa: E402
from agent_rules.gui_web import create_app  # noqa: E402


@pytest.fixture
def gui(tmp_path):
    repo = tmp_path / "sample"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    service = DeploymentService(tmp_path, str(ROOT))
    client = TestClient(
        create_app(service, 8765, "test-token"), base_url="http://127.0.0.1:8765"
    )
    client.headers["X-Session-Token"] = "test-token"
    with client:
        yield client, service, repo


def selection(repo, **overrides):
    return {
        "path": str(repo),
        "profile": "codex",
        "visibility": "local",
        "skills": True,
        "operation": "install",
        **overrides,
    }


def preview(client, repo, **overrides):
    response = client.post("/api/preview", json=selection(repo, **overrides))
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0, response.text
    return response.json()


def test_discover_preview_apply_sync_and_check(gui):
    client, _, repo = gui
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    found = client.post("/api/discover", json={}).json()["repositories"]
    assert [r["path"] for r in found] == [str(repo)]
    plan = preview(client, repo)
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / ".gitignore").exists()
    assert ".gitignore" in [f["path"] for f in plan["files"]]
    result = client.post("/api/apply", json={"token": plan["token"]})
    assert result.json()["code"] == 0, result.text
    assert (repo / ".agents/skills/review-change/SKILL.md").is_file()
    check = client.post("/api/check", json=selection(repo))
    assert check.status_code == 200
    assert check.json()["code"] in (0, 2), check.text
    again = preview(client, repo, operation="sync")
    assert again["files"] == []
    assert client.post("/api/apply", json={"token": plan["token"]}).status_code == 400


def test_changed_file_invalidates_approval(gui):
    client, _, repo = gui
    plan = preview(client, repo)
    (repo / "AGENTS.md").write_text("user edit", encoding="utf-8")
    result = client.post("/api/apply", json={"token": plan["token"]})
    assert result.status_code == 400
    assert (repo / "AGENTS.md").read_text() == "user edit"
    assert not (repo / ".agents").exists()


def test_source_change_and_expiry_invalidate_approval(gui):
    client, service, repo = gui
    plan = preview(client, repo)
    with mock.patch.object(service, "fingerprint", return_value="changed"):
        assert (
            client.post("/api/apply", json={"token": plan["token"]}).status_code == 400
        )
    plan = preview(client, repo)
    service.previews[plan["token"]].expires = 0
    assert client.post("/api/apply", json={"token": plan["token"]}).status_code == 400
    assert not (repo / "AGENTS.md").exists()


def test_conflict_has_no_apply_token(gui):
    client, _, repo = gui
    (repo / "AGENTS.md").write_text("user content", encoding="utf-8")
    result = client.post("/api/preview", json=selection(repo)).json()
    assert result["code"] != 0
    assert result["token"] is None
    assert (repo / "AGENTS.md").read_text() == "user content"


def test_unsafe_http_requests_and_concurrent_operations_are_rejected(gui):
    client, service, _ = gui
    assert (
        client.post(
            "/api/discover", json={}, headers={"X-Session-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/session", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/session", headers={"Host": "evil.example"}).status_code == 403
    )
    assert (
        client.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )
    assert client.post("/api/discover", content="{}").status_code == 415
    with service.lock:
        assert client.post("/api/discover", json={}).status_code == 409


def test_outside_workspace_and_symlink_destinations_are_rejected(gui, tmp_path):
    client, _, repo = gui
    assert client.post("/api/preview", json=selection(ROOT)).status_code == 400
    outside = tmp_path / "external"
    outside.mkdir()
    try:
        (repo / ".agents").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable for this account")
    assert client.post("/api/preview", json=selection(repo)).status_code == 400
    assert not list(outside.iterdir())


def test_write_failure_reports_partial_progress(gui):
    client, _, repo = gui
    plan = preview(client, repo)
    with mock.patch(
        "agent_rules.gui_service.apply_plan", side_effect=OSError("disk full")
    ):
        response = client.post("/api/apply", json={"token": plan["token"]})
    assert response.json()["code"] == 1
    assert "disk full" in response.json()["log"]
    assert client.post("/api/apply", json={"token": plan["token"]}).status_code == 400


def test_reviewed_boundaries_preview_apply_and_stale_guard(gui):
    client, _, repo = gui
    proposal = "Keep public interfaces backward compatible."
    data = {**selection(repo), "boundaries": [proposal]}
    plan = client.post("/api/preview", json=data).json()
    assert plan["code"] == 0
    assert any(proposal in f["diff"] for f in plan["files"])
    assert not (repo / "AGENTS.md").exists()
    assert client.post("/api/apply", json={"token": plan["token"]}).json()["code"] == 0
    assert proposal in (repo / "AGENTS.md").read_text()
    data.update(operation="sync", boundaries=["Preserve migration history."])
    updated = client.post("/api/preview", json=data).json()
    assert updated["code"] == 0
    (repo / "AGENTS.md").write_text("user edit")
    assert (
        client.post("/api/apply", json={"token": updated["token"]}).status_code == 400
    )


def test_ai_context_and_mocked_proposal_do_not_write(gui, tmp_path):
    client, _, repo = gui
    memory = repo / "MEMORY.md"
    memory.write_text("Previous decision: retain API compatibility.")
    context = client.post("/api/ai/context", json={"path": str(repo)})
    assert str(memory) in context.json()["files"]
    with mock.patch(
        "agent_rules.gui_ai.analyze",
        return_value={
            "rules": [],
            "questions": [],
            "memories_used": [],
            "memory_files": [],
        },
    ):
        response = client.post("/api/ai/analyze", json={"path": str(repo)})
    assert response.status_code == 200
    assert not (repo / "AGENTS.md").exists()
    bad = client.post(
        "/api/ai/context", json={"path": str(repo), "memories": ["relative.md"]}
    )
    assert bad.status_code == 400
    assert client.post("/api/ai/analyze", json={"path": str(ROOT)}).status_code == 400


def test_ai_output_validation_and_read_only_invocation(gui):
    from agent_rules.gui_ai import analyze

    _, _, repo = gui
    response = {
        "rules": [{"text": "Keep API stable.", "evidence": "README.md"}],
        "questions": [],
        "memories_used": [],
    }

    def run(command, **kwargs):
        assert command[:5] == ["codex", "-a", "never", "exec", "--sandbox"]
        assert command[5] == "read-only"
        assert kwargs["cwd"] == repo
        Path(command[command.index("-o") + 1]).write_text(
            __import__("json").dumps(response)
        )
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (None, None)
        return process

    with (
        mock.patch(
            "agent_rules.gui_ai.connection",
            return_value={"ready": True, "path": "codex"},
        ),
        mock.patch("agent_rules.gui_ai.subprocess.Popen", side_effect=run),
    ):
        assert analyze(repo, "", [])["rules"][0]["text"] == "Keep API stable."
        response["memories_used"] = ["unknown.md"]
        with pytest.raises(ValueError, match="메모리"):
            analyze(repo, "", [])


def test_ai_timeout_stops_process_group(gui):
    import os
    from agent_rules.gui_ai import analyze

    _, _, repo = gui
    process = mock.Mock(pid=12345)
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("codex", 300),
        (None, None),
    ]
    with (
        mock.patch(
            "agent_rules.gui_ai.connection",
            return_value={"ready": True, "path": "codex"},
        ),
        mock.patch("agent_rules.gui_ai.subprocess.Popen", return_value=process),
        mock.patch("agent_rules.gui_ai.subprocess.run") as run,
        mock.patch("agent_rules.gui_ai.os.killpg", create=True) as killpg,
    ):
        with pytest.raises(ValueError, match="5분"):
            analyze(repo, "", [])
        process.kill.assert_called_once()
        if os.name == "nt":
            run.assert_called_once()
        else:
            killpg.assert_called_once()


def test_home_memories_respect_custom_home_and_project(gui, tmp_path, monkeypatch):
    from agent_rules.gui_ai import home_memories

    _, _, repo = gui
    home = tmp_path / "codex-home"
    memories = home / "memories"
    memories.mkdir(parents=True)
    (memories / "sample-decisions.md").write_text("project memory")
    (memories / "other-project.md").write_text("unrelated")
    monkeypatch.setenv("CODEX_HOME", str(home))
    result = home_memories(repo)
    assert result["roots"][0] == str(memories)
    assert {p["name"]: p["recommended"] for p in result["files"]} == {
        "other-project.md": False,
        "sample-decisions.md": True,
    }


def test_ai_models_endpoint(gui):
    client, _, _ = gui
    with mock.patch(
        "agent_rules.gui_ai.models",
        return_value={"models": [{"model": "test", "name": "Test", "default": True}]},
    ):
        response = client.post("/api/ai/models", json={})
    assert response.status_code == 200
    assert response.json()["models"][0]["model"] == "test"
