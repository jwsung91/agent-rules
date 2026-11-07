"""Persisted AI proposals survive GUI restarts without leaking or corrupting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_rules.gui import proposals  # noqa: E402

PROPOSAL = {
    "rules": [{"text": "Keep API stable.", "evidence": "README.md"}],
    "questions": [],
    "memories_used": [],
    "memory_files": [],
}


def git_repo(path: Path) -> Path:
    path.mkdir()
    for command in (
        ["git", "init"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "one"],
    ):
        subprocess.run(command, cwd=path, check=True, capture_output=True)
    return path


def commit(repo: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "next"],
        cwd=repo, check=True, capture_output=True,
    )


def test_save_and_load_round_trip(tmp_path):
    repo = git_repo(tmp_path / "repo")
    assert proposals.load(repo) == {"saved": None}
    path = proposals.save(repo, "claude", "sonnet", ["/m.md"], PROPOSAL)
    assert path.parent == Path(os.environ["AGENT_RULES_PROPOSAL_DIR"])
    assert not (repo / ".agent-rules").exists()
    saved = proposals.load(repo)["saved"]
    assert saved["proposal"] == PROPOSAL
    assert (saved["provider"], saved["model"], saved["memories"]) == ("claude", "sonnet", ["/m.md"])
    assert saved["stale"] is False
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_latest_proposal_replaces_previous_and_marks_stale(tmp_path):
    repo = git_repo(tmp_path / "repo")
    proposals.save(repo, "codex", "", [], PROPOSAL)
    newer = {**PROPOSAL, "questions": ["Which branch?"]}
    proposals.save(repo, "codex", "", [], newer)
    assert proposals.load(repo)["saved"]["proposal"] == newer
    commit(repo)
    assert proposals.load(repo)["saved"]["stale"] is True


def test_failed_write_keeps_previous_record(tmp_path):
    repo = git_repo(tmp_path / "repo")
    path = proposals.save(repo, "codex", "", [], PROPOSAL)
    with mock.patch("agent_rules.gui.proposals.json.dump", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            proposals.save(repo, "codex", "", [], {**PROPOSAL, "questions": ["lost"]})
    assert proposals.load(repo)["saved"]["proposal"] == PROPOSAL
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_unreadable_or_foreign_records_are_ignored(tmp_path):
    repo = git_repo(tmp_path / "repo")
    path = proposals.record_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert proposals.load(repo) == {"saved": None}
    path.write_text(json.dumps({"version": 1, "repo": "/elsewhere", "proposal": {}}), encoding="utf-8")
    assert proposals.load(repo) == {"saved": None}


def test_analyze_persists_result_and_survives_cache_failure(tmp_path):
    from agent_rules.gui.ai import analyze

    repo = git_repo(tmp_path / "repo")
    response = {key: PROPOSAL[key] for key in ("rules", "questions", "memories_used")}

    real_popen = subprocess.Popen

    def run(command, **kwargs):
        # Patching ai.subprocess.Popen patches the shared module; let git through.
        if command[0] == "git":
            return real_popen(command, **kwargs)
        Path(command[command.index("-o") + 1]).write_text(json.dumps(response))
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (None, None)
        return process

    with (
        mock.patch("agent_rules.gui.ai.connection", return_value={"ready": True, "path": "codex"}),
        mock.patch("agent_rules.gui.ai.subprocess.Popen", side_effect=run),
    ):
        result = analyze(repo, "", [])
        assert result["saved"] is True
        saved = proposals.load(repo)["saved"]
        assert saved["proposal"]["rules"] == response["rules"]
        assert "saved" not in saved["proposal"]
        with mock.patch("agent_rules.gui.proposals.save", side_effect=OSError("read-only")):
            assert analyze(repo, "", [])["saved"] is False


def test_saved_endpoint_and_bridge_job(tmp_path):
    from fastapi.testclient import TestClient

    from agent_rules.gui.bridge import Job, run_job
    from agent_rules.gui.service import DeploymentService
    from agent_rules.gui.web import create_app

    repo = git_repo(tmp_path / "sample")
    proposals.save(repo, "codex", "", [], PROPOSAL)
    client = TestClient(
        create_app(DeploymentService(tmp_path, str(ROOT)), 8765, "test-token"),
        base_url="http://127.0.0.1:8765",
    )
    client.headers["X-Session-Token"] = "test-token"
    with client:
        response = client.post("/api/ai/saved", json={"path": str(repo)})
        assert response.status_code == 200, response.text
        assert response.json()["saved"]["proposal"] == PROPOSAL
        assert client.post("/api/ai/saved", json={"path": str(ROOT)}).status_code == 400
    job = Job(id="saved", action="saved", path="sample")
    assert run_job(job, tmp_path, [])["saved"]["proposal"] == PROPOSAL
