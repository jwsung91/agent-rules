from __future__ import annotations

import importlib.util
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_format_validation_commands_explicit_only(self) -> None:
        rendered = adopt.format_validation_commands(["git diff --check", "git diff --check"], [])
        self.assertIn("Confirmed for this repository:", rendered)
        self.assertNotIn("Auto-detected", rendered)
        self.assertIn("```bash", rendered)
        self.assertEqual(rendered.count("git diff --check"), 1)

    def test_format_validation_commands_splits_detected_candidates(self) -> None:
        rendered = adopt.format_validation_commands(["make lint"], ["npm test", "git diff --check"])
        self.assertIn("Confirmed for this repository:", rendered)
        self.assertIn("make lint", rendered)
        self.assertIn(
            "Auto-detected candidates — verify each command works before relying on it:",
            rendered,
        )
        self.assertIn("npm test", rendered)
        # git diff --check is always a confirmed baseline, never a "detected candidate"
        self.assertEqual(rendered.count("git diff --check"), 1)
        confirmed_block, detected_block = rendered.split("Auto-detected")
        self.assertNotIn("npm test", confirmed_block)

    def test_format_validation_commands_empty_uses_placeholder(self) -> None:
        rendered = adopt.format_validation_commands([], [])
        self.assertIn("git diff --check", rendered)
        self.assertIn(adopt.VALIDATION_PLACEHOLDER, rendered)
        self.assertNotIn("Auto-detected", rendered)

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
                visibility="local",
                skills=False,
            )
            plan = adopt.build_plan(repo, args, "claude")
            self.assertEqual(
                [item.path for item in plan.files],
                ["CLAUDE.md", ".agent-rules/bases/CLAUDE.md"],
            )

    def test_three_way_merge_preserves_independent_changes(self) -> None:
        merged, conflicted = adopt.three_way_merge(
            "one local\ntwo\nthree\nfour\n",
            "one\ntwo\nthree\nfour\n",
            "one\ntwo\nthree\nfour upstream\n",
        )
        self.assertFalse(conflicted)
        self.assertIn("one local", merged)
        self.assertIn("four upstream", merged)

    def test_three_way_merge_reports_conflicting_changes(self) -> None:
        merged, conflicted = adopt.three_way_merge(
            "one\nlocal\n",
            "one\nbase\n",
            "one\nupstream\n",
        )
        self.assertTrue(conflicted)
        self.assertIn("<<<<<<< local", merged)

    def test_three_way_merge_handles_non_utf8_locale(self) -> None:
        # Regression: subprocess.run(text=True) without an explicit encoding
        # decodes git merge-file's UTF-8 stdout using the process's locale
        # encoding. On a non-UTF-8 locale (e.g. Windows cp949), non-ASCII
        # merged content raised UnicodeDecodeError before three_way_merge()
        # started passing encoding="utf-8" explicitly.
        with mock.patch("locale.getpreferredencoding", return_value="cp949"):
            merged, conflicted = adopt.three_way_merge(
                "one local — note\ntwo\nthree\nfour\n",
                "one\ntwo\nthree\nfour\n",
                "one\ntwo\nthree\nfour upstream\n",
            )
        self.assertFalse(conflicted)
        self.assertIn("—", merged)
        self.assertIn("four upstream", merged)


class AdoptAgentRulesIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        # Resolve so this matches adopt.py's own resolve_target_repo() output;
        # on some Windows hosts tempfile's raw path uses an 8.3 short name
        # (e.g. RUNNER~1) that only resolve() expands to the long form.
        self.repo = Path(self.tmp.name).resolve()
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
        self.assertIn("Would add to .gitignore: CLAUDE.md", dry_run.stdout)

        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        self.assertFalse((self.repo / "GEMINI.md").exists())
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("CLAUDE.md", gitignore)
        self.assertNotIn("AGENTS.md", gitignore)
        self.assertNotIn("GEMINI.md", gitignore)

    def test_tracked_visibility_does_not_modify_gitignore(self) -> None:
        result = self.cli("--profile", "codex", "--visibility", "tracked")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "AGENTS.md").exists())
        self.assertFalse((self.repo / ".gitignore").exists())

    def test_tracked_visibility_refuses_ignored_output(self) -> None:
        (self.repo / ".gitignore").write_text("AGENTS.md\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--visibility", "tracked")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ignored by target repository ignore rules", result.stdout)

    def test_all_profile_installs_shared_skill_for_codex_and_claude(self) -> None:
        result = self.cli("--profile", "all", "--skills", "--visibility", "tracked")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        codex_skill = self.repo / ".codex" / "skills" / "investigate-bug" / "SKILL.md"
        claude_skill = self.repo / ".claude" / "skills" / "investigate-bug" / "SKILL.md"
        self.assertTrue(codex_skill.exists())
        self.assertTrue(claude_skill.exists())
        self.assertEqual(
            codex_skill.read_text(encoding="utf-8"),
            claude_skill.read_text(encoding="utf-8"),
        )
        self.assertFalse(
            (self.repo / ".claude/skills/investigate-bug/agents/openai.yaml").exists()
        )

    def test_skills_adds_shared_skills_section_to_entrypoints(self) -> None:
        result = self.cli("--profile", "all", "--skills", "--visibility", "tracked")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        claude = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        gemini = (self.repo / "GEMINI.md").read_text(encoding="utf-8")
        self.assertIn("## Shared Skills", agents)
        self.assertIn(".codex/skills", agents)
        self.assertIn("invoke the `investigate-bug` skill", agents)
        self.assertIn("## Shared Skills", claude)
        self.assertIn(".claude/skills", claude)
        # The section lives inside the managed block so --sync keeps updating it
        self.assertLess(
            claude.index(adopt.MANAGED_START), claude.index("## Shared Skills")
        )
        self.assertLess(
            claude.index("## Shared Skills"), claude.index(adopt.MANAGED_END)
        )
        self.assertNotIn("## Shared Skills", gemini)
        for content in (agents, claude, gemini):
            self.assertNotIn("{{SHARED_SKILLS_SECTION}}", content)

    def test_no_skills_flag_omits_shared_skills_section(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        content = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertNotIn("## Shared Skills", content)
        self.assertNotIn("{{SHARED_SKILLS_SECTION}}", content)

    def test_sync_with_skills_adds_section_to_existing_adoption(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn(
            "## Shared Skills", (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        )
        sync = self.cli("--profile", "claude", "--skills", "--sync")
        self.assertEqual(sync.returncode, 0, sync.stderr + sync.stdout)
        content = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("## Shared Skills", content)
        self.assertTrue(
            (self.repo / ".claude/skills/investigate-bug/SKILL.md").exists()
        )

    def test_plain_sync_keeps_section_when_skills_are_installed(self) -> None:
        # Regression guard: --sync without --skills must detect installed
        # shared skills; otherwise the 3-way merge would render a skill-free
        # upstream and strip the Shared Skills section it added earlier.
        result = self.cli("--profile", "claude", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "## Shared Skills", (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        )
        sync = self.cli("--sync")
        self.assertEqual(sync.returncode, 0, sync.stderr + sync.stdout)
        self.assertIn(
            "## Shared Skills", (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        )

    def test_check_skills_warns_when_section_is_missing(self) -> None:
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        skill_dir = self.repo / ".claude" / "skills" / "investigate-bug"
        skill_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "skills" / "investigate-bug" / "SKILL.md", skill_dir / "SKILL.md")
        check = self.cli("--check", "--skills")
        self.assertIn(
            "CLAUDE.md lacks a Shared Skills trigger section", check.stdout
        )

    def test_local_skill_install_is_added_to_gitignore(self) -> None:
        result = self.cli("--profile", "codex", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".codex/skills/investigate-bug/SKILL.md", gitignore)
        self.assertNotIn("git add .codex/skills/", result.stdout)

    def test_skill_sync_preserves_local_edits_with_baseline(self) -> None:
        result = self.cli("--profile", "codex", "--skills", "--visibility", "tracked")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        skill = self.repo / ".codex" / "skills" / "investigate-bug" / "SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8") + "\nLocal repository note.\n",
            encoding="utf-8",
        )

        sync = self.cli(
            "--profile",
            "codex",
            "--skills",
            "--visibility",
            "tracked",
            "--sync",
        )
        self.assertEqual(sync.returncode, 0, sync.stderr + sync.stdout)
        self.assertIn("Local repository note.", skill.read_text(encoding="utf-8"))

    def test_skill_sync_merges_upstream_changes_and_stops_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as source_tmp:
            source = Path(source_tmp).resolve()
            for directory in ("scripts", "templates", "skills", "rules", "docs"):
                shutil.copytree(ROOT / directory, source / directory)
            for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
                shutil.copy2(ROOT / name, source / name)
            run(["git", "init", "-b", "main"], source)
            run(["git", "add", "."], source)
            git_commit(source, "initial source")

            script = source / "scripts" / "adopt.py"

            def source_cli(*args: str) -> subprocess.CompletedProcess[str]:
                return run(
                    [
                        sys.executable,
                        str(script),
                        str(self.repo),
                        "--shared-url",
                        str(source),
                        *args,
                    ],
                    source,
                )

            apply = source_cli(
                "--profile", "all", "--skills", "--visibility", "tracked"
            )
            self.assertEqual(apply.returncode, 0, apply.stderr + apply.stdout)

            skill = self.repo / ".codex/skills/investigate-bug/SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "# Investigate Bug", "# Investigate Repository Bug"
                ),
                encoding="utf-8",
            )
            source_skill = source / "skills/investigate-bug/SKILL.md"
            source_skill.write_text(
                source_skill.read_text(encoding="utf-8")
                + "\nUpstream compatibility note.\n",
                encoding="utf-8",
            )
            run(["git", "add", "."], source)
            git_commit(source, "update skill")

            sync = source_cli(
                "--profile",
                "all",
                "--skills",
                "--visibility",
                "tracked",
                "--sync",
            )
            self.assertEqual(sync.returncode, 0, sync.stderr + sync.stdout)
            merged = skill.read_text(encoding="utf-8")
            self.assertIn("# Investigate Repository Bug", merged)
            self.assertIn("Upstream compatibility note.", merged)

            local_before = merged.replace(
                "# Investigate Repository Bug", "# Local Conflicting Title"
            )
            skill.write_text(local_before, encoding="utf-8")
            source_skill.write_text(
                source_skill.read_text(encoding="utf-8").replace(
                    "# Investigate Bug", "# Upstream Conflicting Title"
                ),
                encoding="utf-8",
            )
            run(["git", "add", "."], source)
            git_commit(source, "conflict skill title")
            baseline = self.repo / adopt.sync_base_path(
                ".codex/skills/investigate-bug/SKILL.md"
            )
            baseline_before = baseline.read_text(encoding="utf-8")

            conflict = source_cli(
                "--profile",
                "all",
                "--skills",
                "--visibility",
                "tracked",
                "--sync",
            )
            self.assertEqual(conflict.returncode, 1, conflict.stderr + conflict.stdout)
            self.assertIn("Refusing to write unresolved merge conflicts", conflict.stdout)
            self.assertEqual(skill.read_text(encoding="utf-8"), local_before)
            self.assertEqual(baseline.read_text(encoding="utf-8"), baseline_before)

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

    def test_check_skills_reports_contract_and_baselines(self) -> None:
        codex = self.cli("--profile", "codex", "--skills", "--visibility", "local")
        claude = self.cli("--profile", "claude", "--skills", "--visibility", "local")
        self.assertEqual(codex.returncode, 0, codex.stderr + codex.stdout)
        self.assertEqual(claude.returncode, 0, claude.stderr + claude.stdout)

        codex_check = self.cli(
            "--check", "--profile", "codex", "--skills", "--visibility", "local"
        )
        claude_check = self.cli(
            "--check", "--profile", "claude", "--skills", "--visibility", "local"
        )
        self.assertNotEqual(codex_check.returncode, 1, codex_check.stderr + codex_check.stdout)
        self.assertNotEqual(claude_check.returncode, 1, claude_check.stderr + claude_check.stdout)
        self.assertIn(
            "Codex and Claude investigate-bug contracts match", claude_check.stdout
        )
        self.assertIn("sync baseline exists for AGENTS.md", codex_check.stdout)
        self.assertIn("sync baseline exists for CLAUDE.md", claude_check.stdout)

    def test_check_skills_fails_when_required_skill_is_missing(self) -> None:
        result = self.cli("--profile", "all", "--visibility", "local")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        check = self.cli("--check", "--skills", "--visibility", "local")
        self.assertEqual(check.returncode, 1, check.stderr + check.stdout)
        self.assertIn("is required by --skills but missing", check.stdout)

    def test_sync_preserves_managed_content_edits_in_claude(self) -> None:
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        path = self.repo / "CLAUDE.md"
        content = path.read_text(encoding="utf-8")
        # Simulate outdated shared content inside the managed block, plus a
        # local section outside it that must survive the sync.
        content = content.replace(
            "Investigate existing code, documentation, and behavior before editing.",
            "Outdated managed rule.",
        )
        content += "\n## Local Notes\n\nKeep this local section.\n"
        path.write_text(content, encoding="utf-8")

        result = self.cli("--profile", "claude", "--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updated = path.read_text(encoding="utf-8")
        self.assertIn("Outdated managed rule.", updated)
        self.assertIn("Keep this local section.", updated)

    def test_sync_preserves_removed_markers_when_baseline_exists(self) -> None:
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        path = self.repo / "CLAUDE.md"
        # Simulate a file generated before managed markers existed: metadata
        # present, no markers, stale shared content.
        content = path.read_text(encoding="utf-8")
        content = content.replace(adopt.MANAGED_START + "\n\n", "")
        content = content.replace(adopt.MANAGED_END + "\n\n", "")
        content = content.replace(
            "Investigate existing code, documentation, and behavior before editing.",
            "Stale legacy rule.",
        )
        path.write_text(content, encoding="utf-8")

        result = self.cli("--profile", "claude", "--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updated = path.read_text(encoding="utf-8")
        self.assertIn("Stale legacy rule.", updated)
        self.assertNotIn(adopt.MANAGED_START, updated)
        self.assertNotIn(adopt.MANAGED_END, updated)

    def test_sync_all_preserves_local_edits_in_tool_entrypoints(self) -> None:
        self.assertEqual(self.cli("--profile", "all").returncode, 0)
        claude_path = self.repo / "CLAUDE.md"
        content = claude_path.read_text(encoding="utf-8")
        content = content.replace(
            "Investigate existing code, documentation, and behavior before editing.",
            "Outdated managed rule.",
        )
        content += "\n## Local Notes\n\nKeep this local section.\n"
        claude_path.write_text(content, encoding="utf-8")

        result = self.cli("--profile", "all", "--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updated = claude_path.read_text(encoding="utf-8")
        self.assertIn("Outdated managed rule.", updated)
        self.assertIn("Keep this local section.", updated)

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
        self.assertEqual(
            sum(line.strip().lstrip("/") == "CLAUDE.md" for line in gitignore.splitlines()),
            1,
        )

    def test_gitignore_entry_with_leading_slash_not_duplicated(self) -> None:
        (self.repo / ".gitignore").write_text("/CLAUDE.md\n", encoding="utf-8")
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(
            sum(line.strip().lstrip("/") == "CLAUDE.md" for line in gitignore.splitlines()),
            1,
        )

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

    def test_update_preserves_managed_block_edits(self) -> None:
        self.assertEqual(self.cli("--profile", "codex").returncode, 0)
        path = self.repo / "AGENTS.md"
        content = path.read_text(encoding="utf-8")
        old_content = content.replace(
            "Use agent roles as execution modes, not fixed tool identities.",
            "Old managed text.",
        )
        old_content += "\n## Repository Notes\n\nKeep this text.\n"
        path.write_text(old_content, encoding="utf-8")

        result = self.cli("--profile", "codex", "--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        updated = path.read_text(encoding="utf-8")
        self.assertIn("Old managed text.", updated)
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

    def test_check_does_not_warn_when_only_detected_commands_present(self) -> None:
        # No --validation given, only an auto-detected command (npm test via package.json).
        # The rendered file has two ```bash blocks (confirmed + auto-detected); --check must
        # look at both, not just the first, when deciding whether validation is unconfigured.
        (self.repo / "package.json").write_text('{"scripts":{"test":"node test.js"}}', encoding="utf-8")
        result = self.cli("--profile", "codex")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        content = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Auto-detected candidates", content)
        self.assertIn("npm test", content)

        check = self.cli("--check")
        self.assertNotIn("Validation only contains git diff --check", check.stdout)


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

    @unittest.skipUnless(adopt.tomllib is not None, "requires Python 3.11+ (stdlib tomllib)")
    def test_parse_toml_batch(self) -> None:
        repo = self.make_repo("r1")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "{repo.as_posix()}"\nprofile = "codex"\n',
            encoding="utf-8",
        )
        entries = adopt.parse_batch_file(toml_file)
        self.assertEqual(len(entries), 1)
        self.assertEqual(Path(entries[0].path), repo)
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

    @unittest.skipUnless(adopt.tomllib is not None, "requires Python 3.11+ (stdlib tomllib)")
    def test_batch_apply(self) -> None:
        repo1 = self.make_repo("r1")
        repo2 = self.make_repo("r2")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "{repo1.as_posix()}"\n\n[[repos]]\npath = "{repo2.as_posix()}"\n',
            encoding="utf-8",
        )
        result = self.cli("--batch", str(toml_file), "--profile", "codex", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("2 succeeded", result.stdout)

    @unittest.skipUnless(adopt.tomllib is not None, "requires Python 3.11+ (stdlib tomllib)")
    def test_batch_per_repo_profile_override(self) -> None:
        repo1 = self.make_repo("r1")
        repo2 = self.make_repo("r2")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "{repo1.as_posix()}"\nprofile = "codex"\n\n'
            f'[[repos]]\npath = "{repo2.as_posix()}"\nprofile = "claude"\n',
            encoding="utf-8",
        )
        result = self.cli("--batch", str(toml_file), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("2 succeeded", result.stdout)

    @unittest.skipUnless(adopt.tomllib is not None, "requires Python 3.11+ (stdlib tomllib)")
    def test_batch_check(self) -> None:
        repo = self.make_repo("r1")
        run([sys.executable, str(SCRIPT), str(repo), "--shared-url", str(ROOT), "--profile", "codex"], ROOT)
        toml_file = self.base / "repos.toml"
        toml_file.write_text(f'[[repos]]\npath = "{repo.as_posix()}"\n', encoding="utf-8")
        result = self.cli("--batch", str(toml_file), "--check")
        # --check is always strict; fresh adoption may have placeholder warnings
        # Verify the batch ran and reported on exactly 1 repository
        match = re.search(r"(\d+) succeeded, (\d+) warned, (\d+) failed", result.stdout)
        self.assertIsNotNone(match, result.stderr + result.stdout)
        self.assertEqual(sum(int(g) for g in match.groups()), 1)

    @unittest.skipUnless(adopt.tomllib is not None, "requires Python 3.11+ (stdlib tomllib)")
    def test_batch_continues_on_failure(self) -> None:
        repo1 = self.make_repo("r1")
        toml_file = self.base / "repos.toml"
        toml_file.write_text(
            f'[[repos]]\npath = "/nonexistent/repo"\n\n[[repos]]\npath = "{repo1.as_posix()}"\nprofile = "codex"\n',
            encoding="utf-8",
        )
        result = self.cli("--batch", str(toml_file), "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 succeeded", result.stdout)
        self.assertIn("1 failed", result.stdout)

    def test_toml_batch_without_tomllib_raises_clear_error(self) -> None:
        # Exercise the Python <3.11 fallback path directly, regardless of
        # which interpreter runs the test suite.
        toml_file = self.base / "repos.toml"
        toml_file.write_text('[[repos]]\npath = "/tmp/x"\n', encoding="utf-8")
        original = adopt.tomllib
        adopt.tomllib = None
        try:
            with self.assertRaises(SystemExit) as ctx:
                adopt.parse_batch_file(toml_file)
            self.assertIn("Python 3.11+", str(ctx.exception))
        finally:
            adopt.tomllib = original


def extract_section(content: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"heading '{heading}' not found"
    return match.group(1).strip()


def normalize_tool_name(content: str) -> str:
    return re.sub(r"claude|gemini", "TOOL", content, flags=re.IGNORECASE)


class CoreRulesConsistencyTests(unittest.TestCase):
    """Guards against re-diverging the hand-maintained Core Rules copies.

    These files intentionally duplicate the same guidance (target files must be
    self-contained even for agents that don't follow links), so nothing renders
    them from a single source. This test is the drift guard instead.
    """

    def test_root_entrypoints_share_core_rules(self) -> None:
        agents = extract_section((ROOT / "AGENTS.md").read_text(encoding="utf-8"), "Core Rules")
        claude = extract_section((ROOT / "CLAUDE.md").read_text(encoding="utf-8"), "Core Rules")
        gemini = extract_section((ROOT / "GEMINI.md").read_text(encoding="utf-8"), "Core Rules")
        self.assertEqual(agents, claude)
        self.assertEqual(claude, gemini)

    def test_target_templates_share_core_rules(self) -> None:
        agents = extract_section(
            (ROOT / "templates" / "target-AGENTS.md").read_text(encoding="utf-8"), "Core Rules"
        )
        claude = extract_section(
            (ROOT / "templates" / "target-CLAUDE.md").read_text(encoding="utf-8"), "Core Rules"
        )
        gemini = extract_section(
            (ROOT / "templates" / "target-GEMINI.md").read_text(encoding="utf-8"), "Core Rules"
        )
        self.assertEqual(agents, claude)
        self.assertEqual(claude, gemini)

    def test_lightweight_adoption_example_matches_target_template(self) -> None:
        doc_content = (ROOT / "docs" / "lightweight-adoption.md").read_text(encoding="utf-8")
        template_content = (ROOT / "templates" / "target-AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(
            extract_section(doc_content, "Core Rules"),
            extract_section(template_content, "Core Rules"),
        )

    def test_root_claude_and_gemini_are_fully_parallel(self) -> None:
        # CLAUDE.md and GEMINI.md are meant to be identical except for the tool
        # name itself (unlike AGENTS.md, which intentionally carries extra
        # local-rules backlinks). Normalize the tool name and diff the rest.
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        gemini = (ROOT / "GEMINI.md").read_text(encoding="utf-8")
        self.assertEqual(normalize_tool_name(claude), normalize_tool_name(gemini))

    def test_target_claude_and_gemini_are_fully_parallel(self) -> None:
        claude = (ROOT / "templates" / "target-CLAUDE.md").read_text(encoding="utf-8")
        gemini = (ROOT / "templates" / "target-GEMINI.md").read_text(encoding="utf-8")
        self.assertEqual(normalize_tool_name(claude), normalize_tool_name(gemini))


if __name__ == "__main__":
    unittest.main()
