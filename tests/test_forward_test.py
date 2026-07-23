from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "forward_test.py"

spec = importlib.util.spec_from_file_location("forward_test", SCRIPT)
forward_test = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["forward_test"] = forward_test
spec.loader.exec_module(forward_test)


FAKE_CLAUDE = '''
import json
import os
import sys

print(json.dumps({
    "type": "assistant",
    "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "investigate-bug"}}]},
}))
print(json.dumps({"type": "result", "result": "Fixed the one-line bug. Refactor logged as Not Included."}))

if os.environ.get("FAKE_CLAUDE_DIRTY"):
    with open("dirty.txt", "w", encoding="utf-8") as handle:
        handle.write("unexpected file written by the fake model\\n")
'''

FAKE_CODEX = '''
import json
import sys

args = sys.argv[1:]
out_path = None
for index, value in enumerate(args):
    if value == "-o":
        out_path = args[index + 1]

if out_path:
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("Fixed the one-line bug via codex. Refactor logged separately.\\n")

print(json.dumps({"type": "turn.completed"}))
'''


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, env=env)


class ForwardTestUnitTests(unittest.TestCase):
    def test_build_fixture_writes_case_files_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            case = forward_test.CASES["percentage-discount-bug"]
            forward_test.build_fixture(case, fixture)
            self.assertTrue((fixture / "discount.py").exists())
            self.assertTrue((fixture / "test_discount.py").exists())
            log = run(["git", "log", "--oneline"], fixture)
            self.assertEqual(len(log.stdout.strip().splitlines()), 1)
            status = run(["git", "status", "--short"], fixture)
            self.assertEqual(status.stdout.strip(), "")

    def test_cases_cover_all_three_shared_skills(self) -> None:
        self.assertIn("percentage-discount-bug", forward_test.CASES)
        self.assertIn("percentage-discount-review", forward_test.CASES)
        self.assertIn("percentage-discount-validate", forward_test.CASES)

    def test_review_case_triggers_review_change_and_is_read_only(self) -> None:
        case = forward_test.CASES["percentage-discount-review"]
        self.assertIn("discount.py", case.files)
        self.assertIn("Review the apply_discount", case.prompt)
        self.assertIn("do not modify", case.prompt.lower())

    def test_validate_case_triggers_validate_change_without_fixing(self) -> None:
        case = forward_test.CASES["percentage-discount-validate"]
        self.assertIn("Validate the change", case.prompt)
        self.assertIn("running the relevant checks", case.prompt.lower())
        self.assertIn("do not fix", case.prompt.lower())

    def test_every_case_builds_a_clean_committed_fixture(self) -> None:
        for name, case in forward_test.CASES.items():
            with tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp) / "fixture"
                forward_test.build_fixture(case, fixture)
                log = run(["git", "log", "--oneline"], fixture)
                self.assertEqual(
                    len(log.stdout.strip().splitlines()), 1, f"{name} not committed"
                )
                status = run(["git", "status", "--short"], fixture)
                self.assertEqual(status.stdout.strip(), "", f"{name} left worktree dirty")

    def test_git_status_lines_reflects_new_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            case = forward_test.CASES["percentage-discount-bug"]
            forward_test.build_fixture(case, fixture)
            self.assertEqual(forward_test.git_status_lines(fixture), [])
            (fixture / "new_file.txt").write_text("x", encoding="utf-8")
            lines = forward_test.git_status_lines(fixture)
            self.assertEqual(len(lines), 1)
            self.assertIn("new_file.txt", lines[0])


class ForwardTestCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.out_dir = self.base / "results"
        self.fake_claude = self.base / "fake_claude.py"
        self.fake_claude.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.fake_codex = self.base / "fake_codex.py"
        self.fake_codex.write_text(FAKE_CODEX, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return run([sys.executable, str(SCRIPT), *args], ROOT, env=env)

    def latest_run_summary(self) -> dict:
        batch_dirs = sorted(self.out_dir.iterdir())
        self.assertEqual(len(batch_dirs), 1, f"expected exactly one batch dir, found {batch_dirs}")
        run_dir = batch_dirs[0] / "run-1"
        return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    def test_claude_run_records_transcript_final_report_and_skill_invocation(self) -> None:
        result = self.cli(
            "--agent", "claude",
            "--claude-bin", f"{sys.executable} {self.fake_claude}",
            "--out-dir", str(self.out_dir),
            "--shared-url", str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        summary = self.latest_run_summary()
        self.assertEqual(summary["returncode"], 0)
        self.assertTrue(summary["clean_worktree"])
        self.assertEqual(summary["new_paths_since_adoption"], [])
        self.assertEqual(
            summary["skill_invocations"], [{"skill": "investigate-bug"}]
        )

        batch_dirs = sorted(self.out_dir.iterdir())
        run_dir = batch_dirs[0] / "run-1"
        final_report = (run_dir / "final_report.txt").read_text(encoding="utf-8")
        self.assertIn("Fixed the one-line bug", final_report)
        self.assertTrue((run_dir / "transcript.jsonl").exists())
        self.assertTrue((run_dir / "fixture" / "discount.py").exists())

    def test_dirty_worktree_is_detected_and_reported(self) -> None:
        import os

        env = dict(os.environ)
        env["FAKE_CLAUDE_DIRTY"] = "1"
        result = self.cli(
            "--agent", "claude",
            "--claude-bin", f"{sys.executable} {self.fake_claude}",
            "--out-dir", str(self.out_dir),
            "--shared-url", str(ROOT),
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        summary = self.latest_run_summary()
        self.assertFalse(summary["clean_worktree"])
        self.assertEqual(len(summary["new_paths_since_adoption"]), 1)
        self.assertIn("dirty.txt", summary["new_paths_since_adoption"][0])

    def test_codex_run_records_last_message_and_leaves_skill_invocations_unparsed(self) -> None:
        result = self.cli(
            "--agent", "codex",
            "--codex-bin", f"{sys.executable} {self.fake_codex}",
            "--out-dir", str(self.out_dir),
            "--shared-url", str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        summary = self.latest_run_summary()
        self.assertIsNone(summary["skill_invocations"])
        self.assertTrue(summary["clean_worktree"])

        batch_dirs = sorted(self.out_dir.iterdir())
        run_dir = batch_dirs[0] / "run-1"
        final_report = (run_dir / "final_report.txt").read_text(encoding="utf-8")
        self.assertIn("Fixed the one-line bug via codex", final_report)
        last_message = (run_dir / "last_message.txt").read_text(encoding="utf-8")
        self.assertEqual(final_report, last_message)

    def test_runs_flag_creates_one_directory_per_run(self) -> None:
        result = self.cli(
            "--agent", "claude",
            "--claude-bin", f"{sys.executable} {self.fake_claude}",
            "--out-dir", str(self.out_dir),
            "--shared-url", str(ROOT),
            "--runs", "2",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        batch_dirs = sorted(self.out_dir.iterdir())
        self.assertEqual(len(batch_dirs), 1)
        run_dirs = sorted((batch_dirs[0]).glob("run-*"))
        self.assertEqual([p.name for p in run_dirs], ["run-1", "run-2"])
        for run_dir in run_dirs:
            self.assertTrue((run_dir / "summary.json").exists())

    def test_unknown_case_is_rejected_by_argparse(self) -> None:
        result = self.cli(
            "--agent", "claude",
            "--case", "does-not-exist",
            "--claude-bin", f"{sys.executable} {self.fake_claude}",
            "--out-dir", str(self.out_dir),
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
