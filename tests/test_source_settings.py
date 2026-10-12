"""Source selection must agree across lookup, metadata, and GUI operations."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_rules import source  # noqa: E402
from agent_rules.gui.service import DeploymentService  # noqa: E402
from agent_rules.metadata import parse_metadata  # noqa: E402


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_selected_branch_lookup_and_cache(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "fetch", str(ROOT), "HEAD")
    main = git(tmp_path, "rev-parse", "FETCH_HEAD")
    stable = main
    git(tmp_path, "update-ref", "refs/heads/main", main)
    git(tmp_path, "update-ref", "refs/heads/stable", stable)
    url = str(tmp_path)
    assert source.get_source_status(url).remote_head == main
    status = source.get_source_status(url, "stable")
    assert status.remote_head == stable
    assert status.source_ref == "stable"
    assert source.get_source_status(url, "missing").remote_head is None
    assert source.get_source_status(url).remote_head == main


def test_gui_selected_source_metadata_and_check(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init")
    shared = tmp_path / "source"
    shared.mkdir()
    git(shared, "init")
    git(shared, "fetch", str(ROOT), "HEAD")
    git(shared, "update-ref", "refs/heads/stable", "FETCH_HEAD")
    branch = "stable"
    service = DeploymentService(tmp_path, str(shared), source_ref=branch)
    preview = service.preview(str(repo), "all", "local", False, "install")
    assert preview["code"] == 0
    assert service.apply(preview["token"])["code"] == 0
    for filename in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        metadata = parse_metadata((repo / filename).read_text())
        assert metadata["source"] == str(shared)
        assert metadata["source_ref"] == branch
    result = service.check(str(repo), "all", "local", False)
    assert f"remote {branch} HEAD:" in result["log"]
    synced = service.preview(str(repo), "all", "local", False, "sync")
    assert synced["code"] == 0
    assert synced["files"] == []


def test_gui_depth_survives_browse_and_workspace_change(tmp_path):
    workspace = tmp_path / "workspace"
    repo = workspace / "one" / "two" / "three" / "project"
    repo.mkdir(parents=True)
    git(repo, "init")
    assert DeploymentService(workspace).discover()["repositories"] == []
    service = DeploymentService(tmp_path, str(ROOT), max_depth=5)
    assert service.browse(str(workspace))["repository_count"] == 1
    assert service.change_workspace(str(workspace))["repositories"][0]["path"] == str(repo)
    assert service.discover()["repositories"][0]["path"] == str(repo)


@pytest.mark.parametrize("branch", ["", "-bad", "bad\nbranch", "bad..branch", "bad branch"])
def test_invalid_source_branch(branch):
    with pytest.raises(ValueError):
        source.parse_source_ref(branch)


def test_gui_rejects_nonpositive_depth(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        DeploymentService(tmp_path, max_depth=0)


def test_cli_batch_uses_selected_branch(tmp_path):
    shared = tmp_path / "source"
    shared.mkdir()
    git(shared, "init")
    git(shared, "fetch", str(ROOT), "HEAD")
    git(shared, "update-ref", "refs/heads/stable", "FETCH_HEAD")
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init")
    batch = tmp_path / "repos.txt"
    batch.write_text(str(repo) + "\n", encoding="utf-8")
    command = [
        sys.executable, str(ROOT / "scripts/adopt.py"), "--batch", str(batch),
        "--shared-url", str(shared), "--source-ref", "stable", "--profile", "codex",
        "--validation", "python -m pytest", "--boundary", "Preserve public APIs.",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert parse_metadata((repo / "AGENTS.md").read_text())["source_ref"] == "stable"
    checked = subprocess.run(command + ["--check"], capture_output=True, text=True, timeout=20)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "remote stable HEAD:" in checked.stdout


@pytest.mark.parametrize("options", [["--max-depth", "0"], ["--source-ref", "bad..branch"]])
def test_gui_launch_rejects_invalid_settings(tmp_path, options):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gui.py"), "--workspace", str(tmp_path), *options],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "error:" in result.stderr
