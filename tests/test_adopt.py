from __future__ import annotations

import contextlib
import importlib.util
import argparse
import io
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

# `adopt` re-exports the whole public API, which is what most assertions read.
# Overriding a name at runtime is different: `from .constants import NAME`
# binds it in the importing module's namespace, so a patch has to target the
# module that *uses* the name -- patching the re-export would change nothing
# the code under test can see. These handles exist for exactly that.
sys.path.insert(0, str(ROOT / "scripts"))
from agent_rules import batch as batch_mod  # noqa: E402
from agent_rules import checking as checking_mod  # noqa: E402
from agent_rules import planning as planning_mod  # noqa: E402
from agent_rules import render as render_mod  # noqa: E402


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
    def test_shared_skill_registries_match_skill_directories(self) -> None:
        skill_names = {
            path.name for path in (ROOT / "skills").iterdir() if path.is_dir()
        }
        self.assertEqual(set(adopt.SHARED_SKILLS), skill_names)
        self.assertEqual(set(adopt.SKILL_TRIGGER_RULES), skill_names)

    def test_skill_trigger_priority_note_only_appears_with_both_skills(self) -> None:
        with mock.patch.object(render_mod, "SHARED_SKILLS", ("investigate-bug",)):
            self.assertNotIn(
                adopt.SKILL_TRIGGER_PRIORITY_NOTE,
                adopt.shared_skills_section("CLAUDE.md"),
            )
        with mock.patch.object(
            render_mod, "SHARED_SKILLS", ("investigate-bug", "review-change")
        ):
            self.assertIn(
                adopt.SKILL_TRIGGER_PRIORITY_NOTE,
                adopt.shared_skills_section("CLAUDE.md"),
            )

    def test_review_trigger_blocks_unverified_target_substitution(self) -> None:
        rule = adopt.SKILL_TRIGGER_RULES["review-change"]
        self.assertIn("cannot be inspected", rule)
        self.assertIn("never substitute", rule)

    def test_investigate_trigger_excludes_unrelated_work_from_fix_plan(self) -> None:
        rule = adopt.SKILL_TRIGGER_RULES["investigate-bug"]
        self.assertIn("Do not include unrelated work in the bug-fix plan", rule)
        self.assertIn("only under Not Included or Follow-up", rule)

    def test_validate_trigger_preserves_worktree_and_reports_evidence(self) -> None:
        rule = adopt.SKILL_TRIGGER_RULES["validate-change"]
        self.assertIn("record the initial worktree state", rule)
        self.assertIn("report exact commands and outcomes", rule)
        self.assertIn("without deleting or reverting", rule)

    def test_prepare_commit_trigger_scopes_change_and_conventional_message(self) -> None:
        rule = adopt.SKILL_TRIGGER_RULES["prepare-commit"]
        self.assertIn("commit only the requested logical change", rule)
        self.assertIn("git diff --check", rule)
        self.assertIn("Conventional Commits message", rule)
        self.assertIn("Do not amend or rewrite", rule)

    def test_shared_skill_summary_returns_first_description_sentence(self) -> None:
        for skill_name in adopt.SHARED_SKILLS:
            summary = adopt.shared_skill_summary(skill_name)
            self.assertTrue(summary, f"empty summary for {skill_name}")
            self.assertTrue(summary.endswith("."))
            # First sentence only: no embedded ". " sentence boundary remains.
            self.assertNotIn(". ", summary)

    def test_list_shared_skills_lists_every_shared_skill(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = adopt.list_shared_skills()
        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        for skill_name in adopt.SHARED_SKILLS:
            self.assertIn(skill_name, output)
        self.assertIn("--skills", output)

    def test_list_skills_cli_needs_no_target_or_profile(self) -> None:
        # Run from a non-repo temp dir to prove --list-skills is informational
        # and does not require a target repository, git, or a profile.
        with tempfile.TemporaryDirectory() as tmp:
            result = run([sys.executable, str(SCRIPT), "--list-skills"], cwd=Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for skill_name in adopt.SHARED_SKILLS:
            self.assertIn(skill_name, result.stdout)

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

    def test_check_skills_generalizes_to_a_second_shared_skill(self) -> None:
        # Regression guard: the Codex/Claude contract-parity check and the
        # Codex-only-file leak check used to hardcode "investigate-bug" or
        # require a separate per-skill metadata registry.
        # Simulate a second shared skill (no real skills/second-skill/ source
        # directory needed, since check_adoption only reads already-installed
        # files in the target repo) and confirm both checks cover it.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run(["git", "init"], repo)
            second_codex = repo / ".codex" / "skills" / "second-skill"
            second_claude = repo / ".claude" / "skills" / "second-skill"
            (second_codex).mkdir(parents=True)
            (second_claude / "agents").mkdir(parents=True)
            (second_codex / "SKILL.md").write_text("codex version\n", encoding="utf-8")
            (second_claude / "SKILL.md").write_text("claude version\n", encoding="utf-8")
            (second_claude / "agents" / "openai.yaml").write_text(
                "leaked\n", encoding="utf-8"
            )

            skills = ("investigate-bug", "second-skill")
            with (
                mock.patch.object(checking_mod, "SHARED_SKILLS", skills),
                mock.patch.object(planning_mod, "SHARED_SKILLS", skills),
            ):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    adopt.check_adoption(
                        repo,
                        str(ROOT),
                        check_skills=True,
                        visibility="local",
                        profile_override="all",
                    )
                output = buf.getvalue()

        self.assertIn("Codex and Claude second-skill contracts differ", output)
        self.assertIn(
            "Claude second-skill skill contains Codex-only agents/openai.yaml "
            "metadata; remove it",
            output,
        )

    def test_shared_skill_files_automatically_exclude_openai_metadata_from_claude(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            skill_root = source_root / "skills" / "second-skill"
            (skill_root / "agents").mkdir(parents=True)
            (skill_root / "SKILL.md").write_text("shared\n", encoding="utf-8")
            (skill_root / "agents" / "openai.yaml").write_text(
                "codex only\n", encoding="utf-8"
            )

            with (
                mock.patch.object(planning_mod, "SHARED_SKILLS", ("second-skill",)),
                mock.patch.object(
                    planning_mod, "source_repo_root", return_value=source_root
                ),
            ):
                destinations = {
                    destination
                    for _, destination in adopt.shared_skill_file_specs("all")
                }

        self.assertIn(".codex/skills/second-skill/SKILL.md", destinations)
        self.assertIn(
            ".codex/skills/second-skill/agents/openai.yaml", destinations
        )
        self.assertIn(".claude/skills/second-skill/SKILL.md", destinations)
        self.assertNotIn(
            ".claude/skills/second-skill/agents/openai.yaml", destinations
        )

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

    def assert_cli_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        """Assert success, and show the run's output when it was not.

        A bare `assertEqual(result.returncode, 0)` reports "1 != 0" and
        nothing else, which is useless when the failure only reproduces on a
        CI runner.
        """
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plan_and_profile_dry_runs(self) -> None:
        for profile in ("codex", "claude", "gemini", "all"):
            result = self.cli("--profile", profile, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Would create", result.stdout)

    def test_dry_run_reports_actions_not_file_contents(self) -> None:
        # --profile all --skills used to print every planned file in full:
        # ~1,900 lines, which is not a preview anyone reads.
        terse = self.cli("--profile", "all", "--skills", "--dry-run")
        self.assertEqual(terse.returncode, 0, terse.stderr + terse.stdout)
        self.assertIn("Would create", terse.stdout)
        # Content of a generated entrypoint must not be there.
        self.assertNotIn("## Agent Usage Model", terse.stdout)
        self.assertIn("--verbose", terse.stdout)

        verbose = self.cli("--profile", "all", "--skills", "--dry-run", "--verbose")
        self.assertEqual(verbose.returncode, 0, verbose.stderr + verbose.stdout)
        self.assertIn("## Agent Usage Model", verbose.stdout)
        self.assertGreater(
            len(verbose.stdout.splitlines()), len(terse.stdout.splitlines()) * 5
        )
        # Neither form writes anything.
        for name in adopt.ENTRYPOINT_FILES:
            with self.subTest(name=name):
                self.assertFalse((self.repo / name).exists())

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

    def test_all_profile_installs_shared_skills_for_codex_and_claude(self) -> None:
        result = self.cli("--profile", "all", "--skills", "--visibility", "tracked")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for skill_name in adopt.SHARED_SKILLS:
            with self.subTest(skill=skill_name):
                codex_skill = self.repo / ".codex" / "skills" / skill_name / "SKILL.md"
                claude_skill = self.repo / ".claude" / "skills" / skill_name / "SKILL.md"
                self.assertTrue(codex_skill.exists())
                self.assertTrue(claude_skill.exists())
                self.assertEqual(
                    codex_skill.read_text(encoding="utf-8"),
                    claude_skill.read_text(encoding="utf-8"),
                )
                # agents/openai.yaml is optional per skill (docs/skill-authoring.md);
                # only assert it was installed for Codex when the skill actually
                # ships one, but Claude must never have it either way.
                source_openai_yaml = ROOT / "skills" / skill_name / "agents" / "openai.yaml"
                if source_openai_yaml.exists():
                    self.assertTrue(
                        (codex_skill.parent / "agents" / "openai.yaml").exists()
                    )
                self.assertFalse(
                    (claude_skill.parent / "agents" / "openai.yaml").exists()
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
        self.assertIn("invoke the `review-change` skill", agents)
        self.assertIn("invoke the `validate-change` skill", agents)
        self.assertIn("invoke the `prepare-commit` skill", agents)
        self.assertIn("## Shared Skills", claude)
        self.assertIn(".claude/skills", claude)
        self.assertIn("invoke the `review-change` skill", claude)
        self.assertIn("invoke the `validate-change` skill", claude)
        self.assertIn("invoke the `prepare-commit` skill", claude)
        # Shared trigger rules can match the same request (e.g. reviewing and
        # testing a bug fix); the priority note keeps the primary workflow
        # explicit instead of allowing arbitrary substitution.
        self.assertIn(adopt.SKILL_TRIGGER_PRIORITY_NOTE, agents)
        self.assertIn(adopt.SKILL_TRIGGER_PRIORITY_NOTE, claude)
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
        # One directory pattern per installed skill, not one line per file.
        self.assertIn("/.codex/skills/investigate-bug/\n", gitignore)
        self.assertNotIn(".codex/skills/investigate-bug/SKILL.md", gitignore)
        # What actually matters is that the installed files are ignored.
        for relative_path in (
            ".codex/skills/investigate-bug/SKILL.md",
            ".codex/skills/investigate-bug/agents/openai.yaml",
            ".agent-rules/bases/.codex/skills/investigate-bug/SKILL.md",
        ):
            with self.subTest(path=relative_path):
                self.assertTrue(
                    adopt.check_ignore_status(self.repo, relative_path).ignored,
                    f"{relative_path} is not ignored",
                )
        self.assertNotIn("git add .codex/skills/", result.stdout)

    def test_gitignore_stays_small_and_stable_across_skills(self) -> None:
        result = self.cli("--profile", "all", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        entries = [
            line.strip()
            for line in (self.repo / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        # 3 entrypoints + one baseline root + one directory per installed
        # skill per agent root -- independent of how many files each skill
        # ships, which is what used to make this list grow.
        expected = (
            len(adopt.ENTRYPOINT_FILES)
            + 1
            + len(adopt.SHARED_SKILLS) * len(adopt.PROFILE_SKILL_ROOTS["all"])
        )
        self.assertEqual(len(entries), expected, entries)
        # Every generated file the old scheme listed individually.
        skill_files = [path for _source, path in adopt.shared_skill_file_specs("all")]
        generated = (
            list(adopt.ENTRYPOINT_FILES)
            + [adopt.sync_base_path(name) for name in adopt.ENTRYPOINT_FILES]
            + skill_files
            + [adopt.sync_base_path(path) for path in skill_files]
        )
        self.assertLess(len(entries), len(generated))
        for relative_path in generated:
            with self.subTest(path=relative_path):
                self.assertTrue(
                    adopt.check_ignore_status(self.repo, relative_path).ignored
                )

    def test_gitignore_reroots_bare_entrypoint_entries(self) -> None:
        # Earlier versions wrote a bare "AGENTS.md", which gitignore matches
        # at any depth -- including .agents/agent-rules/AGENTS.md, the local
        # copy that is meant to be committed.
        self.assertEqual(self.cli("--profile", "all").returncode, 0)
        gitignore = self.repo / ".gitignore"
        gitignore.write_text(
            f"{adopt.GITIGNORE_AGENT_COMMENT}\nAGENTS.md\nCLAUDE.md\nGEMINI.md\n",
            encoding="utf-8",
        )

        self.assert_cli_ok(self.cli("--sync"))
        lines = [
            line.strip()
            for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for name in adopt.ENTRYPOINT_FILES:
            with self.subTest(name=name):
                self.assertIn(f"/{name}", lines)
                self.assertNotIn(name, lines)
        # A local copy under .agents/ must not be caught by them.
        self.assertFalse(
            adopt.check_ignore_status(
                self.repo, ".agents/agent-rules/AGENTS.md"
            ).ignored
        )

    def test_gitignore_migrates_legacy_per_file_entries(self) -> None:
        result = self.cli("--profile", "codex", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        gitignore = self.repo / ".gitignore"
        # Rewrite the file the way an older version of the helper wrote it,
        # keeping an unrelated user entry above it and one of the helper's
        # own entrypoint lines inside the block.
        legacy_entries = ["/AGENTS.md"] + [
            f"/{path}" for _source, path in adopt.shared_skill_file_specs("codex")
        ]
        gitignore.write_text(
            "build/\n\n"
            + f"{adopt.GITIGNORE_AGENT_COMMENT}\n"
            + "\n".join(legacy_entries)
            + "\n",
            encoding="utf-8",
        )

        sync = self.cli("--sync")
        self.assertEqual(sync.returncode, 0, sync.stderr + sync.stdout)
        content = gitignore.read_text(encoding="utf-8")
        self.assertIn("build/", content, "unrelated user entry was dropped")
        self.assertIn("/.codex/skills/investigate-bug/\n", content)
        self.assertNotIn("SKILL.md", content)
        self.assertNotIn("openai.yaml", content)
        # Exactly one agent-rules block survives the migration.
        self.assertEqual(content.count(adopt.GITIGNORE_AGENT_COMMENT), 1)
        for _source, relative_path in adopt.shared_skill_file_specs("codex"):
            with self.subTest(path=relative_path):
                self.assertTrue(
                    adopt.check_ignore_status(self.repo, relative_path).ignored
                )

    def test_gitignore_migration_is_idempotent(self) -> None:
        self.assertEqual(self.cli("--profile", "codex", "--skills").returncode, 0)
        gitignore = self.repo / ".gitignore"
        before = gitignore.read_text(encoding="utf-8")
        self.assert_cli_ok(self.cli("--sync"))
        self.assertEqual(gitignore.read_text(encoding="utf-8"), before)

    def test_gitignore_migration_leaves_foreign_skill_entries_alone(self) -> None:
        # A skill this helper does not install is the repository's own
        # business, even under the same .codex/skills/ root.
        self.assertEqual(self.cli("--profile", "codex", "--skills").returncode, 0)
        gitignore = self.repo / ".gitignore"
        gitignore.write_text(
            gitignore.read_text(encoding="utf-8")
            + "\n/.codex/skills/team-only-skill/SKILL.md\n",
            encoding="utf-8",
        )

        self.assert_cli_ok(self.cli("--sync"))
        self.assertIn(
            "/.codex/skills/team-only-skill/SKILL.md",
            gitignore.read_text(encoding="utf-8"),
        )

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

    def test_check_skills_detects_staleness_against_local_shared_source(self) -> None:
        # Regression: check_adoption's Codex/Claude contract-parity check only
        # compared the two installed copies to each other, so a target repo
        # whose installed skill predates an upstream change had both copies
        # equally stale and reported "OK" with exit 0. Compare the recorded
        # baseline (upstream content as of the last --sync) against the
        # *current local shared source* instead.
        #
        # The source file below is deliberately edited but never committed:
        # "local shared source" means the literal file on disk, matching how
        # every other read in adopt.py (read_template(), etc.) already
        # works — this is not meant to detect only committed upstream
        # changes, so the test intentionally exercises the uncommitted case.
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
                "--profile", "codex", "--skills", "--visibility", "tracked"
            )
            self.assertEqual(apply.returncode, 0, apply.stderr + apply.stdout)

            check_before = source_cli(
                "--check", "--profile", "codex", "--skills", "--visibility", "tracked"
            )
            self.assertNotIn("behind the local shared source", check_before.stdout)

            # Simulate an upstream change to the skill that the target repo
            # never synced. The two installed copies (there's only one, for
            # profile codex) obviously still "match themselves" — the point
            # is this must be caught some other way.
            (source / "skills/investigate-bug/SKILL.md").write_text(
                (source / "skills/investigate-bug/SKILL.md").read_text(encoding="utf-8")
                + "\nUpstream compatibility note.\n",
                encoding="utf-8",
            )

            check_after = source_cli(
                "--check", "--profile", "codex", "--skills", "--visibility", "tracked"
            )
            self.assertIn(
                ".codex/skills/investigate-bug/SKILL.md is behind the local shared "
                "source; run --sync to update",
                check_after.stdout,
            )
            self.assertEqual(
                check_after.returncode, 2, check_after.stderr + check_after.stdout
            )

    def test_check_skills_fails_when_required_skill_is_missing(self) -> None:
        result = self.cli("--profile", "all", "--visibility", "local")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        check = self.cli("--check", "--skills", "--visibility", "local")
        self.assertEqual(check.returncode, 1, check.stderr + check.stdout)
        self.assertIn(
            "is required by the installed shared skills but missing", check.stdout
        )

    def test_check_skills_detects_missing_non_skill_md_file(self) -> None:
        # Regression: --check --skills only checked SKILL.md's own
        # existence, so deleting a different installed file (the Codex-only
        # agents/openai.yaml) went undetected with exit code 0.
        result = self.cli("--profile", "codex", "--skills", "--visibility", "tracked")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        leaked = self.repo / ".codex/skills/investigate-bug/agents/openai.yaml"
        self.assertTrue(leaked.exists())
        leaked.unlink()

        check = self.cli("--check", "--skills", "--profile", "codex")
        self.assertEqual(check.returncode, 1, check.stderr + check.stdout)
        self.assertIn(
            ".codex/skills/investigate-bug/agents/openai.yaml is required by "
            "the installed shared skills but missing",
            check.stdout,
        )

    def test_check_does_not_call_a_missing_skill_file_current(self) -> None:
        # Regression: the baseline-vs-source staleness check ran whenever the
        # baseline existed, so a deleted skill file drew a contradictory pair
        # of lines -- "[FAIL] ... but missing" immediately followed by
        # "[OK] ... is current with the local shared source".
        result = self.cli("--profile", "claude", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        missing = ".claude/skills/review-change/SKILL.md"
        (self.repo / missing).unlink()

        check = self.cli("--check", "--skills")
        self.assertEqual(check.returncode, 1, check.stderr + check.stdout)
        self.assertIn(
            f"{missing} is required by the installed shared skills but missing",
            check.stdout,
        )
        self.assertNotIn(
            f"{missing} is current with the local shared source", check.stdout
        )
        # Skills that are still installed keep reporting their currency.
        self.assertIn(
            ".claude/skills/investigate-bug/SKILL.md is current with the "
            "local shared source",
            check.stdout,
        )

    def test_check_treats_all_profile_as_superset_for_single_agent_override(
        self,
    ) -> None:
        # Regression: checking an --profile all adoption with an explicit
        # single-agent --profile used to FAIL on "profile mismatch" even
        # though that agent's entrypoint was completely healthy.
        result = self.cli("--profile", "all", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        check = self.cli("--check", "--profile", "codex", "--skills")
        self.assertNotIn("profile mismatch", check.stdout)
        self.assertIn("[OK] profile: codex", check.stdout)

        # A real mismatch (adopted with codex only, checked as if it were
        # "all") must still be reported.
        with tempfile.TemporaryDirectory() as tmp:
            other_repo = Path(tmp).resolve()
            run(["git", "init"], other_repo)
            codex_only = run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(other_repo),
                    "--shared-url",
                    str(ROOT),
                    "--profile",
                    "codex",
                ],
                ROOT,
            )
            self.assertEqual(codex_only.returncode, 0)
            mismatch_check = run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(other_repo),
                    "--shared-url",
                    str(ROOT),
                    "--check",
                    "--profile",
                    "all",
                ],
                ROOT,
            )
            self.assertIn(
                "profile mismatch: expected all, found codex",
                mismatch_check.stdout,
            )

    def test_skills_refused_for_gemini_only_profile(self) -> None:
        result = self.cli("--profile", "gemini", "--skills")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "--skills has no effect for --profile gemini",
            result.stderr + result.stdout,
        )
        self.assertFalse((self.repo / "GEMINI.md").exists())
        self.assertFalse((self.repo / ".gemini").exists())

    def test_check_leads_with_a_status_summary(self) -> None:
        self.assertEqual(self.cli("--profile", "all", "--skills").returncode, 0)
        check = self.cli("--check")
        first = check.stdout.splitlines()[0]
        self.assertRegex(first, r"^Summary: \d+ FAIL · \d+ WARN · \d+ NOTE · \d+ OK$")
        # The tally has to agree with the lines actually printed.
        for status in ("FAIL", "WARN", "NOTE", "OK"):
            printed = check.stdout.count(f"[{status}] ")
            reported = int(re.search(rf"(\d+) {status}", first).group(1))
            with self.subTest(status=status):
                self.assertEqual(reported, printed)

    def test_check_problems_only_drops_passing_lines(self) -> None:
        self.assertEqual(self.cli("--profile", "all", "--skills").returncode, 0)
        full = self.cli("--check")
        terse = self.cli("--check", "--problems-only")
        self.assertEqual(terse.returncode, full.returncode)
        self.assertNotIn("[OK]", terse.stdout)
        self.assertIn("[WARN]", terse.stdout)
        self.assertLess(
            len(terse.stdout.splitlines()), len(full.stdout.splitlines())
        )
        # The summary still reports the passing checks that were not printed.
        self.assertIn("OK", terse.stdout.splitlines()[0])

    def test_check_problems_only_says_so_when_clean(self) -> None:
        result = self.cli(
            "--profile", "claude",
            "--boundary", "public API compatibility",
            "--validation", "pytest -q",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        terse = self.cli("--check", "--problems-only")
        self.assertEqual(terse.returncode, 0, terse.stderr + terse.stdout)
        self.assertIn("No problems found.", terse.stdout)

    def test_check_skills_fails_for_gemini_only_profile(self) -> None:
        self.assertEqual(self.cli("--profile", "gemini").returncode, 0)
        check = self.cli("--check", "--skills", "--profile", "gemini")
        self.assertEqual(check.returncode, 1, check.stderr + check.stdout)
        self.assertIn("--skills has no effect for the gemini profile", check.stdout)

    def test_fully_configured_all_profile_adoption_checks_clean(self) -> None:
        # Regression: the "no shared-skill path for GEMINI.md" report was a
        # WARN, so --profile all --skills sat at exit 2 no matter how the
        # repository was configured. Nothing the user can do resolves it, so
        # the exit code carried no signal for the profile the README suggests.
        result = self.cli(
            "--profile", "all", "--skills",
            "--boundary", "public API compatibility",
            "--validation", "pytest -q",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        check = self.cli("--check")
        self.assertEqual(check.returncode, 0, check.stderr + check.stdout)
        # Still reported, just not as a problem.
        self.assertIn(
            "[NOTE] shared skills are not supported for GEMINI.md", check.stdout
        )
        self.assertNotIn("[WARN]", check.stdout)
        self.assertNotIn("[FAIL]", check.stdout)

    def test_skills_warns_but_proceeds_for_all_profile(self) -> None:
        result = self.cli("--profile", "all", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "shared skills are not supported for GEMINI.md", result.stdout
        )
        self.assertTrue((self.repo / "GEMINI.md").exists())
        self.assertTrue(
            (self.repo / ".codex/skills/investigate-bug/SKILL.md").exists()
        )

        check = self.cli("--check", "--skills", "--profile", "all")
        self.assertIn(
            "shared skills are not supported for GEMINI.md", check.stdout
        )

    def test_rerunning_the_adoption_command_syncs_instead_of_failing(self) -> None:
        # The most natural second command -- the same one again -- used to
        # stop at the first existing file with "Refusing to overwrite" and
        # exit 1, telling the user to add --sync. On an already-adopted
        # repository that request means "bring this up to date".
        self.assertEqual(self.cli("--profile", "all", "--skills").returncode, 0)
        before = {
            name: (self.repo / name).read_bytes() for name in adopt.ENTRYPOINT_FILES
        }

        again = self.cli("--profile", "all", "--skills")
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertIn("Already adopted; syncing", again.stdout)
        for name, original in before.items():
            with self.subTest(name=name):
                self.assertEqual((self.repo / name).read_bytes(), original)

    def test_rerun_still_refuses_a_file_it_did_not_write(self) -> None:
        # A file without the metadata block belongs to someone else; --sync
        # treats those differently, so the explicit refusal stays.
        (self.repo / "CLAUDE.md").write_text("# hand-written\n", encoding="utf-8")
        result = self.cli("--profile", "claude")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Refusing to overwrite existing file", result.stdout)
        self.assertEqual(
            (self.repo / "CLAUDE.md").read_text(encoding="utf-8"), "# hand-written\n"
        )

    def test_rerun_with_force_still_regenerates(self) -> None:
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        path = self.repo / "CLAUDE.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n## Local Notes\n\nkeep me\n",
            encoding="utf-8",
        )
        result = self.cli("--profile", "claude", "--force")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn("Already adopted; syncing", result.stdout)
        self.assertNotIn("keep me", path.read_text(encoding="utf-8"))

    def test_generated_entrypoints_mark_repository_owned_regions(self) -> None:
        self.assertEqual(self.cli("--profile", "all", "--skills").returncode, 0)
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        claude = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(
            set(adopt.extract_local_regions(agents)),
            {"boundaries", "validation_commands"},
        )
        # Only AGENTS.md has a boundaries section.
        self.assertEqual(
            set(adopt.extract_local_regions(claude)), {"validation_commands"}
        )

    def test_sync_never_rewrites_a_repository_owned_region(self) -> None:
        # The structural guarantee: whatever the repository puts inside its
        # own region survives a sync untouched, without the helper having to
        # recognise the content or locate it by surrounding prose.
        self.assertEqual(self.cli("--profile", "codex").returncode, 0)
        path = self.repo / "AGENTS.md"
        content = path.read_text(encoding="utf-8")
        start = "<!-- agent-rules-local:boundaries:start -->\n"
        end = "\n<!-- agent-rules-local:boundaries:end -->"
        head, _, rest = content.partition(start)
        _, _, tail = rest.partition(end)
        mine = "- no vendored dependencies\n- benchmark numbers stay reproducible"
        path.write_text(head + start + mine + end + tail, encoding="utf-8")

        self.assert_cli_ok(self.cli("--sync"))
        self.assertEqual(
            adopt.extract_local_regions(path.read_text(encoding="utf-8"))["boundaries"],
            mine,
        )

    def test_sync_still_updates_shared_content_outside_the_managed_block(self) -> None:
        # Why ownership is marked per region rather than "regenerate only the
        # managed block": shared content lives outside that block too (the
        # Validation guidance, the whole Final Report section) and has been
        # revised since repositories started adopting. It must still update.
        self.assertEqual(self.cli("--profile", "codex").returncode, 0)
        shared = "If validation cannot be run, explain why"
        paths = [self.repo / "AGENTS.md", self.repo / adopt.sync_base_path("AGENTS.md")]
        for path in paths:
            path.write_text(
                path.read_text(encoding="utf-8").replace(shared, "Stale shared text"),
                encoding="utf-8",
            )

        self.assert_cli_ok(self.cli("--sync"))
        refreshed = paths[0].read_text(encoding="utf-8")
        self.assertIn(shared, refreshed)
        self.assertNotIn("Stale shared text", refreshed)

    def _legacy_claude_file(self) -> Path:
        """A CLAUDE.md as generated before managed markers, plus local edits."""
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        path = self.repo / "CLAUDE.md"
        content = adopt.strip_local_markers(path.read_text(encoding="utf-8"))
        content = content.replace(adopt.MANAGED_START + "\n\n", "")
        content = content.replace(adopt.MANAGED_END + "\n\n", "")
        content = content.replace(
            "Confirmed for this repository:", "Preferred checks for this repository:"
        )
        content += "\n## Local Notes\n\nhand-written, not from any template\n"
        path.write_text(content, encoding="utf-8")
        shutil.rmtree(self.repo / ".agent-rules")
        return path

    def test_sync_refuses_a_file_without_managed_markers(self) -> None:
        # Regression: this path regenerated the file from the templates, which
        # destroyed a hand-edited validation section in a real repository
        # during a fleet sync. Nothing warned, and nothing kept a copy.
        path = self._legacy_claude_file()
        before = path.read_text(encoding="utf-8")

        result = self.cli("--sync")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no managed-block markers", result.stdout)
        self.assertIn("--force", result.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_force_backs_up_the_file_it_replaces(self) -> None:
        path = self._legacy_claude_file()
        before = path.read_text(encoding="utf-8")

        result = self.cli("--profile", "claude", "--force")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Backed up:", result.stdout)
        # The regeneration does discard local content -- that is what --force
        # means -- but it is recoverable.
        self.assertNotIn("Local Notes", path.read_text(encoding="utf-8"))
        backups = list((self.repo / adopt.BACKUP_ROOT).glob("*/CLAUDE.md"))
        self.assertEqual(len(backups), 1, backups)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), before)

    def test_backups_are_local_only(self) -> None:
        self._legacy_claude_file()
        self.assertEqual(self.cli("--profile", "claude", "--force").returncode, 0)
        backup = next((self.repo / adopt.BACKUP_ROOT).glob("*/CLAUDE.md"))
        relative = backup.relative_to(self.repo).as_posix()
        self.assertTrue(
            adopt.check_ignore_status(self.repo, relative).ignored,
            f"{relative} is not ignored",
        )

    def test_force_without_an_existing_file_writes_no_backup(self) -> None:
        self.assertEqual(self.cli("--profile", "claude", "--force").returncode, 0)
        self.assertFalse((self.repo / adopt.BACKUP_ROOT).exists())

    def test_sync_without_a_baseline_records_what_it_wrote(self) -> None:
        # Regression: with no baseline, --sync takes the legacy refresh, which
        # replaces the metadata and managed block and leaves the rest alone --
        # so the file keeps no ownership markers, since those sit outside the
        # block. Recording the render as the baseline left it claiming markers
        # the file lacked, and the next 3-way merge read their absence as a
        # local deletion and preserved it forever. AGENTS.md always takes that
        # path, so an adoption predating baselines could never gain markers.
        self.assertEqual(
            self.cli("--profile", "codex", "--validation", "pytest -q").returncode, 0
        )
        # Reproduce an adoption that predates both baselines and markers.
        shutil.rmtree(self.repo / ".agent-rules")
        path = self.repo / "AGENTS.md"
        path.write_text(
            adopt.strip_local_markers(path.read_text(encoding="utf-8")), encoding="utf-8"
        )
        self.assertEqual(adopt.extract_local_regions(path.read_text(encoding="utf-8")), {})

        # First sync has nothing to merge against, so it records the file it
        # actually wrote rather than the render.
        self.assert_cli_ok(self.cli("--sync"))
        baseline = self.repo / adopt.sync_base_path("AGENTS.md")
        self.assertEqual(
            adopt.extract_local_regions(baseline.read_text(encoding="utf-8")),
            adopt.extract_local_regions(path.read_text(encoding="utf-8")),
            "baseline must describe the file it was recorded from",
        )

        # With an honest baseline the next sync sees the markers as an
        # upstream addition and applies them, keeping the configured value.
        self.assert_cli_ok(self.cli("--sync"))
        regions = adopt.extract_local_regions(path.read_text(encoding="utf-8"))
        self.assertEqual(set(regions), {"boundaries", "validation_commands"})
        self.assertIn("pytest -q", regions["validation_commands"])

        before = path.read_bytes()
        self.assert_cli_ok(self.cli("--sync"))
        self.assertEqual(path.read_bytes(), before)

    def test_sync_migrates_an_adoption_written_before_the_markers(self) -> None:
        # Existing adoptions have no markers. The first sync must add them
        # while keeping the configured values, which it recovers from the
        # template text around them.
        self.assertEqual(
            self.cli(
                "--profile", "codex",
                "--boundary", "public API compatibility",
                "--validation", "pytest -q",
            ).returncode,
            0,
        )
        path = self.repo / "AGENTS.md"
        for target in (path, self.repo / adopt.sync_base_path("AGENTS.md")):
            target.write_text(
                adopt.strip_local_markers(target.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
        self.assertEqual(adopt.extract_local_regions(path.read_text(encoding="utf-8")), {})

        self.assert_cli_ok(self.cli("--sync"))
        content = path.read_text(encoding="utf-8")
        regions = adopt.extract_local_regions(content)
        self.assertEqual(set(regions), {"boundaries", "validation_commands"})
        self.assertIn("public API compatibility", regions["boundaries"])
        self.assertIn("pytest -q", regions["validation_commands"])
        self.assertNotIn(adopt.BOUNDARY_PLACEHOLDER, content)

    def test_sync_preserves_repository_boundaries_and_validation(self) -> None:
        # Regression: --sync re-rendered the whole file from the current
        # arguments, so with no --boundary/--validation on the sync run the
        # 3-way merge took the freshly rendered placeholder over what the
        # repository had configured -- silently replacing real boundaries and
        # validation commands with "Add project-specific rules here."
        self.assertEqual(
            self.cli(
                "--profile", "all", "--skills",
                "--boundary", "public API compatibility",
                "--validation", "pytest -q",
            ).returncode,
            0,
        )
        self.assertEqual(self.cli("--check").returncode, 0)

        self.assert_cli_ok(self.cli("--sync"))
        # Only AGENTS.md carries a boundaries section; all three carry validation.
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("public API compatibility", agents)
        self.assertNotIn(adopt.BOUNDARY_PLACEHOLDER, agents)
        for name in adopt.ENTRYPOINT_FILES:
            content = (self.repo / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("pytest -q", content)
                self.assertNotIn(adopt.VALIDATION_PLACEHOLDER, content)
        self.assertEqual(self.cli("--check").returncode, 0)

    def test_sync_accepts_replacement_boundaries(self) -> None:
        # Preserving the existing values must not make them unchangeable.
        # AGENTS.md is the entrypoint that has a boundaries section.
        self.assertEqual(
            self.cli("--profile", "codex", "--boundary", "first rule").returncode, 0
        )
        self.assertEqual(
            self.cli("--sync", "--boundary", "second rule").returncode, 0
        )
        content = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("second rule", content)
        self.assertNotIn("first rule", content)

    def test_force_regenerates_boundaries_from_the_template(self) -> None:
        # --force means "overwrite from the templates", which is a different
        # request from --sync and must not preserve local sections.
        self.assertEqual(
            self.cli("--profile", "codex", "--boundary", "keep me?").returncode, 0
        )
        self.assertEqual(self.cli("--profile", "codex", "--force").returncode, 0)
        content = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("keep me?", content)
        self.assertIn(adopt.BOUNDARY_PLACEHOLDER, content)

    def test_recover_placeholder_declines_when_anchors_are_gone(self) -> None:
        # If the surrounding template text was edited away, recovery returns
        # None so the caller keeps the freshly rendered value instead of
        # slicing out something arbitrary.
        template = "before text here that is long enough\n{{X}}\nafter text here too"
        self.assertEqual(
            adopt.recover_placeholder(
                template.replace("{{X}}", "configured value"), template, "{{X}}"
            ),
            "configured value",
        )
        self.assertIsNone(
            adopt.recover_placeholder("nothing familiar", template, "{{X}}")
        )
        self.assertIsNone(adopt.recover_placeholder("anything", template, "{{ABSENT}}"))

    def test_remove_deletes_generated_files_and_backs_them_up(self) -> None:
        (self.repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        self.assertEqual(
            self.cli(
                "--profile", "all", "--skills", "--boundary", "public API compatibility"
            ).returncode,
            0,
        )
        generated = [
            path
            for path in self.repo.rglob("*")
            if path.is_file() and ".git/" not in path.as_posix()
        ]
        self.assertGreater(len(generated), 20)

        result = self.cli("--remove")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        for name in adopt.ENTRYPOINT_FILES:
            with self.subTest(name=name):
                self.assertFalse((self.repo / name).exists())
        self.assertFalse((self.repo / ".codex").exists())
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / adopt.SYNC_BASE_ROOT).exists())

        # The repository's own ignore rule survives; the helper's block does not.
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("build/", gitignore)
        self.assertNotIn(adopt.GITIGNORE_AGENT_COMMENT, gitignore)

        # Everything removed is recoverable, including the boundary the
        # repository wrote, which a local-only adoption keeps nowhere else.
        backups = list((self.repo / adopt.BACKUP_ROOT).rglob("AGENTS.md"))
        self.assertTrue(backups)
        self.assertIn(
            "public API compatibility", backups[0].read_text(encoding="utf-8")
        )

    def test_remove_dry_run_changes_nothing(self) -> None:
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        before = (self.repo / "CLAUDE.md").read_bytes()
        gitignore = (self.repo / ".gitignore").read_bytes()

        result = self.cli("--remove", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Would remove", result.stdout)
        self.assertEqual((self.repo / "CLAUDE.md").read_bytes(), before)
        self.assertEqual((self.repo / ".gitignore").read_bytes(), gitignore)
        self.assertFalse((self.repo / adopt.BACKUP_ROOT).exists())

    def test_remove_refuses_a_file_it_did_not_generate(self) -> None:
        (self.repo / "AGENTS.md").write_text("# hand-written\n", encoding="utf-8")
        result = self.cli("--profile", "codex", "--remove")
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not generate", result.stdout)
        self.assertEqual(
            (self.repo / "AGENTS.md").read_text(encoding="utf-8"), "# hand-written\n"
        )

    def test_remove_refuses_tracked_files_without_force(self) -> None:
        self.assertEqual(
            self.cli("--profile", "codex", "--visibility", "tracked").returncode, 0
        )
        run(["git", "add", "-A"], self.repo)
        git_commit(self.repo, "adopt")

        result = self.cli("--remove")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Refusing to remove tracked files", result.stdout)
        self.assertTrue((self.repo / "AGENTS.md").exists())

        forced = self.cli("--remove", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_remove_leaves_the_local_copy_alone(self) -> None:
        self.assertEqual(
            self.cli("--profile", "codex", "--local-copy", "--visibility", "tracked").returncode,
            0,
        )
        local_copy = self.repo / ".agents" / "agent-rules"
        self.assertTrue(local_copy.exists())

        self.assertEqual(self.cli("--remove").returncode, 0)
        # A local copy is meant to be committed and shared, so dropping it is
        # a separate decision from undoing the adoption.
        self.assertTrue(local_copy.exists())
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_remove_on_an_unadopted_repository_says_so(self) -> None:
        result = self.cli("--profile", "codex", "--remove")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Nothing to remove", result.stdout)

    def test_sync_survives_a_drifted_baseline_timestamp(self) -> None:
        # Regression: generated_at is rewritten on every render, and the merge
        # saw it raw. Once the baseline's timestamp drifted from the file's,
        # all three inputs differed on that one line and git reported a
        # conflict the repository could never resolve -- --sync refused
        # forever. It only showed up on the Windows CI runner, where the suite
        # is slow enough for consecutive syncs to cross a second boundary;
        # this reproduces it directly by moving the baseline's timestamp.
        self.assert_cli_ok(self.cli("--profile", "codex"))
        baseline = self.repo / adopt.sync_base_path("AGENTS.md")
        drifted = re.sub(
            r"generated_at=.*",
            "generated_at=2020-01-01T00:00:00+00:00",
            baseline.read_text(encoding="utf-8"),
            count=1,
        )
        baseline.write_text(drifted, encoding="utf-8")

        path = self.repo / "AGENTS.md"
        path.write_text(
            re.sub(
                r"generated_at=.*",
                "generated_at=2021-01-01T00:00:00+00:00",
                path.read_text(encoding="utf-8"),
                count=1,
            ),
            encoding="utf-8",
        )

        result = self.cli("--sync")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("merge conflict", result.stdout.lower())
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("<<<<<<<", content)
        # Exactly one timestamp survives, and the rest of the file is intact.
        self.assertEqual(content.count("generated_at="), 1)
        self.assertIn("## Agent Usage Model", content)

    def test_repeated_sync_is_idempotent(self) -> None:
        # Regression: render_metadata() stamps a fresh generated_at on every
        # run, so --sync used to rewrite every entrypoint and baseline even
        # when the shared source had not moved -- producing an empty diff (and
        # under --visibility tracked, a no-content commit) on each sync.
        self.assertEqual(self.cli("--profile", "all", "--skills").returncode, 0)
        tracked = [
            self.repo / name
            for name in adopt.ENTRYPOINT_FILES
            + tuple(adopt.sync_base_path(n) for n in adopt.ENTRYPOINT_FILES)
        ]
        before = {path: path.read_bytes() for path in tracked}

        result = self.cli("--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for path, original in before.items():
            with self.subTest(path=path.name):
                self.assertEqual(path.read_bytes(), original)
        # "Updated:" must be empty; the entrypoints belong under "Skipped:".
        updated_section = result.stdout.split("Updated:", 1)[1].split("Skipped:", 1)[0]
        self.assertIn("none", updated_section)

    def test_sync_still_rewrites_when_shared_content_changes(self) -> None:
        # Guards the other side of test_repeated_sync_is_idempotent: masking
        # generated_at must not mask a real content change. Staleness is put in
        # both the file and its baseline, which is what "upstream moved and the
        # local file has no edit of its own" looks like to the 3-way merge --
        # editing only the file would instead exercise local-edit preservation
        # (test_sync_preserves_managed_content_edits_in_claude).
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        rule = "Prefer simple, explicit, maintainable changes."
        paths = [
            self.repo / "CLAUDE.md",
            self.repo / adopt.sync_base_path("CLAUDE.md"),
        ]
        for path in paths:
            path.write_text(
                path.read_text(encoding="utf-8").replace(rule, "Stale rule."),
                encoding="utf-8",
            )

        result = self.cli("--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for path in paths:
            with self.subTest(path=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn(rule, content)
                self.assertNotIn("Stale rule.", content)

    def test_sync_repairs_missing_gitignore_entry_without_content_change(self) -> None:
        # A fully idempotent sync writes no files; .gitignore repair must not
        # be keyed on whether anything was written.
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        gitignore = self.repo / ".gitignore"
        self.assertIn("CLAUDE.md", gitignore.read_text(encoding="utf-8"))
        gitignore.write_text("", encoding="utf-8")

        result = self.cli("--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("CLAUDE.md", gitignore.read_text(encoding="utf-8"))

    def test_check_infers_installed_skills_without_the_flag(self) -> None:
        # Regression: --sync inferred an existing skill installation via
        # skills_installed() but --check did not, so a health check silently
        # skipped every skill assertion and reported a deleted skill file as
        # clean (exit 2, WARN-only).
        self.assertEqual(
            self.cli("--profile", "claude", "--skills").returncode, 0
        )
        (self.repo / ".claude/skills/review-change/SKILL.md").unlink()

        check = self.cli("--check")
        self.assertEqual(check.returncode, 1, check.stderr + check.stdout)
        self.assertIn(
            ".claude/skills/review-change/SKILL.md is required by the "
            "installed shared skills but missing",
            check.stdout,
        )

    def test_check_without_installed_skills_stays_skill_free(self) -> None:
        # The inference must not turn a skill-less adoption into a wall of
        # FAILs for skills the repository never installed.
        self.assertEqual(self.cli("--profile", "claude").returncode, 0)
        check = self.cli("--check")
        self.assertNotIn("[FAIL]", check.stdout)
        self.assertNotIn("required by the installed shared skills", check.stdout)

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
        # --verbose: the merged text is what this assertion is about, and
        # a plain --dry-run now reports actions rather than file contents.
        sync_merge = self.cli("--profile", "codex", "--sync", "--dry-run", "--verbose")
        self.assertEqual(sync_merge.returncode, 0, sync_merge.stderr + sync_merge.stdout)
        self.assertIn("Custom notes.", sync_merge.stdout)
        self.assertEqual(self.cli("--profile", "codex", "--sync").returncode, 0)
        # --sync on file with metadata should update
        update = self.cli("--profile", "codex", "--sync", "--dry-run")
        self.assertEqual(update.returncode, 0, update.stderr + update.stdout)

    def test_legacy_merge_with_skills_adds_shared_skills_section(self) -> None:
        # Regression: a legacy AGENTS.md that already has Agent Usage Model
        # and Core Rules (so the whole managed block is not re-added) used to
        # silently skip the Shared Skills section entirely on `--sync
        # --skills`, even though the skill files themselves were installed.
        (self.repo / "AGENTS.md").write_text(
            "# AGENTS.md\n\n"
            "This repository follows the shared agent rules from:\n\n"
            f"- {ROOT}\n\n"
            "## Agent Usage Model\n\n"
            "Use agent roles as execution modes, not fixed tool identities.\n\n"
            "## Core Rules\n\n"
            "- Investigate existing code, documentation, and behavior before editing.\n",
            encoding="utf-8",
        )
        result = self.cli("--profile", "codex", "--skills", "--sync")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        content = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## Shared Skills", content)
        self.assertIn("investigate-bug", content)
        self.assertTrue(
            (self.repo / ".codex/skills/investigate-bug/SKILL.md").exists()
        )

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

    def test_gitignore_summary_reflects_post_write_state_for_skills(self) -> None:
        # Regression: the printed "Gitignore:" summary was computed before
        # .gitignore was written, so newly-ignored skill/baseline files were
        # reported as "is not ignored" right under a ".gitignore updated"
        # line, even though they were, in fact, just correctly ignored.
        result = self.cli("--profile", "codex", "--skills")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "OK: .codex/skills/investigate-bug/SKILL.md added to .gitignore "
            "(local-only)",
            result.stdout,
        )
        self.assertNotIn(
            "OK: .codex/skills/investigate-bug/SKILL.md is not ignored",
            result.stdout,
        )

    def test_gitignore_entries_are_root_anchored(self) -> None:
        # Regression: bare entrypoint names (e.g. "AGENTS.md") written to
        # .gitignore without a leading "/" match at any depth, so they
        # silently swept up .agents/agent-rules/AGENTS.md from --local-copy
        # even though local-copy files must stay trackable.
        result = self.cli("--profile", "codex", "--local-copy")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/AGENTS.md", gitignore)
        local_copy_entrypoint = self.repo / ".agents/agent-rules/AGENTS.md"
        self.assertTrue(local_copy_entrypoint.exists())
        add = run(["git", "add", "-A"], self.repo)
        self.assertEqual(add.returncode, 0, add.stderr + add.stdout)
        staged = run(["git", "status", "--short"], self.repo)
        self.assertIn(".agents/agent-rules/AGENTS.md", staged.stdout)

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
        original = batch_mod.tomllib
        batch_mod.tomllib = None
        try:
            with self.assertRaises(SystemExit) as ctx:
                adopt.parse_batch_file(toml_file)
            self.assertIn("Python 3.11+", str(ctx.exception))
        finally:
            batch_mod.tomllib = original


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

    def test_lightweight_adoption_final_report_matches_target_template(self) -> None:
        # Regression guard: docs/lightweight-adoption.md's "Final Report"
        # section is a hand-maintained copy of templates/target-AGENTS.md's,
        # not rendered from it, and unlike the entrypoint files themselves it
        # was not covered by test_entrypoints_require_distinct_final_report_headings.
        # A future edit to one and not the other would otherwise go unnoticed.
        doc_content = (ROOT / "docs" / "lightweight-adoption.md").read_text(encoding="utf-8")
        template_content = (ROOT / "templates" / "target-AGENTS.md").read_text(encoding="utf-8")
        doc_section = extract_section(doc_content, "Final Report")
        # lightweight-adoption.md wraps its example in an outer fence, so its
        # copy of the section is followed by that fence's closing marker.
        # Verify the exact marker instead of rstrip("`"), which would strip
        # any number of trailing backticks and silently accept a corrupted
        # fence (e.g. ``` instead of ````) without failing.
        closing_fence = "\n````"
        self.assertTrue(
            doc_section.endswith(closing_fence),
            f"expected docs/lightweight-adoption.md's Final Report section to "
            f"end with the outer fence marker {closing_fence!r}, got: "
            f"{doc_section[-20:]!r}",
        )
        self.assertEqual(
            doc_section.removesuffix(closing_fence),
            extract_section(template_content, "Final Report").rstrip(),
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

    def test_entrypoints_require_distinct_final_report_headings(self) -> None:
        paths = (
            ROOT / "AGENTS.md",
            ROOT / "CLAUDE.md",
            ROOT / "GEMINI.md",
            ROOT / "templates" / "target-AGENTS.md",
            ROOT / "templates" / "target-CLAUDE.md",
            ROOT / "templates" / "target-GEMINI.md",
        )
        required = (
            "Before sending the response, verify that these Markdown headings appear "
            "verbatim, exactly once, and in this order; do not rename, omit, or combine them."
        )
        required_headings = [
            "## Summary",
            "## Changes",
            "## Validation",
            "## Not Included",
            "## Follow-up",
        ]
        expected_items = [
            "- **Summary**: what changed and why",
            "- **Changes**: files and behaviors affected",
            "- **Validation**: what was run and results",
            "- **Not Included**: what was intentionally left out",
            "- **Follow-up**: known gaps or deferred work",
        ]

        for path in paths:
            with self.subTest(path=path):
                final_report = extract_section(
                    path.read_text(encoding="utf-8"), "Final Report"
                )
                self.assertIn(required, final_report)
                heading_directives = [
                    f"{index}. `{heading}`"
                    for index, heading in enumerate(required_headings, start=1)
                ]
                heading_positions = [
                    final_report.index(directive) for directive in heading_directives
                ]
                self.assertEqual(heading_positions, sorted(heading_positions))
                positions = [final_report.index(item) for item in expected_items]
                self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
