from __future__ import annotations

import importlib.util
import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "adopt.py"

spec = importlib.util.spec_from_file_location("adopt_agent_rules", SCRIPT)
adopt = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["adopt_agent_rules"] = adopt
spec.loader.exec_module(adopt)


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def git_commit(repo: Path, message: str) -> str:
    result = run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test User",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            message,
        ],
        repo,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    rev = run(["git", "rev-parse", "HEAD"], repo)
    assert rev.returncode == 0, rev.stderr + rev.stdout
    return rev.stdout.strip()


class AdoptAgentRulesUnitTests(unittest.TestCase):
    def test_parse_profile(self) -> None:
        self.assertEqual(adopt.parse_profile("codex"), "codex")
        self.assertEqual(adopt.parse_profile("CLAUDE"), "claude")
        with self.assertRaises(SystemExit):
            adopt.parse_profile("unknown")

    def test_required_files_for_profile(self) -> None:
        self.assertEqual(adopt.required_files_for_profile("codex"), ["AGENTS.md"])
        self.assertEqual(adopt.required_files_for_profile("claude"), ["CLAUDE.md"])
        self.assertEqual(adopt.required_files_for_profile("gemini"), ["GEMINI.md"])
        self.assertEqual(
            adopt.required_files_for_profile("all"),
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
        self.assertEqual(adopt.resolve_latest_status("abc", "def"), "different")
        self.assertEqual(adopt.resolve_latest_status("abc", None), "unknown")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run(["git", "init"], repo)
            (repo / "file.txt").write_text("one\n", encoding="utf-8")
            run(["git", "add", "file.txt"], repo)
            first = git_commit(repo, "first")
            (repo / "file.txt").write_text("two\n", encoding="utf-8")
            run(["git", "add", "file.txt"], repo)
            second = git_commit(repo, "second")
            self.assertEqual(adopt.resolve_latest_status(first, second, repo), "behind")
            self.assertEqual(adopt.resolve_latest_status(second, first, repo), "ahead")

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
                shared_url=str(ROOT),
                boundary=[],
                validation=[],
                dry_run=False,
                force=False,
                check=False,
                sync=False,
                local_copy=False,
            )
            plan = adopt.build_plan(repo, args, "claude")
            self.assertEqual([item.path for item in plan.files], ["CLAUDE.md"])


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
        for profile in ("codex", "claude", "gemini", "all"):
            result = self.cli("--profile", profile, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Would create", result.stdout)

    def test_profile_required_for_apply(self) -> None:
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("No agent profile selected", result.stdout)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        self.assertFalse((self.repo / "GEMINI.md").exists())

    def test_apply_check_latest_and_check(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        metadata = adopt.parse_metadata((self.repo / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual(metadata["profile"], "claude")
        check = self.cli("--check")
        self.assertIn("[OK] agent file(s) found: CLAUDE.md", check.stdout)
        self.assertIn("[OK] agent-rules metadata block exists (CLAUDE.md)", check.stdout)
        self.assertIn("[OK] profile: claude", check.stdout)
        self.assertIn("[OK] CLAUDE.md exists", check.stdout)
        self.assertIn("local source HEAD:", check.stdout)
        self.assertIn("remote main HEAD:", check.stdout)
        self.assertIn("latest status:", check.stdout)

    def test_claude_profile_dry_run_and_apply(self) -> None:
        dry_run = self.cli("--profile", "claude", "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
        # claude 프로필은 CLAUDE.md만 생성하고, AGENTS.md/GEMINI.md 파일은 생성하지 않음
        self.assertIn("Would create: " + str(self.repo / "CLAUDE.md"), dry_run.stdout)
        self.assertNotIn("Would create: " + str(self.repo / "AGENTS.md"), dry_run.stdout)
        self.assertNotIn("Would create: " + str(self.repo / "GEMINI.md"), dry_run.stdout)
        # .gitignore에는 세 파일 모두 추가됨
        self.assertIn("AGENTS.md, CLAUDE.md, GEMINI.md", dry_run.stdout)

        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        self.assertFalse((self.repo / "GEMINI.md").exists())
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", gitignore)
        self.assertIn("CLAUDE.md", gitignore)
        self.assertIn("GEMINI.md", gitignore)

    def test_codex_profile_creates_only_agents(self) -> None:
        result = self.cli("--profile", "codex")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "AGENTS.md").exists())
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        self.assertFalse((self.repo / "GEMINI.md").exists())

    def test_all_profile_creates_all_entrypoints(self) -> None:
        result = self.cli("--profile", "all")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "AGENTS.md").exists())
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        self.assertTrue((self.repo / "GEMINI.md").exists())

    def test_sync_all_profile_refuses_claude_without_metadata(self) -> None:
        self.assertEqual(self.cli("--profile", "all").returncode, 0)
        claude_path = self.repo / "CLAUDE.md"
        # Simulate a hand-edited CLAUDE.md that predates the agent-rules metadata block.
        stripped = adopt.METADATA_RE.sub("", claude_path.read_text(encoding="utf-8"), count=1)
        claude_path.write_text(stripped.lstrip("\n"), encoding="utf-8")

        result = self.cli("--profile", "all", "--sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Refusing to update file without agent-rules metadata",
            result.stderr + result.stdout,
        )
        # The file must be left untouched, not silently overwritten.
        self.assertEqual(claude_path.read_text(encoding="utf-8"), stripped.lstrip("\n"))

    def test_existing_agents_default_fails(self) -> None:
        (self.repo / "AGENTS.md").write_text("# custom\n", encoding="utf-8")
        result = self.cli("--profile", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite existing file", result.stderr + result.stdout)

    def test_merge_and_update_dry_run(self) -> None:
        (self.repo / "AGENTS.md").write_text("# AGENTS.md\n\nCustom notes.\n", encoding="utf-8")
        # --sync on file without metadata should merge
        sync_merge = self.cli("--profile", "codex", "--sync", "--dry-run")
        self.assertEqual(sync_merge.returncode, 0, sync_merge.stderr + sync_merge.stdout)
        self.assertIn("Custom notes.", sync_merge.stdout)
        self.assertEqual(self.cli("--profile", "codex", "--sync").returncode, 0)
        # --sync on file with metadata should update
        update = self.cli("--profile", "codex", "--sync", "--dry-run")
        self.assertEqual(update.returncode, 0, update.stderr + update.stdout)

    def test_force_overwrites_existing(self) -> None:
        (self.repo / "AGENTS.md").write_text("# old\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--force")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("agent-rules", (self.repo / "AGENTS.md").read_text(encoding="utf-8"))

    def test_agent_files_added_to_gitignore(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("CLAUDE.md", gitignore)
        self.assertIn(".gitignore updated", result.stdout)

    def test_existing_gitignore_entry_not_duplicated(self) -> None:
        (self.repo / ".gitignore").write_text("CLAUDE.md\n", encoding="utf-8")
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("!CLAUDE.md", gitignore)
        self.assertEqual(gitignore.count("CLAUDE.md"), 1)

    def test_gitignore_entry_with_leading_slash_not_duplicated(self) -> None:
        (self.repo / ".gitignore").write_text("/CLAUDE.md\n", encoding="utf-8")
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(gitignore.count("CLAUDE.md"), 1)

    def test_next_commands_omit_commit_for_local_only_entrypoints(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('git commit -m "chore: ignore local agent entrypoint files"', result.stdout)
        self.assertNotIn('docs(agent): adopt shared agent rules"', result.stdout)

    def test_ignored_directory_pattern_fails(self) -> None:
        (self.repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ignored by target repository ignore rules", result.stdout)

    def test_tracked_ignored_claude_entrypoint_allows_update(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        run(["git", "add", "-f", "CLAUDE.md"], self.repo)
        git_commit(self.repo, "add claude adoption")
        (self.repo / ".gitignore").write_text("CLAUDE.md\n", encoding="utf-8")

        update = self.cli("--profile", "claude", "--sync", "--dry-run")
        self.assertEqual(update.returncode, 0, update.stderr + update.stdout)

    def test_tracked_ignored_agents_allows_update(self) -> None:
        (self.repo / "AGENTS.md").write_text("# tracked\n", encoding="utf-8")
        run(["git", "add", "-f", "AGENTS.md"], self.repo)
        git_commit(self.repo, "add agents")
        (self.repo / ".gitignore").write_text("AGENTS.md\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--force")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_local_copy_ignored_fails(self) -> None:
        (self.repo / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ignored by target repository ignore rules", result.stdout)

    def test_local_copy_creates_source_commit(self) -> None:
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / ".agents" / "agent-rules" / "SOURCE_COMMIT").exists())
        self.assertTrue((self.repo / ".agents" / "agent-rules" / "rules").exists())

    def test_local_copy_existing_files_require_update_or_force(self) -> None:
        local_copy = self.repo / ".agents" / "agent-rules"
        local_copy.mkdir(parents=True)
        (local_copy / "SOURCE_COMMIT").write_text("old\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Refusing to apply local copy", result.stdout)

        update = self.cli("--profile", "codex", "--local-copy", "--sync", "--dry-run")
        self.assertEqual(update.returncode, 0, update.stderr + update.stdout)
        self.assertIn("Would update", update.stdout)

    def test_update_refreshes_metadata_and_managed_block(self) -> None:
        self.assertEqual(self.cli("--profile", "codex").returncode, 0)
        path = self.repo / "AGENTS.md"
        content = path.read_text(encoding="utf-8")
        old_content = content.replace("source_commit=", "source_commit=old")
        old_content = old_content.replace(
            "Use agent roles as execution modes, not fixed tool identities.",
            "Old managed text.",
        )
        old_content += "\n## Repository Notes\n\nKeep this text.\n"
        path.write_text(old_content, encoding="utf-8")

        result = self.cli("--profile", "codex", "--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updated = path.read_text(encoding="utf-8")
        self.assertNotIn("Old managed text.", updated)
        self.assertIn("Use agent roles as execution modes, not fixed tool identities.", updated)
        self.assertIn("Keep this text.", updated)

    def test_legacy_adoption_warns_without_strict(self) -> None:
        (self.repo / "AGENTS.md").write_text(
            f"# AGENTS.md\n\n{ROOT}\n",
            encoding="utf-8",
        )
        # --check is always strict; WARN-only results in exit code 2 (FAIL would be 1)
        result = self.cli("--check")
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn("legacy adoption detected; run --sync to add metadata", result.stdout)

    def test_check_fail_returns_exit_code_one(self) -> None:
        # No agent instruction file at all triggers a FAIL, not just a WARN.
        result = self.cli("--check")
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("[FAIL] no agent instruction file found", result.stdout)

    def test_subdir_target_apply_fails(self) -> None:
        subdir = self.repo / "subdir"
        subdir.mkdir()
        result = run(
            [
                sys.executable,
                str(SCRIPT),
                str(subdir),
                "--shared-url",
                str(ROOT),
                "--profile",
                "codex",
            ],
            ROOT,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not the repository root", result.stdout)

    def test_detect_outputs_validation(self) -> None:
        (self.repo / "package.json").write_text('{"scripts":{"lint":"eslint ."}}', encoding="utf-8")
        # --detect is always enabled; no explicit flag needed
        result = self.cli("--profile", "codex", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("npm run lint", result.stdout)


class AdoptAgentRulesBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_repo(self, name: str) -> Path:
        repo = self.base / name
        repo.mkdir()
        run(["git", "init"], repo)
        return repo

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run(
            [sys.executable, str(SCRIPT), "--shared-url", str(ROOT), *args],
            ROOT,
        )

    def test_parse_toml_batch(self) -> None:
        repo = self.make_repo("r1")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "{repo}"\nprofile = "codex"\n',
            encoding="utf-8",
        )
        entries = adopt.parse_batch_file(toml_file)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, str(repo))
        self.assertEqual(entries[0].profile, "codex")

    def test_parse_text_batch(self) -> None:
        repo1 = self.make_repo("r1")
        repo2 = self.make_repo("r2")
        txt_file = self.base / "repos.txt"
        txt_file.write_text(f"# comment\n{repo1}\n{repo2}\n", encoding="utf-8")
        entries = adopt.parse_batch_file(txt_file)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].path, str(repo1))
        self.assertIsNone(entries[0].profile)

    def test_batch_apply(self) -> None:
        repo1 = self.make_repo("r1")
        repo2 = self.make_repo("r2")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "{repo1}"\n\n[[repos]]\npath = "{repo2}"\n',
            encoding="utf-8",
        )
        result = self.cli("--batch", str(toml_file), "--profile", "codex", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("2 succeeded", result.stdout)

    def test_batch_per_repo_profile_override(self) -> None:
        repo1 = self.make_repo("r1")
        repo2 = self.make_repo("r2")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "{repo1}"\nprofile = "codex"\n\n'
            f'[[repos]]\npath = "{repo2}"\nprofile = "claude"\n',
            encoding="utf-8",
        )
        result = self.cli("--batch", str(toml_file), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("2 succeeded", result.stdout)

    def test_batch_check(self) -> None:
        repo = self.make_repo("r1")
        run([sys.executable, str(SCRIPT), str(repo), "--shared-url", str(ROOT), "--profile", "codex"], ROOT)
        toml_file = self.base / "repos.toml"
        toml_file.write_text(f'[[repos]]\npath = "{repo}"\n', encoding="utf-8")
        result = self.cli("--batch", str(toml_file), "--check")
        # --check is always strict; fresh adoption may have placeholder warnings
        # Verify the batch ran and reported on exactly 1 repository
        import re
        match = re.search(r"(\d+) succeeded, (\d+) failed", result.stdout)
        self.assertIsNotNone(match, result.stderr + result.stdout)
        self.assertEqual(int(match.group(1)) + int(match.group(2)), 1)

    def test_batch_continues_on_failure(self) -> None:
        repo1 = self.make_repo("r1")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "/nonexistent/repo"\n\n[[repos]]\npath = "{repo1}"\nprofile = "codex"\n',
            encoding="utf-8",
        )
        result = self.cli("--batch", str(toml_file), "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 succeeded", result.stdout)
        self.assertIn("1 failed", result.stdout)


if __name__ == "__main__":
    unittest.main()
