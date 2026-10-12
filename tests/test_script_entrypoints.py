"""Keep checkout commands usable after internal file moves."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script",
    ["adopt.py", "generate_batch_list.py", "gui.py", "ai_bridge.py", "forward_test.py"],
)
def test_command_help_outside_checkout_without_site_packages(tmp_path, script):
    result = subprocess.run(
        [sys.executable, "-E", "-S", str(ROOT / "scripts" / script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_core_imports_without_gui_dependencies_or_script_wrappers(tmp_path):
    result = subprocess.run(
        [sys.executable, "-E", "-S", "-c", """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from agent_rules import batch_list, cli, discovery
from agent_rules.forward_test import runner

assert batch_list.find_git_repos is discovery.find_git_repos
assert runner.ROOT == Path(sys.argv[1]).parent
assert not {'adopt', 'generate_batch_list', 'fastapi', 'pydantic', 'uvicorn'} & sys.modules.keys()
""", str(ROOT / "scripts")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
