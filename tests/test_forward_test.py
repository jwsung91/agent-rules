from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
    def test_empty_commit_and_index_only_changes_are_not_clean(self) -> None:
        for action in ("commit", "index"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                case = forward_test.CASES["percentage-discount-commit"]

                def agent(case, fixture, run_dir, command, timeout, action=action):
                    if action == "commit":
                        command = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "test: empty evidence"]
                    else:
                        command = ["git", "add", "discount.py"]
                    completed = run(command, fixture)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    return forward_test.RunResult(0, run_dir / "transcript.jsonl", "", None, True, [], 0)

                with mock.patch.object(forward_test, "adopt_skills"), mock.patch.object(
                    forward_test, "run_codex", side_effect=agent
                ):
                    result = forward_test.do_run(case, "codex", "codex", "", root, [], [], 10)
                self.assertFalse(result.clean)
                self.assertEqual(result.changed_paths, [])
                forward_test.write_summary(root, "codex", case, result)
                summary = json.loads((root / "summary.json").read_text())
                self.assertTrue(summary["head_changed"] if action == "commit" else summary["index_changed"])
                self.assertEqual(summary["behavioral_verdict"], "not_evaluated")

    def test_validate_fixture_contains_a_real_regression_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            forward_test.build_fixture(forward_test.CASES["percentage-discount-validate"], fixture)
            before = run(["git", "show", "HEAD:discount.py"], fixture).stdout
            after = (fixture / "discount.py").read_text()
            original, changed = {}, {}
            exec(before, original)
            exec(after, changed)
            self.assertEqual(original["apply_discount"](100, 20), 80)
            self.assertEqual(changed["apply_discount"](100, 20), -1900)

    def test_model_option_is_passed_to_both_runners(self) -> None:
        for agent in ("claude", "codex"):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(forward_test, "run_command", return_value=(0, "", "")) as command:
                    getattr(forward_test, f"run_{agent}")(
                        forward_test.CASES["percentage-discount-bug"], Path(tmp), Path(tmp), [agent], 5, model="test-model"
                    )
                argv = command.call_args.args[0]
                self.assertEqual(argv[argv.index("--model") + 1], "test-model")

    def test_existing_changes_and_ignored_files_are_detected(self) -> None:
        for mutation in ("edit", "restore", "delete", "ignored", "untracked"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                case = forward_test.CASES["percentage-discount-commit"]

                def adopt(fixture, profile, shared_url):
                    (fixture / ".gitignore").write_text("ignored.txt\n")
                    (fixture / "ignored.txt").write_text("before")
                    (fixture / "untracked.txt").write_text("before")

                def agent(case, fixture, run_dir, command, timeout, mutation=mutation):
                    target = fixture / "discount.py"
                    if mutation == "edit":
                        target.write_text(target.read_text() + "\n# extra change\n")
                    elif mutation == "restore":
                        target.write_text(case.files["discount.py"])
                    elif mutation == "delete":
                        target.unlink()
                    else:
                        (fixture / f"{mutation}.txt").write_text("after")
                    return forward_test.RunResult(
                        0, run_dir / "transcript.jsonl", "", None, True, [], 0
                    )

                with mock.patch.object(forward_test, "adopt_skills", side_effect=adopt), mock.patch.object(
                    forward_test, "run_codex", side_effect=agent
                ):
                    result = forward_test.do_run(
                        case, "codex", "codex", "", root, [], [], 10
                    )
                self.assertFalse(result.clean)
                expected = f"{mutation}.txt" if mutation in {"ignored", "untracked"} else "discount.py"
                self.assertIn(expected, result.changed_paths)
                forward_test.write_summary(root, "codex", case, result)
                summary = json.loads((root / "summary.json").read_text())
                self.assertIn(expected, summary["changed_paths_since_adoption"])

    def test_timeout_output_is_normalized_to_text(self) -> None:
        for output in (b"partial \xe2\x82", "partial", None):
            with self.subTest(output=output), mock.patch.object(
                forward_test.subprocess, "run",
                side_effect=subprocess.TimeoutExpired("agent", 1, output=output, stderr=output),
            ):
                code, stdout, stderr = forward_test.run_command(["agent"], None, 1)
                self.assertEqual(code, 124)
                expected = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output or ""
                self.assertEqual(stdout, expected)
                self.assertEqual(stderr, expected)

    def test_both_agents_save_partial_output_and_summary_on_timeout(self) -> None:
        for name in ("claude", "codex"):
            with self.subTest(agent=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                case = forward_test.CASES["percentage-discount-bug"]
                runner = getattr(forward_test, f"run_{name}")
                with mock.patch.object(
                    forward_test.subprocess, "run",
                    side_effect=subprocess.TimeoutExpired(
                        "agent", 1, output=b'{"type":"partial"}\n', stderr=b"interrupted \xe2\x82"
                    ),
                ):
                    result = runner(case, root, root, ["agent"], 1)
                forward_test.write_summary(root, name, case, result)
                summary = json.loads((root / "summary.json").read_text())
                self.assertEqual(summary["returncode"], 124)
                self.assertEqual(summary["execution_status"], "timeout")
                self.assertEqual((root / "transcript.jsonl").read_text(), '{"type":"partial"}\n')
                self.assertIn("interrupted", (root / "stderr.txt").read_text())
                self.assertTrue((root / "final_report.txt").exists())

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

    def test_cases_cover_shared_skill_triggers(self) -> None:
        self.assertIn("percentage-discount-bug", forward_test.CASES)
        self.assertIn("percentage-discount-review", forward_test.CASES)
        self.assertIn("percentage-discount-validate", forward_test.CASES)
        self.assertIn("percentage-discount-commit", forward_test.CASES)

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

    def test_every_case_builds_one_commit_with_expected_worktree_state(self) -> None:
        for name, case in forward_test.CASES.items():
            with tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp) / "fixture"
                forward_test.build_fixture(case, fixture)
                log = run(["git", "log", "--oneline"], fixture)
                self.assertEqual(
                    len(log.stdout.strip().splitlines()), 1, f"{name} not committed"
                )
                status = run(["git", "status", "--short"], fixture).stdout.strip()
                if case.pending_changes:
                    # A pending-change case must start with an uncommitted change.
                    self.assertNotEqual(status, "", f"{name} has no pending change")
                else:
                    self.assertEqual(status, "", f"{name} left worktree dirty")

    def test_commit_case_leaves_uncommitted_change_and_triggers_prepare_commit(
        self,
    ) -> None:
        case = forward_test.CASES["percentage-discount-commit"]
        self.assertTrue(case.pending_changes)
        self.assertIn("commit", case.prompt.lower())
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            forward_test.build_fixture(case, fixture)
            # The pending change is present but not committed.
            self.assertIn("apply_bulk_discount", (fixture / "discount.py").read_text())
            lines = forward_test.git_status_lines(fixture)
            self.assertTrue(any("discount.py" in line for line in lines))

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


    def test_build_fixture_aborts_when_a_git_command_fails(self) -> None:
        # Regression: build_fixture() discarded every git exit code, so a
        # failed init/add/commit left a fixture with no baseline commit and
        # the run continued, making its clean-worktree verdict meaningless.
        case = forward_test.CASES["percentage-discount-bug"]
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            with mock.patch.object(
                forward_test, "run_command", return_value=(1, "", "fatal: boom")
            ):
                with self.assertRaises(SystemExit) as raised:
                    forward_test.build_fixture(case, fixture)
        message = str(raised.exception)
        self.assertIn("git init", message)
        self.assertIn("fatal: boom", message)

    def test_build_fixture_reports_which_git_step_failed(self) -> None:
        # Only the commit fails, so the message must name that step rather
        # than the first git command in the function.
        case = forward_test.CASES["percentage-discount-bug"]

        real_run_command = forward_test.run_command

        def fail_on_commit(command, cwd, timeout):
            if "commit" in command:
                return 1, "", "fatal: empty ident name"
            return real_run_command(command, cwd, timeout)

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            with mock.patch.object(
                forward_test, "run_command", side_effect=fail_on_commit
            ):
                with self.assertRaises(SystemExit) as raised:
                    forward_test.build_fixture(case, fixture)
        message = str(raised.exception)
        self.assertIn("git commit", message)
        self.assertIn("fatal: empty ident name", message)

    def test_git_status_lines_aborts_instead_of_reporting_clean(self) -> None:
        # Regression: a failed `git status` returned an empty list, which the
        # caller reads as "no new paths" and records as a clean run.
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            fixture.mkdir()
            with mock.patch.object(
                forward_test,
                "run_command",
                return_value=(128, "", "fatal: not a git repository"),
            ):
                with self.assertRaises(SystemExit) as raised:
                    forward_test.git_status_lines(fixture)
        self.assertIn("not a git repository", str(raised.exception))


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

    def invoke_main(self) -> int:
        with mock.patch.object(sys, "argv", [str(SCRIPT), "--agent", "codex", "--out-dir", str(self.out_dir)]):
            return forward_test.main()

    def test_setup_failures_and_interruptions_leave_stage_evidence(self) -> None:
        for function, phase, error, code in (
            ("collect_provenance", "provenance", FileNotFoundError("missing CLI"), 1),
            ("build_fixture", "fixture_setup", SystemExit("git failed"), 1),
            ("adopt_skills", "adoption", RuntimeError("adoption failed"), 1),
            ("run_codex", "agent_execution", KeyboardInterrupt(), 130),
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                self.out_dir = Path(tmp)
                with mock.patch.object(forward_test, "collect_provenance", return_value={"source_commit": "test"}), mock.patch.object(
                    forward_test, "adopt_skills"
                ), mock.patch.object(forward_test, function, side_effect=error):
                    self.assertEqual(self.invoke_main(), code)
                summary = self.latest_run_summary()
                self.assertEqual(summary["phase"], phase)
                self.assertEqual(summary["failure"]["type"], type(error).__name__)
                self.assertIsNone(summary["returncode"])
                self.assertIsNone(summary["clean_worktree"])
                self.assertFalse(summary["postcheck_completed"])
                self.assertEqual(summary["execution_status"], "interrupted" if code == 130 else "error")

    def test_postcheck_failure_preserves_agent_result_and_provenance(self) -> None:
        def agent(case, fixture, run_dir, command, timeout):
            transcript = run_dir / "transcript.jsonl"
            transcript.write_text("agent evidence\n")
            return forward_test.RunResult(0, transcript, "report", None, True, [], 0)

        with mock.patch.object(forward_test, "collect_provenance", return_value={"source_commit": "test"}), mock.patch.object(
            forward_test, "adopt_skills"
        ), mock.patch.object(forward_test, "run_codex", side_effect=agent), mock.patch.object(
            forward_test, "git_status_lines", side_effect=[[], SystemExit("postcheck failed")]
        ):
            self.assertEqual(self.invoke_main(), 1)
        summary = self.latest_run_summary()
        self.assertEqual(summary["phase"], "postcheck")
        self.assertEqual(summary["returncode"], 0)
        self.assertEqual(summary["provenance"]["source_commit"], "test")
        self.assertIsNone(summary["clean_worktree"])
        self.assertTrue(summary["git_before"])
        transcript = next(self.out_dir.glob("*/run-1/transcript.jsonl"))
        self.assertEqual(transcript.read_text(), "agent evidence\n")

    def test_batches_started_at_same_timestamp_do_not_overwrite(self) -> None:
        with mock.patch.object(forward_test, "datetime") as clock, mock.patch.object(
            forward_test, "collect_provenance", side_effect=RuntimeError("test stop")
        ):
            clock.now.return_value.strftime.return_value = "fixed-time"
            self.assertEqual(self.invoke_main(), 1)
            self.assertEqual(self.invoke_main(), 1)
        self.assertEqual(len(list(self.out_dir.glob("*/run-1/summary.json"))), 2)

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

    def test_commit_case_runs_with_dirty_baseline_and_stays_clean(self) -> None:
        # The prepare-commit case starts with an uncommitted change (dirty
        # baseline). A read-only agent that adds nothing must still be reported
        # as clean, because cleanliness is measured relative to that baseline.
        result = self.cli(
            "--agent", "claude",
            "--case", "percentage-discount-commit",
            "--claude-bin", f"{sys.executable} {self.fake_claude}",
            "--out-dir", str(self.out_dir),
            "--shared-url", str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        summary = self.latest_run_summary()
        self.assertTrue(summary["clean_worktree"])
        self.assertEqual(summary["new_paths_since_adoption"], [])
        # The pending change is present and left uncommitted in the fixture.
        batch_dirs = sorted(self.out_dir.iterdir())
        fixture = batch_dirs[0] / "run-1" / "fixture"
        self.assertIn("apply_bulk_discount", (fixture / "discount.py").read_text())

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

    def test_strict_process_failure_records_error_and_returns_nonzero(self) -> None:
        self.fake_codex.write_text("import sys\nif '--version' in sys.argv: print('fake 1.0')\nelse: sys.exit(7)\n")
        result = self.cli("--agent", "codex", "--codex-bin", f"{sys.executable} {self.fake_codex}", "--out-dir", str(self.out_dir), "--strict", "--model", "test-model")
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        summary = self.latest_run_summary()
        self.assertEqual(summary["execution_status"], "error")
        self.assertEqual(summary["returncode"], 7)
        self.assertEqual(summary["behavioral_verdict"], "not_evaluated")
        provenance = summary["provenance"]
        self.assertEqual(provenance["requested_model"], "test-model")
        self.assertIsNone(provenance["effective_model"])
        self.assertEqual(provenance["cli_version_output"], "fake 1.0")
        self.assertEqual(len(provenance["source_content_sha256"]), 64)
        self.assertTrue(provenance["source_commit"])

    def test_nonpositive_runs_and_timeouts_are_rejected(self) -> None:
        for option in ("--runs", "--timeout"):
            with self.subTest(option=option):
                result = self.cli("--agent", "codex", "--out-dir", str(self.out_dir), option, "0")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.out_dir.exists())

    def test_strict_validation_detects_changes_despite_dirty_baseline(self) -> None:
        self.fake_claude.write_text("import sys\nif '--version' not in sys.argv:\n    with open('discount.py', 'a') as f: f.write('\\n# unauthorized edit\\n')\n")
        result = self.cli("--agent", "claude", "--case", "percentage-discount-validate", "--claude-bin", f"{sys.executable} {self.fake_claude}", "--out-dir", str(self.out_dir), "--strict")
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertFalse(self.latest_run_summary()["clean_worktree"])

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
