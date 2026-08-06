"""Deciding what to write, before anything is written."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .constants import (
    CODEX_ONLY_SKILL_PATHS,
    ENTRYPOINT_FILES,
    MANAGED_START,
    PROFILE_SKILL_ROOTS,
    SHARED_SKILLS,
    TOOL_ENTRYPOINTS,
)
from .gitio import check_generated_files_ignored, find_repo_root, three_way_merge
from .metadata import parse_metadata, render_metadata, same_content
from .models import AdoptionPlan, DetectionResult, FilePlan, RenderContext
from .render import (
    build_render_context,
    dedupe,
    merge_agents_content,
    render_file_for_profile,
    shared_skills_section,
    update_agents_content,
    with_preserved_sections,
)
from .source import (
    get_source_status,
    profile_skill_support,
    required_files_for_profile,
    source_repo_root,
    sync_base_path,
)


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


def baseline_plan(
    target_repo: Path, relative_path: str, upstream: str
) -> FilePlan:
    path = sync_base_path(relative_path)
    target = target_repo / path
    if not target.exists():
        action = "create"
    elif same_content(target.read_text(encoding="utf-8", errors="replace"), upstream):
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
    return merged, "no-op" if same_content(merged, existing) else "merge"


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
    return content, ("no-op" if same_content(content, existing) else "update")


def file_action(target_repo: Path, relative_path: str, *, update: bool, force: bool) -> str:
    path = target_repo / relative_path
    if path.exists():
        if update:
            return "update"
        if force:
            return "overwrite"
        return "exists"
    return "create"


def baseline_content_for(
    baseline_existed: bool, rendered: str, written: str | None
) -> str:
    """What the next sync should treat as the shared source it merged from.

    With a baseline present the file was reconciled against the render, so the
    render is the new baseline. Without one the legacy refresh runs instead:
    it replaces the metadata and managed block and leaves everything else
    alone, so the file keeps content the render does not have -- most visibly
    the region ownership markers, which sit outside the managed block.

    Recording the render in that case would leave a baseline claiming markers
    the file does not contain, and the next 3-way merge would read their
    absence as a deliberate local deletion and preserve it forever. Record
    what was actually written, so the next sync sees the markers as an
    upstream addition and applies them.
    """
    if baseline_existed or written is None:
        return rendered
    return written


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
        baseline_existed = (target_repo / sync_base_path(relative_path)).exists()
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
                action = "no-op" if same_content(content, existing) else "merge"
            elif force:
                content = rendered
            else:
                content = None
            plans.append(FilePlan(path=relative_path, action=action, content=content))
            plans.append(
                baseline_plan(
                    target_repo,
                    relative_path,
                    baseline_content_for(baseline_existed, rendered, content),
                )
            )
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
            plans.append(
                baseline_plan(
                    target_repo,
                    relative_path,
                    baseline_content_for(baseline_existed, rendered, content),
                )
            )
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
        for destination_root in PROFILE_SKILL_ROOTS[profile]:
            for source in sorted(skill_root.rglob("*")):
                if source.is_file():
                    relative = source.relative_to(skill_root).as_posix()
                    if (
                        destination_root == ".claude/skills"
                        and relative in CODEX_ONLY_SKILL_PATHS
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

    if profile and args.skills:
        supported, unsupported = profile_skill_support(profile)
        if not supported:
            raise SystemExit(
                f"--skills has no effect for --profile {profile}: no shared-skill "
                "installation path exists for it yet. Remove --skills, or use "
                "--profile codex or --profile claude."
            )
        if unsupported:
            warnings.append(
                "WARN: shared skills are not supported for "
                f"{', '.join(unsupported)} ({profile} profile); it was generated "
                "without a Shared Skills section."
            )

    if profile:
        context = build_render_context(args, profile, source_status, detected)
        if args.sync:
            context = with_preserved_sections(context, target_repo, profile, args)
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
