from __future__ import annotations

import importlib.util
import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "adopt-agent-rules.py"

spec = importlib.util.spec_from_file_location("adopt_agent_rules", SCRIPT)
adopt = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["adopt_agent_rules"] = adopt
spec.loader.exec_module(adopt)


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


class AdoptAgentRulesUnitTests(unittest.TestCase):
    def test_parse_profile(self) -> None:
        self.assertEqual(adopt.parse_profile("codex"), "codex")
        self.assertEqual(adopt.parse_profile("CLAUDE"), "claude")
        with self.assertRaises(SystemExit):
            adopt.parse_profile("unknown")

    def test_parse_entrypoints_backward_compatibility(self) -> None:
        self.assertEqual(adopt.parse_entrypoints(""), set())
        self.assertEqual(adopt.parse_entrypoints("claude"), {"claude"})
        self.assertEqual(adopt.parse_entrypoints("all"), {"claude", "gemini"})
        self.assertEqual(adopt.profile_from_entrypoints({"claude", "gemini"}), "multi")

    def test_required_files_for_profile(self) -> None:
        self.assertEqual(adopt.required_files_for_profile("codex"), ["AGENTS.md"])
        self.assertEqual(
            adopt.required_files_for_profile("multi"),
            ["AGENTS.md", "CLAUDE.md", "GEMINI.md"],
        )

    def test_render_and_parse_metadata(self) -> None:
        block = adopt.render_metadata(
            shared_url="https://example.test/rules",
            profile="claude",
            source_commit="abc123",
            generated_at="2026-06-13T21:00:00+09:00",
        )
        parsed = adopt.parse_metadata(block)
        self.assertEqual(parsed["source"], "https://example.test/rules")
        self.assertEqual(parsed["profile"], "claude")
        self.assertEqual(parsed["source_commit"], "abc123")
        self.assertEqual(parsed["managed_block"], "true")

    def test_resolve_latest_status(self) -> None:
        self.assertEqual(adopt.resolve_latest_status("abc", "abc"), "current")
        self.assertEqual(adopt.resolve_latest_status("abc", "def"), "behind")
        self.assertEqual(adopt.resolve_latest_status("abc", None), "unknown")

    def test_format_validation_commands(self) -> None:
        rendered = adopt.format_validation_commands(["git diff --check", "git diff --check"])
        self.assertIn("```bash", rendered)
        self.assertEqual(rendered.count("git diff --check"), 1)

    def test_detect_repository_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                '{"scripts":{"test":"node test.js","lint":"eslint ."}}',
                encoding="utf-8",
            )
            (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            detected = adopt.detect_repository_type(repo)
            self.assertIn("node", detected.repo_types)
            self.assertIn("python", detected.repo_types)
            self.assertIn("npm run lint", detected.validation_commands)
            self.assertIn("python -m pytest", detected.validation_commands)

    def test_check_ignore_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run(["git", "init"], repo)
            (repo / ".gitignore").write_text("AGENTS.md\n", encoding="utf-8")
            status = adopt.check_ignore_status(repo, "AGENTS.md")
            self.assertTrue(status.ignored)
            self.assertFalse(status.tracked)

    def test_plan_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run(["git", "init"], repo)
            args = argparse.Namespace(
                target_repo=str(repo),
                profile="claude",
                entrypoints="",
                shared_url=str(ROOT),
                boundary=[],
                validation=[],
                plan=True,
                dry_run=False,
                force=False,
                backup=False,
                check=False,
                strict_check=False,
                check_latest=False,
                allow_stale_source=False,
                allow_ignored=False,
                update=False,
                merge=False,
                local_copy=False,
                submodule=False,
                apply_submodule=False,
                detect=False,
            )
            plan = adopt.build_plan(repo, args, "claude")
            self.assertEqual([item.path for item in plan.files], ["AGENTS.md", "CLAUDE.md"])


class AdoptAgentRulesIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        run(["git", "init"], self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run(
            [sys.executable, str(SCRIPT), str(self.repo), "--shared-url", str(ROOT), *args],
            ROOT,
        )

    def test_plan_and_profile_dry_runs(self) -> None:
        self.assertEqual(self.cli("--plan").returncode, 0)
        for profile in ("codex", "claude", "gemini", "multi"):
            result = self.cli("--profile", profile, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Would create", result.stdout)

    def test_profile_required_for_apply(self) -> None:
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("No agent profile selected", result.stdout)

    def test_apply_check_latest_and_check(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "AGENTS.md").exists())
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        metadata = adopt.parse_metadata((self.repo / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(metadata["profile"], "claude")
        self.assertEqual(self.cli("--check-latest").returncode, 0)
        check = self.cli("--check")
        self.assertEqual(check.returncode, 0, check.stderr + check.stdout)

    def test_existing_agents_default_fails(self) -> None:
        (self.repo / "AGENTS.md").write_text("# custom\n", encoding="utf-8")
        result = self.cli("--profile", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite existing file", result.stderr + result.stdout)

    def test_merge_and_update_dry_run(self) -> None:
        (self.repo / "AGENTS.md").write_text("# AGENTS.md\n\nCustom notes.\n", encoding="utf-8")
        merge = self.cli("--profile", "codex", "--merge", "--dry-run")
        self.assertEqual(merge.returncode, 0, merge.stderr + merge.stdout)
        self.assertIn("Custom notes.", merge.stdout)
        self.assertEqual(self.cli("--profile", "codex", "--merge").returncode, 0)
        update = self.cli("--profile", "codex", "--update", "--dry-run")
        self.assertEqual(update.returncode, 0, update.stderr + update.stdout)

    def test_force_backup(self) -> None:
        (self.repo / "AGENTS.md").write_text("# old\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--force", "--backup")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(list(self.repo.glob("AGENTS.md.*.bak")))

    def test_ignored_generated_files_fail_and_allow(self) -> None:
        (self.repo / ".gitignore").write_text("AGENTS.md\nCLAUDE.md\n.agents/\n", encoding="utf-8")
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ignored by target repository ignore rules", result.stdout)
        allowed = self.cli("--profile", "claude", "--allow-ignored", "--dry-run")
        self.assertEqual(allowed.returncode, 0, allowed.stderr + allowed.stdout)

    def test_tracked_ignored_agents_allows_update(self) -> None:
        (self.repo / "AGENTS.md").write_text("# tracked\n", encoding="utf-8")
        run(["git", "add", "-f", "AGENTS.md"], self.repo)
        run(
            [
                "git",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "user.name=Test User",
                "commit",
                "-m",
                "add agents",
            ],
            self.repo,
        )
        (self.repo / ".gitignore").write_text("AGENTS.md\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--force")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_local_copy_ignored_fails(self) -> None:
        (self.repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 1)
        self.assertIn(".agents/agent-rules/SOURCE_COMMIT", result.stdout)

    def test_local_copy_creates_source_commit(self) -> None:
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / ".agents" / "agent-rules" / "SOURCE_COMMIT").exists())
        self.assertTrue((self.repo / ".agents" / "agent-rules" / "rules").exists())

    def test_detect_outputs_validation(self) -> None:
        (self.repo / "package.json").write_text('{"scripts":{"lint":"eslint ."}}', encoding="utf-8")
        result = self.cli("--profile", "codex", "--detect", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("npm run lint", result.stdout)


if __name__ == "__main__":
    unittest.main()
