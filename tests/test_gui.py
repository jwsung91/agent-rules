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


def test_discover_skips_hidden_directories(gui):
    _, service, repo = gui
    hidden = service.workspace / ".tool" / "plugin"
    hidden.mkdir(parents=True)
    subprocess.run(["git", "init", str(hidden)], check=True, capture_output=True)
    found = service.discover()["repositories"]
    assert [r["path"] for r in found] == [str(repo)]


def test_ai_memories_rejects_path_outside_workspace(gui, tmp_path_factory):
    client, _, _ = gui
    outside = tmp_path_factory.mktemp("outside")
    response = client.post("/api/ai/memories", json={"path": str(outside)})
    assert response.status_code == 400, response.text


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


def test_workspace_browse_switch_and_preview_invalidation(gui, tmp_path):
    client, service, repo = gui
    plan = preview(client, repo)
    sibling = tmp_path.parent / (tmp_path.name + "-alternate")
    sibling.mkdir()
    other = sibling / "other"
    other.mkdir()
    subprocess.run(["git", "init", str(other)], check=True, capture_output=True)
    (sibling / "not-a-directory.txt").write_text("file")
    listing = client.post("/api/workspace/browse", json={"path": str(sibling)})
    assert listing.status_code == 200
    assert [x["name"] for x in listing.json()["directories"]] == ["other"]
    assert service.workspace == tmp_path
    invalid = client.post(
        "/api/workspace/change", json={"path": str(sibling / "missing")}
    )
    assert invalid.status_code == 400
    assert service.workspace == tmp_path
    assert plan["token"] in service.previews
    changed = client.post("/api/workspace/change", json={"path": str(sibling)})
    assert changed.status_code == 200
    assert service.workspace == sibling
    assert [x["path"] for x in changed.json()["repositories"]] == [str(other)]
    assert client.post("/api/apply", json={"token": plan["token"]}).status_code == 400
    assert client.post("/api/check", json=selection(repo)).status_code == 400
    assert client.get("/api/session").json()["workspace"] == str(sibling)


def test_workspace_paths_and_session_guards(gui):
    client, service, repo = gui
    for endpoint in ["browse", "change"]:
        assert (
            client.post(
                f"/api/workspace/{endpoint}", json={"path": "relative"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"/api/workspace/{endpoint}",
                json={"path": str(repo)},
                headers={"X-Session-Token": "wrong"},
            ).status_code
            == 403
        )
    with service.lock:
        assert (
            client.post("/api/workspace/change", json={"path": str(repo)}).status_code
            == 409
        )


def test_workspace_path_suggestions_are_read_only(gui, tmp_path):
    import os

    client, service, _ = gui
    (tmp_path / "example one").mkdir()
    (tmp_path / "example two").mkdir()
    (tmp_path / "example.txt").write_text("not a directory")
    response = client.post(
        "/api/workspace/suggest", json={"path": str(tmp_path / "exam")}
    )
    assert response.status_code == 200
    assert response.json()["paths"] == [
        str(tmp_path / name) + os.sep for name in ("example one", "example two")
    ]
    assert service.workspace == tmp_path
    assert (
        client.post("/api/workspace/suggest", json={"path": "relative"}).json()["paths"]
        == []
    )
    assert (
        client.post(
            "/api/workspace/suggest", json={"path": str(tmp_path / "missing") + os.sep}
        ).json()["paths"]
        == []
    )


def test_workspace_suggestions_hide_dot_directories_unless_typed(gui, tmp_path):
    import os

    client, _, _ = gui
    (tmp_path / ".cache").mkdir()
    paths = client.post(
        "/api/workspace/suggest", json={"path": str(tmp_path) + os.sep}
    ).json()["paths"]
    assert str(tmp_path / ".cache") + os.sep not in paths
    assert str(tmp_path / "sample") + os.sep in paths
    typed = client.post(
        "/api/workspace/suggest", json={"path": str(tmp_path / ".c")}
    ).json()["paths"]
    assert typed == [str(tmp_path / ".cache") + os.sep]


def test_claude_proposal_restricts_tools_and_parses_envelope(gui):
    import json
    from agent_rules.gui_ai import analyze

    _, _, repo = gui
    payload = {
        "is_error": False,
        "structured_output": {"rules": [], "questions": [], "memories_used": []},
    }

    def run(command, **kwargs):
        assert command[0] == "claude"
        for option in (
            "--restricted",
            "--safe-mode",
            "--strict-mcp-config",
            "--no-session-persistence",
        ):
            assert option in command
        assert command[command.index("--tools") + 1] == "Read,Glob,Grep"
        assert command[command.index("--permission-mode") + 1] == "dontAsk"
        assert command[command.index("--model") + 1] == "sonnet"
        assert kwargs["cwd"] == repo
        kwargs["stdout"].write(json.dumps(payload))
        kwargs["stdout"].flush()
        return mock.Mock(returncode=0)

    with (
        mock.patch(
            "agent_rules.gui_ai.connection",
            return_value={"ready": True, "path": "claude"},
        ),
        mock.patch("agent_rules.gui_ai.subprocess.Popen", side_effect=run),
    ):
        assert analyze(repo, "sonnet", [], "claude")["rules"] == []
        payload["is_error"] = True
        with pytest.raises(ValueError, match="반환하지"):
            analyze(repo, "sonnet", [], "claude")


def test_ai_provider_routing_and_validation(gui):
    client, _, repo = gui
    with mock.patch(
        "agent_rules.gui_ai.analyze", return_value={"rules": []}
    ) as analyze:
        response = client.post(
            "/api/ai/analyze",
            json={"path": str(repo), "provider": "claude", "model": "sonnet"},
        )
        assert response.status_code == 200
        analyze.assert_called_once_with(repo, "sonnet", [], "claude")
    for endpoint in ("models", "connection", "analyze"):
        assert (
            client.post(f"/api/ai/{endpoint}", json={"provider": "unknown"}).status_code
            == 422
        )
    response = client.post("/api/ai/models", json={"provider": "claude"})
    assert {m["model"] for m in response.json()["models"]} == {
        "sonnet",
        "opus",
        "haiku",
    }
    assert "message" in response.json()


def test_claude_auth_requires_logged_in_state(monkeypatch):
    from agent_rules.gui_ai import connection

    monkeypatch.setattr("agent_rules.gui_ai.executable", lambda provider: "claude")
    with mock.patch(
        "agent_rules.gui_ai.subprocess.run",
        side_effect=[
            mock.Mock(returncode=0, stdout="Claude Code"),
            mock.Mock(returncode=0, stdout='{"loggedIn": false}'),
        ],
    ):
        assert not connection("claude")["ready"]


def test_claude_memory_respects_config_directory(gui, tmp_path, monkeypatch):
    import re
    from agent_rules.gui_ai import memory_files, home_memories

    _, _, repo = gui
    home = tmp_path / "claude-home"
    memory = (
        home
        / "projects"
        / re.sub(r"[^a-zA-Z0-9-]", "-", str(repo))
        / "memory"
        / "MEMORY.md"
    )
    memory.parent.mkdir(parents=True)
    memory.write_text("Project decision")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    assert memory in memory_files(repo)
    assert any(
        row["path"] == str(memory) and row["recommended"]
        for row in home_memories(repo)["files"]
    )


def test_distribution_commit_used_without_git(tmp_path):
    from agent_rules.source import local_source_head

    commit = "a" * 40
    (tmp_path / ".source-commit").write_text(commit)
    assert local_source_head(tmp_path) == (commit, None)
    (tmp_path / ".source-commit").write_text("HEAD")
    assert local_source_head(tmp_path)[0] is None
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    # A checkout must never mask an invalid HEAD with distribution metadata.
    assert local_source_head(tmp_path)[0] is None


def test_folder_selection_requires_selectable_git_repository(gui, tmp_path):
    client, service, repo = gui
    plain = tmp_path / "documents"
    plain.mkdir()
    (repo / "src").mkdir()
    listing = client.post("/api/workspace/browse", json={"path": str(tmp_path)}).json()
    assert listing["repository_count"] == 1
    assert {d["name"]: d["is_repository"] for d in listing["directories"]} == {
        "documents": False,
        "sample": True,
    }
    for folder in (plain, repo / "src"):
        assert (
            client.post("/api/workspace/browse", json={"path": str(folder)}).json()[
                "repository_count"
            ]
            == 0
        )
        response = client.post("/api/workspace/change", json={"path": str(folder)})
        assert response.status_code == 400
        assert service.workspace == tmp_path
    assert (
        client.post("/api/workspace/change", json={"path": str(repo)}).status_code
        == 200
    )
    assert ".git" not in [
        d["name"]
        for d in client.post("/api/workspace/browse", json={"path": str(repo)}).json()[
            "directories"
        ]
    ]


def test_folder_selection_accepts_git_file_and_rejects_fake_marker(gui, tmp_path):
    client, _, _ = gui
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "init", "--separate-git-dir", str(tmp_path / "metadata"), str(linked)],
        check=True,
        capture_output=True,
    )
    assert (linked / ".git").is_file()
    assert (
        client.post("/api/workspace/browse", json={"path": str(linked)}).json()[
            "repository_count"
        ]
        == 1
    )
    assert (
        client.post("/api/workspace/change", json={"path": str(linked)}).status_code
        == 200
    )
    fake = tmp_path / "fake"
    (fake / ".git").mkdir(parents=True)
    assert (
        client.post("/api/workspace/change", json={"path": str(fake)}).status_code
        == 400
    )


def test_agent_status_uses_actual_files_and_refreshes_after_apply(gui):
    client, service, repo = gui
    assert service.agent_status(repo) == dict.fromkeys(("codex", "claude", "gemini"), "미설치")
    plan = preview(client, repo, profile="all")
    assert client.post("/api/apply", json={"token": plan["token"]}).json()["code"] == 0
    statuses = dict.fromkeys(("codex", "claude", "gemini"), "설치됨")
    assert client.post("/api/check", json=selection(repo, profile="all")).json()["agents"] == statuses
    (repo / "CLAUDE.md").unlink()
    (repo / "GEMINI.md").write_text("My own rules")
    found = client.post("/api/discover", json={}).json()["repositories"][0]
    assert found["agents"] == {"codex": "설치됨", "claude": "미설치", "gemini": "사용자 규칙"}
