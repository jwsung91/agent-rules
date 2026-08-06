#!/usr/bin/env python3
"""Adopt agent-rules in a target repository.

The helper creates lightweight repository-local entrypoints by default. It can
also check/update existing adoption metadata and create a pinned local copy
under .agents/agent-rules/ when offline use is needed.

This file stays the entry point and the module's public surface: docs, adopted
repositories, and sibling scripts all refer to `scripts/adopt.py`. The
implementation lives in the `agent_rules` package beside it, re-exported here
so importing this module keeps reaching every name it used to expose.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The package sits next to this file. `python scripts/adopt.py` puts that
# directory on sys.path automatically, but importing this file by location
# (as tests do) does not, so add it before the re-exports below. Those
# imports cannot move to the top of the file for that reason -- hence the
# E402 suppressions.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from agent_rules.constants import (  # noqa: E402
    LOCAL_REGION_RE,
    DEFAULT_SHARED_URL,
    SOURCE_REF,
    VALID_PROFILES,
    PROFILE_FILES,
    ENTRYPOINT_FILES,
    VALID_VISIBILITIES,
    SHARED_SKILLS,
    PROFILE_SKILL_ROOTS,
    ENTRYPOINT_SKILL_ROOTS,
    SKILL_ROOTS,
    CODEX_ONLY_SKILL_PATHS,
    SKILL_TRIGGER_RULES,
    SKILL_TRIGGER_PRIORITY_NOTE,
    TOOL_ENTRYPOINTS,
    METADATA_RE,
    GENERATED_AT_RE,
    MANAGED_START,
    MANAGED_END,
    BOUNDARY_PLACEHOLDER,
    VALIDATION_PLACEHOLDER,
    GITIGNORE_AGENT_COMMENT,
    SYNC_BASE_ROOT,
)
from agent_rules.models import (  # noqa: E402
    RenderContext,
    SourceStatus,
    IgnoreStatus,
    DetectionResult,
    FilePlan,
    BatchEntry,
    AdoptionPlan,
)
from agent_rules.metadata import (  # noqa: E402
    render_metadata,
    parse_metadata,
    mask_generated_at,
    same_content,
)
from agent_rules.gitio import (  # noqa: E402
    run_command,
    find_repo_root,
    merge_base_is_ancestor,
    is_tracked,
    check_ignore_status,
    check_generated_files_ignored,
    three_way_merge,
)
from agent_rules.source import (  # noqa: E402
    adoption_is_current,
    resolve_target_repo,
    source_repo_root,
    template_dir,
    read_template,
    parse_profile,
    required_files_for_profile,
    profile_skill_support,
    local_source_head,
    remote_main_head,
    resolve_latest_status,
    latest_reference,
    target_commit_status,
    get_source_status,
    sync_base_path,
    infer_profile_from_existing,
    skills_installed,
)
from agent_rules.render import (  # noqa: E402
    format_boundaries,
    format_validation_commands,
    dedupe,
    render_template,
    build_render_context,
    shared_skills_section,
    with_preserved_sections,
    recover_placeholder,
    extract_local_regions,
    strip_local_markers,
    render_file_for_profile,
    extract_managed_block,
    replace_metadata_block,
    replace_managed_block,
    update_agents_content,
    section_present,
    merge_agents_content,
)
from agent_rules.gitignore import (  # noqa: E402
    gitignore_patterns,
    is_legacy_gitignore_entry,
    strip_legacy_gitignore_entries,
    add_to_gitignore,
    fail_on_ignored,
)
from agent_rules.planning import (  # noqa: E402
    baseline_content_for,
    detect_repository_type,
    baseline_plan,
    plan_three_way_update,
    plan_generated_update,
    file_action,
    build_entrypoint_plans,
    local_copy_file_specs,
    shared_skill_file_specs,
    build_shared_skill_plans,
    build_local_copy_plans,
    read_local_copy_commit,
    build_plan,
)
from agent_rules.checking import (  # noqa: E402
    latest_status_for_target,
    extract_validation_commands,
    append_check,
    check_adoption,
    shared_skill_summary,
    list_shared_skills,
)
from agent_rules.applying import (  # noqa: E402
    write_plan_file,
    validate_plan_before_write,
    print_summary,
    apply_plan,
)
from agent_rules.batch import (  # noqa: E402
    parse_batch_file,
    run_batch,
)
from agent_rules.cli import (  # noqa: E402
    parse_args,
    print_profile_help,
    validate_args,
    main,
)
from agent_rules.batch import tomllib  # noqa: E402

# Re-exported for `import adopt` consumers; see the module docstring.
__all__ = [
    "baseline_content_for",
    "extract_local_regions",
    "strip_local_markers",
    "LOCAL_REGION_RE",
    "with_preserved_sections",
    "recover_placeholder",
    "adoption_is_current",
    "AdoptionPlan",
    "BOUNDARY_PLACEHOLDER",
    "BatchEntry",
    "CODEX_ONLY_SKILL_PATHS",
    "DEFAULT_SHARED_URL",
    "DetectionResult",
    "ENTRYPOINT_FILES",
    "ENTRYPOINT_SKILL_ROOTS",
    "FilePlan",
    "GENERATED_AT_RE",
    "GITIGNORE_AGENT_COMMENT",
    "IgnoreStatus",
    "MANAGED_END",
    "MANAGED_START",
    "METADATA_RE",
    "PROFILE_FILES",
    "PROFILE_SKILL_ROOTS",
    "RenderContext",
    "SHARED_SKILLS",
    "SKILL_ROOTS",
    "SKILL_TRIGGER_PRIORITY_NOTE",
    "SKILL_TRIGGER_RULES",
    "SOURCE_REF",
    "SYNC_BASE_ROOT",
    "SourceStatus",
    "TOOL_ENTRYPOINTS",
    "VALIDATION_PLACEHOLDER",
    "VALID_PROFILES",
    "VALID_VISIBILITIES",
    "add_to_gitignore",
    "append_check",
    "apply_plan",
    "baseline_plan",
    "build_entrypoint_plans",
    "build_local_copy_plans",
    "build_plan",
    "build_render_context",
    "build_shared_skill_plans",
    "check_adoption",
    "check_generated_files_ignored",
    "check_ignore_status",
    "dedupe",
    "detect_repository_type",
    "extract_managed_block",
    "extract_validation_commands",
    "fail_on_ignored",
    "file_action",
    "find_repo_root",
    "format_boundaries",
    "format_validation_commands",
    "get_source_status",
    "gitignore_patterns",
    "infer_profile_from_existing",
    "is_legacy_gitignore_entry",
    "is_tracked",
    "latest_reference",
    "latest_status_for_target",
    "list_shared_skills",
    "local_copy_file_specs",
    "local_source_head",
    "main",
    "mask_generated_at",
    "merge_agents_content",
    "merge_base_is_ancestor",
    "parse_args",
    "parse_batch_file",
    "parse_metadata",
    "parse_profile",
    "plan_generated_update",
    "plan_three_way_update",
    "print_profile_help",
    "print_summary",
    "profile_skill_support",
    "read_local_copy_commit",
    "read_template",
    "remote_main_head",
    "render_file_for_profile",
    "render_metadata",
    "render_template",
    "replace_managed_block",
    "replace_metadata_block",
    "required_files_for_profile",
    "resolve_latest_status",
    "resolve_target_repo",
    "run_batch",
    "run_command",
    "same_content",
    "section_present",
    "shared_skill_file_specs",
    "shared_skill_summary",
    "shared_skills_section",
    "skills_installed",
    "source_repo_root",
    "strip_legacy_gitignore_entries",
    "sync_base_path",
    "target_commit_status",
    "template_dir",
    "three_way_merge",
    "tomllib",
    "update_agents_content",
    "validate_args",
    "validate_plan_before_write",
    "write_plan_file",
]


if __name__ == "__main__":
    raise SystemExit(main())
