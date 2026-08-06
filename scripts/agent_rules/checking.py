"""The --check health report and the --list-skills preview."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import (
    BOUNDARY_PLACEHOLDER,
    CODEX_ONLY_SKILL_PATHS,
    ENTRYPOINT_FILES,
    ENTRYPOINT_SKILL_ROOTS,
    PROFILE_SKILL_ROOTS,
    SHARED_SKILLS,
    SYNC_BASE_ROOT,
    VALID_PROFILES,
    VALIDATION_PLACEHOLDER,
)
from .gitio import check_generated_files_ignored, find_repo_root
from .metadata import parse_metadata
from .models import FilePlan, SourceStatus
from .planning import read_local_copy_commit, shared_skill_file_specs
from .source import (
    get_source_status,
    profile_skill_support,
    required_files_for_profile,
    source_repo_root,
    sync_base_path,
    target_commit_status,
)


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
    profile_matches = profile in VALID_PROFILES and (
        profile_override is None
        or metadata_profile == profile_override
        # "all" is a superset: a repo adopted with --profile all legitimately
        # has every agent's entrypoint, so checking one agent's slice of it
        # with an explicit --profile isn't a mismatch.
        or metadata_profile == "all"
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
        supported, unsupported = profile_skill_support(profile)
        if not supported:
            append_check(
                results,
                "FAIL",
                f"--skills has no effect for the {profile} profile: no "
                "shared-skill installation path exists for it yet",
            )
        elif unsupported:
            # NOTE, not WARN: this branch is only reachable for --profile all,
            # where an entrypoint without a shared-skill path (GEMINI.md) is
            # the expected outcome, not a defect. Reporting it as a warning
            # pinned --profile all --skills at exit 2 no matter how the
            # repository was configured, which cost the exit code its meaning.
            append_check(
                results,
                "NOTE",
                "shared skills are not supported for "
                f"{', '.join(unsupported)} ({profile} profile); nothing to fix",
            )
        # Derived from the same file list shared_skill_file_specs() installs,
        # so every installed file is checked, not just SKILL.md — a deleted
        # supporting file (e.g. a script or asset a skill ships alongside
        # SKILL.md) is caught the same way a deleted SKILL.md already was.
        for source, relative_path in shared_skill_file_specs(profile):
            skill_paths.append(relative_path)
            path = target_repo / relative_path
            append_check(
                results,
                "OK" if path.exists() else "FAIL",
                f"{relative_path} exists"
                if path.exists()
                # "the installed shared skills", not "--skills": skill checks
                # also run when --check infers them from an existing
                # installation, so the flag may never have been typed.
                else f"{relative_path} is required by the installed shared skills but missing",
            )
            baseline = target_repo / sync_base_path(relative_path)
            append_check(
                results,
                "OK" if baseline.exists() else "WARN",
                f"sync baseline exists for {relative_path}"
                if baseline.exists()
                else f"sync baseline missing for {relative_path}",
            )
            # Requires the installed file, not just the baseline: a staleness
            # verdict about a file that is not installed contradicts the FAIL
            # emitted above ("... but missing" followed by "... is current
            # with the local shared source"). The FAIL already says what to
            # do, so stay silent here rather than describe a file that a
            # reinstall is about to replace anyway.
            if baseline.exists() and path.exists():
                # Compares the recorded baseline (upstream content as of the
                # last --sync) against the *current local shared source* —
                # i.e. the literal file on disk under source_repo_root(),
                # same as every other read in this module (read_template(),
                # shared_skill_file_specs(), etc.) — not the installed copy
                # (which may carry intentional local edits and shouldn't be
                # flagged) and not a git commit (this check has no concept of
                # "committed"; an uncommitted edit to the local agent-rules
                # checkout counts as "the local shared source changed," same
                # as everywhere else --sync reads from). Catches a target
                # repo whose installed skill is stale relative to that local
                # source, which a codex-vs-claude parity check alone cannot
                # see since both installed copies can be equally stale.
                # Compared as decoded text, not raw bytes: writing the
                # baseline goes through write_text(), which normalizes line
                # endings to the platform default (CRLF on Windows), so a
                # byte comparison against the source's on-disk LF would
                # always report "stale" even with identical content.
                up_to_date = baseline.read_text(
                    encoding="utf-8", errors="replace"
                ) == source.read_text(encoding="utf-8")
                append_check(
                    results,
                    "OK" if up_to_date else "WARN",
                    f"{relative_path} is current with the local shared source"
                    if up_to_date
                    else f"{relative_path} is behind the local shared source; run --sync to update",
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
            for codex_only_file in CODEX_ONLY_SKILL_PATHS:
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


def shared_skill_summary(skill_name: str) -> str:
    """First sentence of a shared skill's SKILL.md description.

    The frontmatter description is the canonical, agent-neutral summary and is
    guaranteed present by the skill-authoring convention (enforced in
    tests/test_skills.py), so it is a safer source than the Codex-only
    agents/openai.yaml short_description.
    """
    skill_md = source_repo_root() / "skills" / skill_name / "SKILL.md"
    if not skill_md.exists():
        return ""
    match = re.search(
        r"^description:\s*(.+)$",
        skill_md.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        return ""
    description = match.group(1).strip()
    sentence, _, _ = description.partition(". ")
    return sentence.rstrip(".") + "." if sentence else ""


def list_shared_skills() -> int:
    print("Shared skills installed by --skills:\n")
    for skill_name in SHARED_SKILLS:
        summary = shared_skill_summary(skill_name)
        print(f"  {skill_name}")
        if summary:
            print(f"      {summary}")
    print(
        "\nInstall with, for example:\n"
        "  python scripts/adopt.py /path/to/repo --profile claude --skills"
    )
    return 0
