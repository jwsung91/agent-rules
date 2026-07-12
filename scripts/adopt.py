#!/usr/bin/env python3
"""Adopt agent-rules in a target repository.

The helper creates lightweight repository-local entrypoints by default. It can
also check/update existing adoption metadata and create a pinned local copy
under .agents/agent-rules/ when offline use is needed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]


DEFAULT_SHARED_URL = "https://github.com/jwsung91/agent-rules"
SOURCE_REF = "main"
VALID_PROFILES = {"codex", "claude", "gemini", "all"}
PROFILE_FILES = {
    "codex": ("AGENTS.md",),
    "claude": ("CLAUDE.md",),
    "gemini": ("GEMINI.md",),
    "all": ("AGENTS.md", "CLAUDE.md", "GEMINI.md"),
}
ENTRYPOINT_FILES = PROFILE_FILES["all"]
VALID_VISIBILITIES = {"local", "tracked"}
SHARED_SKILLS = ("investigate-bug",)
PROFILE_SKILL_ROOTS = {
    "codex": (".codex/skills",),
    "claude": (".claude/skills",),
    "gemini": (),
    "all": (".codex/skills", ".claude/skills"),
}
ENTRYPOINT_SKILL_ROOTS = {
    "AGENTS.md": ".codex/skills",
    "CLAUDE.md": ".claude/skills",
    "GEMINI.md": None,
}
# Per-skill files that carry agent-specific metadata and must not leak into
# other agents' installs, even though the rest of the skill is a shared
# contract. Keyed by skill name so adding a second shared skill doesn't
# require touching every place that checks or excludes these files.
CODEX_ONLY_SKILL_FILES: dict[str, tuple[str, ...]] = {
    "investigate-bug": ("agents/openai.yaml",),
}
# Trigger rules injected into generated entrypoints when --skills is active.
# Skill descriptions compete for salience at invocation time and can lose to
# competing requests bundled into the same message; the always-loaded
# entrypoint is the reliable trigger lever (see docs/cross-agent-validation.md).
SKILL_TRIGGER_RULES = {
    "investigate-bug": (
        "When a message reports a bug or unexpected behavior, invoke the "
        "`investigate-bug` skill before planning any fix — even when the same "
        "message also requests unrelated work such as refactoring, new tests, "
        "or cleanup. Investigate the bug under that workflow first and treat "
        "the unrelated work as a separate request."
    ),
}
TOOL_ENTRYPOINTS = {"CLAUDE.md", "GEMINI.md"}
METADATA_RE = re.compile(r"<!--\s*agent-rules:\s*(.*?)-->", re.DOTALL)
MANAGED_START = "<!-- agent-rules-managed:start -->"
MANAGED_END = "<!-- agent-rules-managed:end -->"
BOUNDARY_PLACEHOLDER = "Add project-specific rules here."
VALIDATION_PLACEHOLDER = "# Add project-specific build/test/lint commands here."
GITIGNORE_AGENT_COMMENT = "# agent-rules (local only)"
SYNC_BASE_ROOT = ".agent-rules/bases"


@dataclass(frozen=True)
class RenderContext:
    shared_rules_url: str
    boundaries: str
    validation_commands: str
    profile: str
    source_commit: str
    generated_at: str
    install_skills: bool = False


@dataclass
class SourceStatus:
    local_head: str | None
    remote_head: str | None
    local_status: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class IgnoreStatus:
    path: str
    tracked: bool
    ignored: bool
    matched_rule: str | None = None
    warning: str | None = None


@dataclass
class DetectionResult:
    repo_types: list[str]
    validation_commands: list[str]


@dataclass
class FilePlan:
    path: str
    action: str
    content: str | None = None
    source: Path | None = None


@dataclass
class BatchEntry:
    path: str
    profile: str | None = None


@dataclass
class AdoptionPlan:
    target_repo: Path
    git_root: Path | None
    profile: str | None
    metadata: dict[str, str]
    source_status: SourceStatus
    local_copy_commit: str | None
    files: list[FilePlan]
    ignore_statuses: list[IgnoreStatus]
    detected: DetectionResult
    warnings: list[str] = field(default_factory=list)

    @property
    def is_subdir_target(self) -> bool:
        return self.git_root is not None and self.git_root != self.target_repo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, update, or check agent-rules adoption files."
    )
    parser.add_argument(
        "target_repo",
        nargs="?",
        default=".",
        help="Path to the target repository root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(VALID_PROFILES),
        help="Agent profile to manage: codex, claude, gemini, or all.",
    )
    parser.add_argument(
        "--shared-url",
        default=DEFAULT_SHARED_URL,
        help=f"Shared rules repository URL. Default: {DEFAULT_SHARED_URL}",
    )
    parser.add_argument(
        "--boundary",
        action="append",
        default=[],
        help="Repository-specific boundary to add to AGENTS.md. May be repeated.",
    )
    parser.add_argument(
        "--validation",
        action="append",
        default=[],
        help="Validation command to add to AGENTS.md. May be repeated.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--check", action="store_true", help="Check adoption health.")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Update metadata and managed blocks, or merge into an existing file without metadata.",
    )
    parser.add_argument(
        "--local-copy",
        action="store_true",
        help="Copy shared rules under .agents/agent-rules/ for pinned/offline use.",
    )
    parser.add_argument(
        "--visibility",
        choices=sorted(VALID_VISIBILITIES),
        default="local",
        help="Keep generated files local (default) or make them trackable.",
    )
    parser.add_argument(
        "--skills",
        action="store_true",
        help="Install shared skills for the selected agent profile.",
    )
    parser.add_argument(
        "--batch",
        metavar="FILE",
        help="Apply to multiple repositories listed in a .toml or .txt file.",
    )
    return parser.parse_args()


def run_command(command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def resolve_target_repo(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Target path does not exist: {path}")
    if not path.is_dir():
        raise SystemExit(f"Target path is not a directory: {path}")
    return path


def find_repo_root(path: Path) -> Path | None:
    code, stdout, _ = run_command(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    return Path(stdout).resolve() if code == 0 and stdout else None


def source_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def template_dir() -> Path:
    return source_repo_root() / "templates"


def read_template(name: str) -> str:
    path = template_dir() / name
    if not path.exists():
        raise SystemExit(f"Template file not found: {path}")
    return path.read_text(encoding="utf-8")


def parse_profile(value: str | None) -> str | None:
    if value is None:
        return None
    profile = value.strip().lower()
    if profile not in VALID_PROFILES:
        raise SystemExit(
            f"Unsupported profile: {value}. Supported values: {', '.join(sorted(VALID_PROFILES))}."
        )
    return profile


def required_files_for_profile(profile: str) -> list[str]:
    if profile not in PROFILE_FILES:
        raise SystemExit(
            f"Unsupported profile: {profile}. Supported values: {', '.join(sorted(VALID_PROFILES))}."
        )
    return list(PROFILE_FILES[profile])


def format_boundaries(items: list[str]) -> str:
    if items:
        return "\n".join(f"- {item}" for item in items)
    return (
        f"{BOUNDARY_PLACEHOLDER}\n\n"
        "Examples:\n\n"
        "- public API compatibility expectations\n"
        "- benchmark or performance data boundaries\n"
        "- packaging impact expectations\n"
        "- supported language or build conventions\n"
        "- documentation update expectations"
    )


def format_validation_commands(explicit: list[str], detected: list[str]) -> str:
    confirmed = dedupe(["git diff --check", *explicit])
    candidates = dedupe([command for command in detected if command not in confirmed])

    if not candidates and not explicit:
        confirmed = confirmed + [VALIDATION_PLACEHOLDER]

    blocks = ["Confirmed for this repository:\n\n```bash\n" + "\n".join(confirmed) + "\n```"]
    if candidates:
        blocks.append(
            "Auto-detected candidates — verify each command works before relying on it:\n\n"
            "```bash\n" + "\n".join(candidates) + "\n```"
        )
    return "\n\n".join(blocks)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def render_metadata(
    *,
    shared_url: str,
    profile: str,
    source_commit: str,
    generated_at: str | None = None,
) -> str:
    timestamp = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    return "\n".join(
        [
            "<!-- agent-rules:",
            f"source={shared_url}",
            f"profile={profile}",
            f"source_ref={SOURCE_REF}",
            f"source_commit={source_commit}",
            f"generated_at={timestamp}",
            "managed_block=true",
            "-->",
        ]
    )


def parse_metadata(content: str) -> dict[str, str]:
    match = METADATA_RE.search(content)
    if not match:
        return {}

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def render_template(content: str, context: RenderContext) -> str:
    replacements = {
        "{{SHARED_RULES_URL}}": context.shared_rules_url,
        "{{REPOSITORY_SPECIFIC_BOUNDARIES}}": context.boundaries,
        "{{VALIDATION_COMMANDS}}": context.validation_commands,
        "{{AGENT_RULES_METADATA}}": render_metadata(
            shared_url=context.shared_rules_url,
            profile=context.profile,
            source_commit=context.source_commit,
            generated_at=context.generated_at,
        ),
    }
    rendered = content
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def local_source_head(root: Path | None = None) -> tuple[str | None, str | None]:
    root = root or source_repo_root()
    code, stdout, stderr = run_command(["git", "-C", str(root), "rev-parse", "HEAD"])
    if code != 0 or not stdout:
        return None, stderr or "git rev-parse failed"
    return stdout, None


def remote_main_head(shared_url: str) -> tuple[str | None, str | None]:
    code, stdout, stderr = run_command(
        ["git", "ls-remote", shared_url, f"refs/heads/{SOURCE_REF}"]
    )
    if code != 0 or not stdout:
        return None, stderr or "git ls-remote failed"
    return stdout.split()[0], None


def merge_base_is_ancestor(repo: Path, ancestor: str, descendant: str) -> str:
    code, _, stderr = run_command(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant]
    )
    if code == 0:
        return "yes"
    if code == 1:
        return "no"
    return f"unknown:{stderr or 'git merge-base failed'}"


def resolve_latest_status(
    local_head: str | None,
    remote_head: str | None,
    repo: Path | None = None,
) -> str:
    if not local_head or not remote_head:
        return "unknown"
    if local_head == remote_head:
        return "current"

    if repo is None:
        return "different"

    local_before_remote = merge_base_is_ancestor(repo, local_head, remote_head)
    if local_before_remote == "yes":
        return "behind"
    if local_before_remote.startswith("unknown:"):
        return "different"

    remote_before_local = merge_base_is_ancestor(repo, remote_head, local_head)
    if remote_before_local == "yes":
        return "ahead"
    if remote_before_local.startswith("unknown:"):
        return "different"
    return "diverged"


def latest_reference(source_status: SourceStatus) -> str | None:
    return source_status.remote_head or source_status.local_head


def target_commit_status(
    source_commit: str | None,
    source_status: SourceStatus,
    repo: Path | None = None,
) -> str:
    latest = latest_reference(source_status)
    if not source_commit or not latest:
        return "unknown"
    if source_commit == latest:
        return "current"
    if repo is None:
        return "different"

    applied_before_latest = merge_base_is_ancestor(repo, source_commit, latest)
    if applied_before_latest == "yes":
        return "behind"
    if applied_before_latest.startswith("unknown:"):
        return "different"
    return "different"


_SOURCE_STATUS_CACHE: dict[str, SourceStatus] = {}


def get_source_status(shared_url: str) -> SourceStatus:
    # Cached per URL: batch runs would otherwise repeat the same
    # `git ls-remote` network call once per repository.
    cached = _SOURCE_STATUS_CACHE.get(shared_url)
    if cached is not None:
        return cached
    warnings: list[str] = []
    local_head, local_warning = local_source_head()
    if local_warning:
        warnings.append(f"WARN: local source HEAD unavailable: {local_warning}")
    remote_head, remote_warning = remote_main_head(shared_url)
    if remote_warning:
        warnings.append(f"WARN: remote main HEAD unavailable: {remote_warning}")
    status = SourceStatus(
        local_head=local_head,
        remote_head=remote_head,
        local_status=resolve_latest_status(local_head, remote_head, source_repo_root()),
        warnings=warnings,
    )
    _SOURCE_STATUS_CACHE[shared_url] = status
    return status


def is_tracked(repo: Path, relative_path: str) -> bool:
    code, _, _ = run_command(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", relative_path]
    )
    return code == 0


def check_ignore_status(repo: Path, relative_path: str) -> IgnoreStatus:
    tracked = is_tracked(repo, relative_path)
    code, stdout, stderr = run_command(
        ["git", "-C", str(repo), "check-ignore", "-v", "--", relative_path]
    )
    if code == 0 and stdout:
        # Format: "<source>:<linenum>:<pattern>\t<pathname>"
        # A negation pattern (!foo) as the last match means the file is un-ignored.
        tab_idx = stdout.find("\t")
        rule_part = stdout[:tab_idx] if tab_idx != -1 else stdout
        pattern = rule_part.rsplit(":", 1)[-1].strip() if ":" in rule_part else ""
        if pattern.startswith("!"):
            return IgnoreStatus(path=relative_path, tracked=tracked, ignored=False)
        return IgnoreStatus(
            path=relative_path,
            tracked=tracked,
            ignored=True,
            matched_rule=stdout,
        )
    if code not in (0, 1):
        return IgnoreStatus(
            path=relative_path,
            tracked=tracked,
            ignored=False,
            warning=stderr or "git check-ignore failed",
        )
    return IgnoreStatus(path=relative_path, tracked=tracked, ignored=False)


def check_generated_files_ignored(
    target_repo: Path,
    git_root: Path | None,
    files: list[FilePlan],
) -> list[IgnoreStatus]:
    paths = [item.path for item in files]
    if git_root is None:
        return [
            IgnoreStatus(
                path=path,
                tracked=False,
                ignored=False,
                warning="target path is not inside a Git repository",
            )
            for path in paths
        ]

    statuses: list[IgnoreStatus] = []
    for path in paths:
        absolute_path = target_repo / path
        try:
            root_relative = absolute_path.relative_to(git_root).as_posix()
        except ValueError:
            statuses.append(
                IgnoreStatus(
                    path=path,
                    tracked=False,
                    ignored=False,
                    warning=f"{absolute_path} is outside git root {git_root}",
                )
            )
            continue
        statuses.append(check_ignore_status(git_root, root_relative))
    return statuses


def add_to_gitignore(git_root: Path, filenames: list[str], *, dry_run: bool) -> str | None:
    """Add agent file names to .gitignore so they stay local-only.
    Returns relative .gitignore path if modified, else None."""
    gitignore_path = git_root / ".gitignore"
    content = (
        gitignore_path.read_text(encoding="utf-8", errors="replace")
        if gitignore_path.exists()
        else ""
    )
    existing_normalized = {line.strip().lstrip("/") for line in content.splitlines()}
    to_add = [f for f in filenames if f not in existing_normalized]
    if not to_add:
        return None
    if dry_run:
        print(f"Would add to .gitignore: {', '.join(to_add)}")
        return ".gitignore"
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"\n{GITIGNORE_AGENT_COMMENT}\n" + "\n".join(to_add) + "\n"
    gitignore_path.write_text(content, encoding="utf-8")
    return ".gitignore"


def fail_on_ignored(statuses: list[IgnoreStatus]) -> int:
    failing = [status for status in statuses if status.ignored and not status.tracked]
    if not failing:
        return 0

    print("FAIL: Generated file is ignored by target repository ignore rules.\n")
    for status in failing:
        print("File:")
        print(f"- {status.path}")
        if status.matched_rule:
            print("\nMatched ignore rule:")
            print(f"- {status.matched_rule}")
        print("\nThis file would not be committed by default.\n")
    print("Recommended fixes:")
    print("1. Remove or narrow the ignore rule in .gitignore.")
    print("2. Re-run with --dry-run to verify.")
    return 1


def detect_repository_type(target_repo: Path) -> DetectionResult:
    repo_types: list[str] = []
    commands: list[str] = []

    if (target_repo / "CMakeLists.txt").exists():
        repo_types.append("cmake")
        commands.append("cmake --build build -j2")
    if (target_repo / "pyproject.toml").exists() or (target_repo / "setup.py").exists():
        repo_types.append("python")
        commands.append("python -m pytest")
    elif (target_repo / "requirements.txt").exists():
        repo_types.append("python")
        commands.append("python -m pytest")
    package_json = target_repo / "package.json"
    if package_json.exists():
        repo_types.append("node")
        commands.append("npm test")
        try:
            package_data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            package_data = {}
        scripts = package_data.get("scripts", {}) if isinstance(package_data, dict) else {}
        if isinstance(scripts, dict) and "lint" in scripts:
            commands.append("npm run lint")
    if (target_repo / "Cargo.toml").exists():
        repo_types.append("rust")
        commands.append("cargo test")
    if (target_repo / "go.mod").exists():
        repo_types.append("go")
        commands.append("go test ./...")
    if (
        (target_repo / "package.xml").exists()
        or (target_repo / "colcon.meta").exists()
    ):
        repo_types.append("ros2")
        commands.extend(["colcon build --parallel-workers 2", "colcon test"])
    if (target_repo / ".github" / "workflows").exists():
        repo_types.append("github-actions")

    return DetectionResult(repo_types=dedupe(repo_types), validation_commands=dedupe(commands))


def build_render_context(
    args: argparse.Namespace,
    profile: str,
    source_status: SourceStatus,
    detected: DetectionResult,
) -> RenderContext:
    return RenderContext(
        shared_rules_url=args.shared_url,
        boundaries=format_boundaries(list(args.boundary)),
        validation_commands=format_validation_commands(
            list(args.validation), detected.validation_commands
        ),
        profile=profile,
        source_commit=source_status.local_head or "unknown",
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        install_skills=args.skills,
    )


def shared_skills_section(relative_path: str) -> str:
    root = ENTRYPOINT_SKILL_ROOTS.get(relative_path)
    if not root:
        return ""
    names = ", ".join(f"`{name}`" for name in SHARED_SKILLS)
    lines = [
        "## Shared Skills",
        "",
        f"- This repository installs shared skills under `{root}/`: {names}.",
    ]
    for name in SHARED_SKILLS:
        rule = SKILL_TRIGGER_RULES.get(name)
        if rule:
            lines.append(f"- {rule}")
    return "\n".join(lines)


def render_file_for_profile(relative_path: str, context: RenderContext) -> str:
    if relative_path not in ENTRYPOINT_FILES:
        raise SystemExit(f"Unsupported generated file: {relative_path}")
    rendered = render_template(read_template(f"target-{relative_path}"), context)
    section = shared_skills_section(relative_path) if context.install_skills else ""
    if section:
        rendered = rendered.replace("{{SHARED_SKILLS_SECTION}}", section)
    else:
        rendered = rendered.replace("{{SHARED_SKILLS_SECTION}}\n\n", "")
        rendered = rendered.replace("{{SHARED_SKILLS_SECTION}}", "")
    return rendered


def sync_base_path(relative_path: str) -> str:
    return f"{SYNC_BASE_ROOT}/{relative_path}"


def three_way_merge(local: str, base: str, upstream: str) -> tuple[str, bool]:
    """Merge text with Git's deterministic merge-file implementation."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        local_path = root / "local"
        base_path = root / "base"
        upstream_path = root / "upstream"
        local_path.write_text(local, encoding="utf-8")
        base_path.write_text(base, encoding="utf-8")
        upstream_path.write_text(upstream, encoding="utf-8")
        result = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "-L",
                "local",
                "-L",
                "base",
                "-L",
                "upstream",
                str(local_path),
                str(base_path),
                str(upstream_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode not in (0, 1):
            raise SystemExit(
                f"git merge-file failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout, result.returncode == 1


def baseline_plan(
    target_repo: Path, relative_path: str, upstream: str
) -> FilePlan:
    path = sync_base_path(relative_path)
    target = target_repo / path
    if not target.exists():
        action = "create"
    elif target.read_text(encoding="utf-8", errors="replace") == upstream:
        action = "no-op"
    else:
        action = "update"
    return FilePlan(path=path, action=action, content=upstream)


def plan_three_way_update(
    target_repo: Path,
    relative_path: str,
    existing: str,
    upstream: str,
    *,
    fallback: tuple[str, str] | None = None,
) -> tuple[str | None, str]:
    base = target_repo / sync_base_path(relative_path)
    if not base.exists():
        if fallback is not None:
            return fallback
        return None, "sync-base-missing"
    merged, conflicted = three_way_merge(
        existing,
        base.read_text(encoding="utf-8", errors="replace"),
        upstream,
    )
    if conflicted:
        return merged, "merge-conflict"
    return merged, "no-op" if merged == existing else "merge"


def extract_managed_block(content: str) -> str | None:
    start = content.find(MANAGED_START)
    end = content.find(MANAGED_END)
    if start == -1 or end == -1 or end < start:
        return None
    return content[start : end + len(MANAGED_END)]


def replace_metadata_block(content: str, metadata: str) -> str:
    if METADATA_RE.search(content):
        # Use a callable replacement so backslashes in `metadata` (e.g. from a
        # Windows path in the source URL) aren't parsed as regex escapes.
        return METADATA_RE.sub(lambda _match: metadata, content, count=1)
    for heading in ("# AGENTS.md", "# CLAUDE.md", "# GEMINI.md"):
        if content.startswith(heading):
            return content.replace(f"{heading}\n", f"{heading}\n\n{metadata}\n", 1)
    return f"{metadata}\n\n{content}"


def replace_managed_block(existing: str, rendered: str) -> str:
    new_block = extract_managed_block(rendered)
    if not new_block:
        return existing

    if extract_managed_block(existing):
        start = existing.find(MANAGED_START)
        end = existing.find(MANAGED_END) + len(MANAGED_END)
        return existing[:start] + new_block + existing[end:]

    insertion = f"\n\n{new_block}\n"
    if "## Repository-specific Boundaries" in existing:
        return existing.replace("## Repository-specific Boundaries", insertion + "\n## Repository-specific Boundaries", 1)
    return existing.rstrip() + insertion + "\n"


def update_agents_content(existing: str, rendered: str, metadata: str) -> str:
    updated = replace_metadata_block(existing, metadata)
    updated = replace_managed_block(updated, rendered)
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def section_present(content: str, heading: str) -> bool:
    return re.search(rf"^##\s+{re.escape(heading)}\s*$", content, re.MULTILINE) is not None


def merge_agents_content(
    existing: str,
    rendered: str,
    metadata: str,
    shared_url: str,
    *,
    skills_section: str = "",
) -> str:
    content = replace_metadata_block(existing, metadata)
    additions: list[str] = []

    if shared_url not in content:
        additions.append(
            "This repository follows the shared agent rules from:\n\n"
            f"- {shared_url}\n"
        )

    rendered_block = extract_managed_block(rendered)
    # The managed block already carries Shared Skills when rendered fresh, so
    # track whether it was added here to avoid duplicating that section below.
    managed_block_added = False
    if rendered_block and (
        not section_present(content, "Agent Usage Model")
        or not section_present(content, "Core Rules")
    ):
        additions.append(rendered_block)
        managed_block_added = True

    for heading in ("Repository-specific Boundaries", "Validation", "Final Report"):
        if section_present(content, heading):
            continue
        pattern = re.compile(
            rf"(^##\s+{re.escape(heading)}\s*$.*?)(?=^##\s+|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(rendered)
        if match:
            additions.append(match.group(1).strip())
        else:
            additions.append(
                f"## {heading}\n\n"
                f"<!-- TODO(agent-rules): add repository-specific {heading.lower()} guidance. -->"
            )

    # A legacy file commonly already has Agent Usage Model and Core Rules
    # (so managed_block_added is False above) but predates --skills, so it
    # needs Shared Skills added on its own rather than via the whole block.
    if (
        skills_section
        and not managed_block_added
        and not section_present(content, "Shared Skills")
    ):
        additions.append(skills_section)

    if additions:
        content = content.rstrip() + "\n\n" + "\n\n".join(additions).strip() + "\n"
    if not content.endswith("\n"):
        content += "\n"
    return content


def plan_generated_update(
    existing: str, rendered: str, metadata: str, relative_path: str
) -> tuple[str, str]:
    """Refresh a generated entrypoint that carries agent-rules metadata.

    Files with managed markers get an in-place managed-block update that
    preserves local sections. Legacy generated files without markers are fully
    regenerated (partial update cannot locate the shared content in them).
    AGENTS.md always takes the in-place path: replace_managed_block knows how
    to insert the block before its Repository-specific Boundaries section.
    """
    if MANAGED_START in existing or relative_path == "AGENTS.md":
        content = update_agents_content(existing, rendered, metadata)
    else:
        content = rendered
    return content, ("no-op" if content == existing else "update")


def file_action(target_repo: Path, relative_path: str, *, update: bool, force: bool) -> str:
    path = target_repo / relative_path
    if path.exists():
        if update:
            return "update"
        if force:
            return "overwrite"
        return "exists"
    return "create"


def build_entrypoint_plans(
    target_repo: Path,
    profile: str,
    context: RenderContext,
    *,
    sync: bool,
    update: bool,
    merge: bool,
    force: bool,
) -> list[FilePlan]:
    if sync:
        # Determine whether to update or merge based on metadata presence
        _primary = required_files_for_profile(profile)[0]
        _primary_path = target_repo / _primary
        if _primary_path.exists():
            _existing = _primary_path.read_text(encoding="utf-8", errors="replace")
            if parse_metadata(_existing):
                update = True
            elif _primary == "AGENTS.md":
                merge = True
            else:
                update = True
    plans: list[FilePlan] = []
    primary_file = required_files_for_profile(profile)[0]
    for relative_path in required_files_for_profile(profile):
        rendered = render_file_for_profile(relative_path, context)
        path = target_repo / relative_path
        action = file_action(target_repo, relative_path, update=update, force=force)

        if action == "exists" and not merge:
            plans.append(FilePlan(path=relative_path, action="exists"))
            continue

        if relative_path == primary_file and path.exists():
            existing = path.read_text(encoding="utf-8", errors="replace")
            metadata = render_metadata(
                shared_url=context.shared_rules_url,
                profile=context.profile,
                source_commit=context.source_commit,
                generated_at=context.generated_at,
            )
            if update and parse_metadata(existing):
                content, action = plan_three_way_update(
                    target_repo,
                    relative_path,
                    existing,
                    rendered,
                    fallback=plan_generated_update(
                        existing, rendered, metadata, relative_path
                    ),
                )
            elif update:
                content = None
                action = "metadata-missing"
            elif merge and relative_path == "AGENTS.md":
                content = merge_agents_content(
                    existing,
                    rendered,
                    metadata,
                    context.shared_rules_url,
                    skills_section=(
                        shared_skills_section("AGENTS.md")
                        if context.install_skills
                        else ""
                    ),
                )
                action = "no-op" if content == existing else "merge"
            elif force:
                content = rendered
            else:
                content = None
            plans.append(FilePlan(path=relative_path, action=action, content=content))
            plans.append(baseline_plan(target_repo, relative_path, rendered))
            continue

        if relative_path in TOOL_ENTRYPOINTS and path.exists() and update:
            existing = path.read_text(encoding="utf-8", errors="replace")
            if parse_metadata(existing):
                metadata = render_metadata(
                    shared_url=context.shared_rules_url,
                    profile=context.profile,
                    source_commit=context.source_commit,
                    generated_at=context.generated_at,
                )
                content, action = plan_generated_update(
                    existing, rendered, metadata, relative_path
                )
                content, action = plan_three_way_update(
                    target_repo,
                    relative_path,
                    existing,
                    rendered,
                    fallback=(content, action),
                )
            else:
                content = None
                action = "metadata-missing"
            plans.append(FilePlan(path=relative_path, action=action, content=content))
            plans.append(baseline_plan(target_repo, relative_path, rendered))
            continue

        plans.append(FilePlan(path=relative_path, action=action, content=rendered))
        plans.append(baseline_plan(target_repo, relative_path, rendered))
    return plans


def local_copy_file_specs(profile: str) -> list[tuple[Path, str]]:
    root = source_repo_root()
    specs: list[tuple[Path, str]] = []
    specs.append((Path("SOURCE_COMMIT"), ".agents/agent-rules/SOURCE_COMMIT"))
    for name in required_files_for_profile(profile):
        source_name = name
        specs.append((root / source_name, f".agents/agent-rules/{name}"))
    for directory in ("rules", "templates", "skills"):
        for source in sorted((root / directory).rglob("*")):
            if source.is_file():
                specs.append((source, f".agents/agent-rules/{source.relative_to(root).as_posix()}"))
    for name in ("lightweight-adoption.md", "scripted-adoption.md"):
        source = root / "docs" / name
        specs.append((source, f".agents/agent-rules/docs/{name}"))
    return specs


def shared_skill_file_specs(profile: str) -> list[tuple[Path, str]]:
    root = source_repo_root()
    specs: list[tuple[Path, str]] = []
    for skill_name in SHARED_SKILLS:
        skill_root = root / "skills" / skill_name
        codex_only_files = CODEX_ONLY_SKILL_FILES.get(skill_name, ())
        for destination_root in PROFILE_SKILL_ROOTS[profile]:
            for source in sorted(skill_root.rglob("*")):
                if source.is_file():
                    relative = source.relative_to(skill_root).as_posix()
                    if (
                        destination_root == ".claude/skills"
                        and relative in codex_only_files
                    ):
                        continue
                    specs.append(
                        (source, f"{destination_root}/{skill_name}/{relative}")
                    )
    return specs


def build_shared_skill_plans(
    target_repo: Path,
    profile: str,
    *,
    update: bool,
    force: bool,
) -> list[FilePlan]:
    plans: list[FilePlan] = []
    for source, relative_path in shared_skill_file_specs(profile):
        target = target_repo / relative_path
        upstream = source.read_text(encoding="utf-8")
        if target.exists():
            if update:
                content, action = plan_three_way_update(
                    target_repo,
                    relative_path,
                    target.read_text(encoding="utf-8", errors="replace"),
                    upstream,
                    fallback=(None, "no-op")
                    if target.read_text(encoding="utf-8", errors="replace") == upstream
                    else None,
                )
            elif force:
                action = "overwrite"
                content = upstream
            else:
                action = "exists"
                content = None
        else:
            action = "create"
            content = upstream
        plans.append(FilePlan(path=relative_path, action=action, content=content))
        plans.append(baseline_plan(target_repo, relative_path, upstream))
    return plans


def build_local_copy_plans(
    target_repo: Path,
    profile: str,
    source_commit: str,
    *,
    update: bool,
    force: bool,
) -> list[FilePlan]:
    plans: list[FilePlan] = []
    local_copy_root = target_repo / ".agents" / "agent-rules"
    existing_local_copy_without_update = local_copy_root.exists() and not (update or force)
    for source, relative_path in local_copy_file_specs(profile):
        target = target_repo / relative_path
        if source == Path("SOURCE_COMMIT"):
            content = source_commit + "\n"
            if existing_local_copy_without_update:
                action = "exists" if target.exists() else "blocked-existing-local-copy"
            elif target.exists() and target.read_text(encoding="utf-8", errors="replace") == content:
                action = "no-op"
            elif target.exists():
                action = "update"
            else:
                action = "create"
            plans.append(FilePlan(path=relative_path, action=action, content=content))
        else:
            if existing_local_copy_without_update:
                action = "exists" if target.exists() else "blocked-existing-local-copy"
            else:
                source_content = source.read_text(encoding="utf-8")
                if target.exists():
                    target_content = target.read_text(encoding="utf-8", errors="replace")
                    action = "no-op" if source_content == target_content else "update"
                else:
                    action = "create"
            plans.append(FilePlan(path=relative_path, action=action, source=source))
    return plans


def read_local_copy_commit(target_repo: Path) -> str | None:
    path = target_repo / ".agents" / "agent-rules" / "SOURCE_COMMIT"
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8", errors="replace").strip()
    return value or None


def build_plan(
    target_repo: Path,
    args: argparse.Namespace,
    profile: str | None,
) -> AdoptionPlan:
    git_root = find_repo_root(target_repo)
    detected = detect_repository_type(target_repo)
    source_status = get_source_status(args.shared_url)
    metadata: dict[str, str] = {}
    for _name in ENTRYPOINT_FILES:
        _p = target_repo / _name
        if _p.exists():
            _m = parse_metadata(_p.read_text(encoding="utf-8", errors="replace"))
            if _m:
                metadata = _m
                break
    files: list[FilePlan] = []
    warnings = list(source_status.warnings)
    if git_root is not None and git_root != target_repo:
        warnings.append(
            f"WARN: target path is inside a Git repository but is not the root: {git_root}"
        )

    if profile:
        context = build_render_context(args, profile, source_status, detected)
        files.extend(
            build_entrypoint_plans(
                target_repo,
                profile,
                context,
                sync=args.sync,
                update=False,
                merge=False,
                force=args.force,
            )
        )
        if args.local_copy:
            files.extend(
                build_local_copy_plans(
                    target_repo,
                    profile,
                    source_status.local_head or "unknown",
                    update=args.sync,
                    force=args.force,
                )
            )
        if args.skills:
            files.extend(
                build_shared_skill_plans(
                    target_repo,
                    profile,
                    update=args.sync,
                    force=args.force,
                )
            )

    ignore_statuses = (
        check_generated_files_ignored(target_repo, git_root, files) if files else []
    )
    return AdoptionPlan(
        target_repo=target_repo,
        git_root=git_root,
        profile=profile,
        metadata=metadata,
        source_status=source_status,
        local_copy_commit=read_local_copy_commit(target_repo),
        files=files,
        ignore_statuses=ignore_statuses,
        detected=detected,
        warnings=warnings,
    )


def print_profile_help() -> None:
    print("No agent profile selected.\n")
    print("Choose one:")
    print("- --profile codex   : create AGENTS.md only")
    print("- --profile claude  : create CLAUDE.md only")
    print("- --profile gemini  : create GEMINI.md only")
    print("- --profile all     : create AGENTS.md + CLAUDE.md + GEMINI.md")


def latest_status_for_target(metadata: dict[str, str], source_status: SourceStatus) -> str:
    return target_commit_status(
        metadata.get("source_commit"), source_status, source_repo_root()
    )


def extract_validation_commands(content: str) -> list[str]:
    section = re.search(
        r"^##\s+Validation\s*$(.*?)(?=^##\s+|\Z)", content, re.MULTILINE | re.DOTALL
    )
    if not section:
        return []
    commands: list[str] = []
    for block in re.findall(r"```bash\n(.*?)```", section.group(1), re.DOTALL):
        commands.extend(
            line.strip()
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return commands


def append_check(results: list[tuple[str, str]], status: str, message: str) -> None:
    results.append((status, message))


def check_adoption(
    target_repo: Path,
    shared_url: str,
    *,
    check_skills: bool = False,
    visibility: str = "local",
    profile_override: str | None = None,
) -> int:
    results: list[tuple[str, str]] = []
    git_root = find_repo_root(target_repo)

    # Find metadata from any agent instruction file (AGENTS.md takes priority)
    metadata: dict[str, str] = {}
    metadata_file: str | None = None
    primary_content = ""
    metadata_candidates = (
        required_files_for_profile(profile_override)
        if profile_override in VALID_PROFILES
        else list(ENTRYPOINT_FILES)
    )
    for name in metadata_candidates:
        p = target_repo / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            m = parse_metadata(text)
            if m:
                metadata = m
                metadata_file = name
                primary_content = text
                break

    agents_path = target_repo / "AGENTS.md"
    agents_content = (
        agents_path.read_text(encoding="utf-8", errors="replace")
        if agents_path.exists()
        else ""
    )
    if not primary_content:
        primary_content = agents_content

    has_shared_url = shared_url in primary_content or bool(metadata.get("source"))
    legacy_adoption = agents_path.exists() and not metadata and shared_url in agents_content

    existing_files = [
        n for n in ENTRYPOINT_FILES if (target_repo / n).exists()
    ]
    append_check(
        results,
        "OK" if existing_files else "FAIL",
        f"agent file(s) found: {', '.join(existing_files)}"
        if existing_files
        else "no agent instruction file found (AGENTS.md, CLAUDE.md, or GEMINI.md)",
    )

    if metadata:
        append_check(results, "OK", f"agent-rules metadata block exists ({metadata_file})")
    elif legacy_adoption:
        append_check(results, "WARN", "legacy adoption detected; run --sync to add metadata")
    else:
        append_check(results, "FAIL", "agent-rules metadata block is missing")

    append_check(
        results,
        "OK" if has_shared_url else "FAIL",
        "shared source URL found" if has_shared_url else "shared source URL is missing",
    )
    append_check(
        results,
        "OK" if metadata.get("source_commit") else "WARN" if legacy_adoption else "FAIL",
        "source_commit found"
        if metadata.get("source_commit")
        else "legacy adoption detected; run --sync to add metadata"
        if legacy_adoption
        else "source_commit is missing",
    )

    metadata_profile = metadata.get("profile")
    profile = profile_override or metadata_profile
    profile_matches = (
        profile in VALID_PROFILES
        and (profile_override is None or metadata_profile == profile_override)
    )
    append_check(
        results,
        "OK" if profile_matches else "WARN" if legacy_adoption else "FAIL",
        f"profile: {profile}"
        if profile_matches
        else f"profile mismatch: expected {profile_override}, found {metadata_profile}"
        if profile_override and metadata_profile
        else "legacy adoption detected; run --sync to add metadata"
        if legacy_adoption
        else "profile is missing or invalid",
    )

    required = (
        required_files_for_profile(profile)
        if profile in VALID_PROFILES
        else existing_files or ["AGENTS.md"]
    )
    for relative_path in required:
        path = target_repo / relative_path
        append_check(
            results,
            "OK" if path.exists() else "FAIL",
            f"{relative_path} exists"
            if path.exists()
            else f"{relative_path} is required by profile but missing",
        )
        baseline = target_repo / sync_base_path(relative_path)
        append_check(
            results,
            "OK" if baseline.exists() else "WARN",
            f"sync baseline exists for {relative_path}"
            if baseline.exists()
            else f"sync baseline missing for {relative_path}; run --sync to establish it",
        )

    skill_paths: list[str] = []
    if check_skills and profile in VALID_PROFILES:
        for root in PROFILE_SKILL_ROOTS[profile]:
            for skill_name in SHARED_SKILLS:
                relative_path = f"{root}/{skill_name}/SKILL.md"
                skill_paths.append(relative_path)
                path = target_repo / relative_path
                append_check(
                    results,
                    "OK" if path.exists() else "FAIL",
                    f"{relative_path} exists"
                    if path.exists()
                    else f"{relative_path} is required by --skills but missing",
                )
                baseline = target_repo / sync_base_path(relative_path)
                append_check(
                    results,
                    "OK" if baseline.exists() else "WARN",
                    f"sync baseline exists for {relative_path}"
                    if baseline.exists()
                    else f"sync baseline missing for {relative_path}",
                )

        codex_root = PROFILE_SKILL_ROOTS["codex"][0]
        claude_root = PROFILE_SKILL_ROOTS["claude"][0]
        for skill_name in SHARED_SKILLS:
            codex_skill = target_repo / codex_root / skill_name / "SKILL.md"
            claude_skill = target_repo / claude_root / skill_name / "SKILL.md"
            if codex_skill.exists() and claude_skill.exists():
                contracts_match = codex_skill.read_bytes() == claude_skill.read_bytes()
                append_check(
                    results,
                    "OK" if contracts_match else "FAIL",
                    f"Codex and Claude {skill_name} contracts match"
                    if contracts_match
                    else f"Codex and Claude {skill_name} contracts differ",
                )
            for codex_only_file in CODEX_ONLY_SKILL_FILES.get(skill_name, ()):
                leaked = target_repo / claude_root / skill_name / codex_only_file
                if leaked.exists():
                    append_check(
                        results,
                        "WARN",
                        f"Claude {skill_name} skill contains Codex-only "
                        f"{codex_only_file} metadata; remove it",
                    )

        for relative_path in required:
            if not ENTRYPOINT_SKILL_ROOTS.get(relative_path):
                continue
            path = target_repo / relative_path
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            append_check(
                results,
                "OK" if "## Shared Skills" in content else "WARN",
                f"{relative_path} contains a Shared Skills trigger section"
                if "## Shared Skills" in content
                else f"{relative_path} lacks a Shared Skills trigger section; run --sync --skills to add it",
            )

    if BOUNDARY_PLACEHOLDER in primary_content:
        append_check(
            results,
            "WARN",
            "Repository-specific Boundaries still contains placeholder text",
        )
    validation_commands = extract_validation_commands(primary_content)
    if not validation_commands or validation_commands == ["git diff --check"]:
        append_check(results, "WARN", "Validation only contains git diff --check")
    if VALIDATION_PLACEHOLDER in primary_content:
        append_check(results, "WARN", "Validation still contains placeholder text")

    plans = [FilePlan(path=name, action="check") for name in required]
    plans.extend(
        FilePlan(path=sync_base_path(name), action="check") for name in required
    )
    plans.extend(FilePlan(path=name, action="check") for name in skill_paths)
    plans.extend(
        FilePlan(path=sync_base_path(name), action="check") for name in skill_paths
    )
    local_copy_root = target_repo / ".agents" / "agent-rules"
    if local_copy_root.exists():
        plans.append(FilePlan(path=".agents/agent-rules/SOURCE_COMMIT", action="check"))
        if not (local_copy_root / "SOURCE_COMMIT").exists():
            append_check(results, "FAIL", ".agents/agent-rules/SOURCE_COMMIT is missing")
    for status in check_generated_files_ignored(target_repo, git_root, plans):
        is_entrypoint = Path(status.path).name in ENTRYPOINT_FILES
        is_generated = (
            is_entrypoint
            or status.path in skill_paths
            or status.path.startswith(f"{SYNC_BASE_ROOT}/")
        )
        if is_generated:
            if visibility == "tracked" and status.ignored and not status.tracked:
                append_check(results, "FAIL", f"{status.path} is ignored but should be tracked")
            elif visibility == "tracked" and status.tracked:
                append_check(results, "OK", f"{status.path} is tracked")
            elif visibility == "tracked":
                append_check(results, "WARN", f"{status.path} is trackable but untracked")
            elif status.tracked:
                append_check(results, "WARN", f"{status.path} is tracked; run: git rm --cached {status.path}")
            elif not status.ignored:
                append_check(results, "WARN", f"{status.path} is not in .gitignore; run adopt to add it")
            # ignored+untracked is the expected state; no check entry needed
        else:
            if status.ignored and not status.tracked:
                append_check(results, "FAIL", f"{status.path} is ignored by .gitignore")
            elif status.warning:
                append_check(results, "WARN", status.warning)

    if (target_repo / "rules" / "commit-guidelines.md").exists():
        append_check(
            results,
            "WARN",
            "root-level rules/ looks like an agent-rules copy; use .agents/agent-rules/",
        )
    if (target_repo / "templates" / "task-instruction-template.md").exists():
        append_check(
            results,
            "WARN",
            "root-level templates/ looks like an agent-rules copy; use .agents/agent-rules/",
        )

    for status, message in results:
        print(f"[{status}] {message}")

    source_status = get_source_status(shared_url)
    target_status = latest_status_for_target(metadata, source_status)
    local_copy_commit = read_local_copy_commit(target_repo)

    print("\nSource status:")
    print(f"- local source HEAD: {source_status.local_head or 'unknown'}")
    print(f"- remote main HEAD: {source_status.remote_head or 'unknown'}")
    print(f"- local source status: {source_status.local_status}")
    for warning in source_status.warnings:
        print(f"- {warning}")
    print("\nTarget status:")
    print(f"- applied source_commit: {metadata.get('source_commit', 'missing')}")
    print(f"- applied profile: {metadata.get('profile', 'missing')}")
    print(f"- latest status: {target_status}")
    if local_copy_commit:
        local_copy_status = target_commit_status(
            local_copy_commit, source_status, source_repo_root()
        )
        print(f"- local copy commit: {local_copy_commit}")
        print(f"- local copy status: {local_copy_status}")

    has_fail = any(status == "FAIL" for status, _ in results)
    has_warn = any(status == "WARN" for status, _ in results)
    if has_fail:
        return 1
    if has_warn:
        return 2
    return 0


def write_plan_file(
    target_repo: Path,
    plan: FilePlan,
    *,
    dry_run: bool,
) -> tuple[str, str]:
    path = target_repo / plan.path
    if plan.action == "no-op":
        return "Skipped", plan.path
    if plan.action == "blocked-existing-local-copy":
        raise SystemExit(
            f"Refusing to apply local copy because .agents/agent-rules already exists: {target_repo / '.agents' / 'agent-rules'}\n"
            "Use --local-copy --sync to refresh the existing local copy, or --force "
            "to overwrite intentionally."
        )
    if plan.action == "metadata-missing":
        raise SystemExit(
            f"Refusing to update file without agent-rules metadata: {path}\n"
            "Use --sync to preserve existing content and add metadata, or --force "
            "to overwrite intentionally."
        )
    if plan.action == "sync-base-missing":
        raise SystemExit(
            f"Refusing to sync a modified generated file without a baseline: {path}\n"
            "Re-run with --force to establish a new baseline, or restore the generated "
            "file and run --sync again."
        )
    if plan.action == "merge-conflict":
        preview = f"\n\nConflict preview:\n{plan.content.rstrip()}" if plan.content else ""
        raise SystemExit(
            f"Refusing to write unresolved merge conflicts: {path}\n"
            "Run with --dry-run to inspect the conflict, then reconcile the local "
            f"changes or use --force intentionally.{preview}"
        )
    if plan.action == "exists":
        if plan.path.startswith(".agents/agent-rules/"):
            raise SystemExit(
                f"Refusing to apply local copy because .agents/agent-rules already exists: {target_repo / '.agents' / 'agent-rules'}\n"
                "Use --local-copy --sync to refresh the existing local copy, or --force "
                "to overwrite intentionally."
            )
        raise SystemExit(
            f"Refusing to overwrite existing file: {path}\n"
            "Use --sync to update files with agent-rules metadata, or --force to overwrite."
        )

    existed = path.exists()
    if dry_run:
        print(f"Would {plan.action}: {path}")
        if plan.content is not None:
            print("-" * 72)
            print(plan.content.rstrip())
            print("-" * 72)
        elif plan.source is not None:
            print(f"Source: {plan.source}")
        return ("Updated" if existed else "Created", plan.path)

    path.parent.mkdir(parents=True, exist_ok=True)
    if plan.content is not None:
        path.write_text(plan.content, encoding="utf-8")
    elif plan.source is not None:
        shutil.copy2(plan.source, path)
    else:
        raise SystemExit(f"No content or source for planned file: {plan.path}")
    return ("Updated" if existed else "Created", plan.path)


def validate_plan_before_write(plan: AdoptionPlan) -> int:
    if plan.is_subdir_target:
        print(
            "FAIL: target path is inside a Git repository but is not the repository root.\n"
            f"- target: {plan.target_repo}\n"
            f"- git root: {plan.git_root}\n\n"
            "Run the helper from the Git repository root."
        )
        return 1

    for item in plan.files:
        if item.action in {
            "exists",
            "metadata-missing",
            "blocked-existing-local-copy",
            "sync-base-missing",
            "merge-conflict",
        }:
            try:
                write_plan_file(plan.target_repo, item, dry_run=True)
            except SystemExit as exc:
                print(exc)
                return 1
    return 0


def print_summary(
    created: list[str],
    updated: list[str],
    skipped: list[str],
    plan: AdoptionPlan,
    gitignore_file: str | None = None,
    visibility: str = "local",
) -> None:
    print("\nCreated:")
    print("\n".join(f"- {item}" for item in created) if created else "- none")
    print("\nUpdated:")
    print("\n".join(f"- {item}" for item in updated) if updated else "- none")
    print("\nSkipped:")
    print("\n".join(f"- {item}" for item in skipped) if skipped else "- none")
    if gitignore_file:
        print("\n.gitignore updated (local-only):")
        print(f"- {gitignore_file}")

    print("\nWarnings:")
    warnings = list(plan.warnings)
    if plan.source_status.local_status in {"behind", "ahead", "different", "diverged"}:
        warnings.append(
            f"Local agent-rules source status versus remote main is {plan.source_status.local_status}."
        )
    for status in plan.ignore_statuses:
        if status.warning:
            warnings.append(status.warning)
    print("\n".join(f"- {warning}" for warning in warnings) if warnings else "- none")

    print("\nGitignore:")
    if plan.ignore_statuses:
        for status in plan.ignore_statuses:
            is_entrypoint = Path(status.path).name in ENTRYPOINT_FILES
            if is_entrypoint:
                if gitignore_file:
                    print(f"- OK: {status.path} added to .gitignore (local-only)")
                elif status.ignored and not status.tracked:
                    print(f"- OK: {status.path} is local-only (already in .gitignore)")
                elif status.tracked:
                    print(f"- WARN: {status.path} is tracked (consider untracking to make local-only)")
                else:
                    print(f"- NOTE: {status.path} is not effectively in .gitignore")
            else:
                if status.ignored and status.tracked:
                    print(f"- OK: {status.path} is tracked despite ignore match")
                elif status.ignored:
                    print(f"- WARN: {status.path} is ignored")
                else:
                    print(f"- OK: {status.path} is not ignored")
    else:
        print("- no generated files checked")

    print("\nLatest source status:")
    print(f"- local: {plan.source_status.local_head or 'unknown'}")
    print(f"- remote main: {plan.source_status.remote_head or 'unknown'}")
    print(f"- status: {plan.source_status.local_status}")

    if plan.detected.repo_types:
        print("\nDetected repository type:")
        print(f"- {', '.join(plan.detected.repo_types) if plan.detected.repo_types else 'none'}")
        print("\nSuggested validation commands:")
        for command in plan.detected.validation_commands:
            print(f"- {command}")

    changed = created + updated
    generated_agent_files = [
        p
        for p in changed
        if Path(p).name in ENTRYPOINT_FILES
        or p.startswith(
            (".codex/skills/", ".claude/skills/", f"{SYNC_BASE_ROOT}/")
        )
    ]
    committable_changed = [
        p
        for p in changed
        if visibility == "tracked" or p not in generated_agent_files
    ]

    print("\nNext commands:")
    if committable_changed:
        print("- git diff -- " + " ".join(committable_changed))
    print("- git diff --check")
    if gitignore_file:
        print(f"- git add {gitignore_file}")
    if committable_changed:
        print("- git add " + " ".join(committable_changed))
    if gitignore_file and committable_changed:
        print('- git commit -m "docs(agent): adopt shared agent rules and ignore local entrypoints"')
    elif committable_changed:
        print('- git commit -m "docs(agent): adopt shared agent rules"')
    elif gitignore_file:
        print('- git commit -m "chore: ignore local agent entrypoint files"')


def apply_plan(plan: AdoptionPlan, args: argparse.Namespace) -> int:
    preflight_result = validate_plan_before_write(plan)
    if preflight_result:
        return preflight_result

    # Local copy files (.agents/) must be committable; fail if they're ignored
    local_copy_ignored = [
        s for s in plan.ignore_statuses
        if s.path.startswith(".agents/") and s.ignored and not s.tracked
    ]
    if local_copy_ignored:
        return fail_on_ignored(local_copy_ignored)

    if args.visibility == "tracked":
        tracked_outputs_ignored = [
            status
            for status in plan.ignore_statuses
            if status.ignored and not status.tracked
        ]
        if tracked_outputs_ignored:
            return fail_on_ignored(tracked_outputs_ignored)

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    for item in plan.files:
        bucket, path = write_plan_file(plan.target_repo, item, dry_run=args.dry_run)
        if bucket == "Created":
            created.append(path)
        elif bucket == "Updated":
            updated.append(path)
        else:
            skipped.append(path)

    # Local visibility ignores only files generated for the selected profile.
    git_root = plan.git_root or plan.target_repo
    generated_local_paths = [
        item.path
        for item in plan.files
        if item.path in ENTRYPOINT_FILES
        or item.path.startswith(
            (".codex/skills/", ".claude/skills/", f"{SYNC_BASE_ROOT}/")
        )
    ]
    any_local_output_written = any(
        path in generated_local_paths for path in (created + updated)
    )
    gitignore_file: str | None = None
    if any_local_output_written and args.visibility == "local":
        gitignore_file = add_to_gitignore(
            git_root,
            generated_local_paths,
            dry_run=args.dry_run,
        )

    print_summary(
        created,
        updated,
        skipped,
        plan,
        gitignore_file=gitignore_file,
        visibility=args.visibility,
    )
    return 0


def _read_batch_file_text(batch_file: Path) -> str:
    try:
        return batch_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"Batch file is not valid UTF-8: {batch_file}\n"
            f"({exc}). Re-save it as UTF-8 (e.g. from Notepad's 'Save As' encoding option)."
        ) from exc


def parse_batch_file(batch_file: Path) -> list[BatchEntry]:
    if batch_file.suffix == ".toml":
        return _parse_toml_batch(batch_file)
    return _parse_text_batch(batch_file)


def _parse_toml_batch(batch_file: Path) -> list[BatchEntry]:
    if tomllib is None:
        raise SystemExit("TOML batch files require Python 3.11+.")
    data = tomllib.loads(_read_batch_file_text(batch_file))
    repos = data.get("repos", [])
    if not isinstance(repos, list):
        raise SystemExit("TOML batch file must contain a [[repos]] array.")
    entries: list[BatchEntry] = []
    for item in repos:
        if not isinstance(item, dict) or "path" not in item:
            raise SystemExit(f"Each [[repos]] entry must have a 'path' field: {item}")
        entries.append(BatchEntry(path=item["path"], profile=item.get("profile")))
    return entries


def _parse_text_batch(batch_file: Path) -> list[BatchEntry]:
    entries: list[BatchEntry] = []
    for line in _read_batch_file_text(batch_file).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(BatchEntry(path=line))
    return entries


def run_batch(batch_file: Path, args: argparse.Namespace) -> int:
    entries = parse_batch_file(batch_file)
    if not entries:
        print("No repositories found in batch file.")
        return 0

    results: list[tuple[str, int]] = []
    for entry in entries:
        print(f"\n{'─' * 60}")
        print(f"  {entry.path}")
        print(f"{'─' * 60}")

        try:
            target_repo = resolve_target_repo(entry.path)
        except (SystemExit, Exception) as exc:
            # Catch broadly, not just SystemExit: a single misbehaving
            # repository (bad encoding, unexpected git state, ...) must not
            # abort the rest of the batch.
            print(f"FAIL: {exc}")
            results.append((entry.path, 1))
            continue

        try:
            profile = parse_profile(entry.profile or args.profile)
            if profile is None and (args.check or args.sync):
                profile = infer_profile_from_existing(target_repo)
        except (SystemExit, Exception) as exc:
            # Catch broadly, not just SystemExit: a single misbehaving
            # repository (bad encoding, unexpected git state, ...) must not
            # abort the rest of the batch.
            print(f"FAIL: {exc}")
            results.append((entry.path, 1))
            continue

        try:
            if args.check:
                code = check_adoption(
                    target_repo,
                    args.shared_url,
                    check_skills=args.skills,
                    visibility=args.visibility,
                    profile_override=profile,
                )
            else:
                if not profile:
                    print("FAIL: no profile specified and none inferred from existing files.")
                    results.append((entry.path, 1))
                    continue
                # Per-entry copy: skills inference for one repository must not
                # leak into the rest of the batch.
                entry_args = argparse.Namespace(**vars(args))
                if (
                    entry_args.sync
                    and not entry_args.skills
                    and skills_installed(target_repo, profile)
                ):
                    entry_args.skills = True
                plan = build_plan(target_repo, entry_args, profile)
                if entry_args.sync and plan.source_status.local_status in {"behind", "different", "diverged"}:
                    print(f"FAIL: local source is {plan.source_status.local_status}. Update agent-rules first.")
                    results.append((entry.path, 1))
                    continue
                code = apply_plan(plan, entry_args)
        except (SystemExit, Exception) as exc:
            print(f"FAIL: {exc}")
            code = 1

        results.append((entry.path, code))

    print(f"\n{'═' * 60}")
    succeeded = [p for p, c in results if c == 0]
    # Exit code 2 means WARN-only (from check_adoption); anything else non-zero failed.
    warned = [p for p, c in results if c == 2]
    failed = [p for p, c in results if c not in (0, 2)]
    print(f"{len(succeeded)} succeeded, {len(warned)} warned, {len(failed)} failed")
    if warned:
        print("\nWarnings only:")
        for p in warned:
            print(f"  - {p}")
    if failed:
        print("\nFailed:")
        for p in failed:
            print(f"  - {p}")
    if failed:
        return 1
    if warned:
        return 2
    return 0


def validate_args(args: argparse.Namespace, profile: str | None) -> None:
    if args.sync and args.force:
        raise SystemExit("Use either --sync or --force, not both.")
    if args.batch:
        return
    write_requested = not args.check
    if write_requested and not profile:
        print_profile_help()
        raise SystemExit(2)


def infer_profile_from_existing(target_repo: Path) -> str | None:
    for name in ENTRYPOINT_FILES:
        p = target_repo / name
        if p.exists():
            m = parse_metadata(p.read_text(encoding="utf-8", errors="replace"))
            if m.get("profile"):
                return m["profile"]
    return None


def skills_installed(target_repo: Path, profile: str) -> bool:
    for root in PROFILE_SKILL_ROOTS.get(profile, ()):
        for skill_name in SHARED_SKILLS:
            if (target_repo / root / skill_name / "SKILL.md").exists():
                return True
    return False


def main() -> int:
    # Some Windows console code pages (e.g. cp949) can't encode every
    # character this script prints (box-drawing separators, em dashes).
    # Fall back instead of crashing mid-run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    args = parse_args()

    if args.batch:
        batch_file = Path(args.batch).expanduser().resolve()
        if not batch_file.exists():
            raise SystemExit(f"Batch file does not exist: {batch_file}")
        profile = parse_profile(args.profile)
        validate_args(args, profile)
        return run_batch(batch_file, args)

    target_repo = resolve_target_repo(args.target_repo)
    profile = parse_profile(args.profile)

    # Auto-detect profile from existing files when --check or --sync is requested
    if profile is None and (args.check or args.sync):
        profile = infer_profile_from_existing(target_repo)

    # Without this, --sync would render entrypoints skill-free and the 3-way
    # merge would strip the Shared Skills section from repositories whose
    # skills were installed by an earlier --skills run.
    if args.sync and not args.skills and profile and skills_installed(target_repo, profile):
        args.skills = True

    validate_args(args, profile)

    if args.check:
        return check_adoption(
            target_repo,
            args.shared_url,
            check_skills=args.skills,
            visibility=args.visibility,
            profile_override=profile,
        )

    plan = build_plan(target_repo, args, profile)

    if args.sync and plan.source_status.local_status in {"behind", "different", "diverged"}:
        print(
            f"FAIL: local agent-rules source status is {plan.source_status.local_status} versus remote main.\n"
            "Update local agent-rules first."
        )
        return 1

    return apply_plan(plan, args)


if __name__ == "__main__":
    raise SystemExit(main())
