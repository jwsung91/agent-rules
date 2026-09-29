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
