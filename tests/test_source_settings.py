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
    git(tmp_path, "fetch", "--update-shallow", str(ROOT), "HEAD")
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
    git(shared, "fetch", "--update-shallow", str(ROOT), "HEAD")
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
    git(shared, "fetch", "--update-shallow", str(ROOT), "HEAD")
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


def test_source_status_cache_expires(monkeypatch):
    from unittest import mock

    source._SOURCE_STATUS_CACHE.clear()
    heads = iter(["a" * 40, "b" * 40])
    now = [1000.0]
    monkeypatch.setattr(source.time, "monotonic", lambda: now[0])
    with (
        mock.patch.object(source, "local_source_head", side_effect=lambda: (next(heads), None)),
        mock.patch.object(source, "remote_main_head", return_value=("c" * 40, None)),
        mock.patch.object(source, "resolve_latest_status", return_value="different"),
    ):
        first = source.get_source_status("https://example.invalid/rules")
        now[0] += source.SOURCE_STATUS_TTL - 1
        assert source.get_source_status("https://example.invalid/rules") is first
        # A long-running GUI must see a pulled checkout instead of stamping
        # generated files with the commit it saw at startup.
        now[0] += 2
        assert source.get_source_status("https://example.invalid/rules").local_head == "b" * 40
    source._SOURCE_STATUS_CACHE.clear()


@pytest.mark.parametrize(
    ("variable", "value"), [("AGENT_RULES_PORT", "80"), ("AGENT_RULES_MAX_DEPTH", "0")]
)
def test_gui_launch_reads_invalid_settings_from_environment(tmp_path, variable, value):
    import os

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gui.py"), "--workspace", str(tmp_path)],
        capture_output=True, text=True, timeout=10, env={**os.environ, variable: value},
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_gui_launch_reports_missing_bridge_token(tmp_path):
    import os

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gui.py"), "--workspace", str(tmp_path)],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "AGENT_RULES_BRIDGE_FILE": str(tmp_path / "missing-token")},
    )
    assert result.returncode == 1
    assert "Host bridge token file not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_sync_and_check_keep_the_recorded_source(tmp_path):
    shared = tmp_path / "source"
    shared.mkdir()
    git(shared, "init")
    git(shared, "fetch", "--update-shallow", str(ROOT), "HEAD")
    git(shared, "update-ref", "refs/heads/stable", "FETCH_HEAD")
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init")
    adopt = [sys.executable, str(ROOT / "scripts/adopt.py"), str(repo)]

    def run(*options, codes=(0,)):
        result = subprocess.run(adopt + list(options), capture_output=True, text=True, timeout=20)
        assert result.returncode in codes, result.stdout + result.stderr
        return result.stdout

    def recorded():
        metadata = parse_metadata((repo / "AGENTS.md").read_text())
        return metadata["source"], metadata["source_ref"]

    run("--profile", "codex", "--shared-url", str(shared), "--source-ref", "stable")
    assert recorded() == (str(shared), "stable")
    # Without the options, --sync must not rewrite the source to the defaults
    # and --check must compare against the recorded branch.
    run("--sync")
    assert recorded() == (str(shared), "stable")
    # Exit code 2 only reports warnings such as the boundary placeholder.
    checked = run("--check", codes=(0, 2))
    assert "0 FAIL" in checked.splitlines()[0]
    assert f"- source: {shared} (stable)" in checked
    assert "remote stable HEAD:" in checked
    # Explicit options still win.
    git(shared, "update-ref", "refs/heads/main", "FETCH_HEAD")
    run("--sync", "--source-ref", "main")
    assert recorded() == (str(shared), "main")
