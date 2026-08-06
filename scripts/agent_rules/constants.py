"""Shared configuration: profiles, skills, markers, and patterns.

Values here are read by every other module. Tests that override one (for
example SHARED_SKILLS) must patch it on the module that *uses* it, not here:
a `from .constants import NAME` binding is resolved at import time.
"""

from __future__ import annotations

import re

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
SHARED_SKILLS = (
    "investigate-bug",
    "review-change",
    "validate-change",
    "prepare-commit",
)
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
# Every root any profile installs skills into, in a stable order. Derived
# rather than restated so a new agent's root only has to be added above.
SKILL_ROOTS = tuple(
    dict.fromkeys(root for roots in PROFILE_SKILL_ROOTS.values() for root in roots)
)
# Paths that carry Codex-specific metadata and must not leak into another
# agent's install, even though the rest of each skill is a shared contract.
# This convention applies to every shared skill without per-skill registration.
CODEX_ONLY_SKILL_PATHS = ("agents/openai.yaml",)
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
        "the unrelated work as a separate request. Do not include unrelated "
        "work in the bug-fix plan, Changes, or fix approach; mention it only "
        "under Not Included or Follow-up as a separate request."
    ),
    "review-change": (
        "When asked to review code, documentation, a diff, working tree, commit, "
        "branch, patch, pull request, or completed implementation, invoke the "
        "`review-change` skill before reporting findings. Stay in Review Mode "
        "and do not modify files unless the user separately authorizes changes. "
        "If the requested review target cannot be inspected, report the review "
        "as blocked; never substitute a different accessible branch, pull request, "
        "commit, repository, or remote target."
    ),
    "validate-change": (
        "When asked to validate, test, verify, check, or perform pre-commit "
        "verification of an existing change, invoke the `validate-change` skill "
        "before running checks. Keep validation focused and non-mutating, record "
        "the initial worktree state, report exact commands and outcomes, and "
        "identify any validation-created changes without deleting or reverting "
        "them unless separately authorized."
    ),
    "prepare-commit": (
        "When asked to commit, prepare or stage a commit, or write a commit "
        "message for the current changes, invoke the `prepare-commit` skill "
        "before committing. Review the diff, commit only the requested logical "
        "change, run lightweight pre-commit checks including `git diff --check`, "
        "and write a Conventional Commits message. Do not amend or rewrite "
        "history, reformat code, or include unrelated changes unless separately "
        "authorized."
    ),
}
# Shared skill trigger rules can overlap (e.g. "review and test this bug fix");
# without explicit priority an agent could substitute validation for review or
# diagnosis, or mix report structures. The tiebreak remains skill-specific
# judgment rather than a generic priority mechanism.
SKILL_TRIGGER_PRIORITY_NOTE = (
    "When a request could match more than one shared skill's trigger (for "
    "example, reviewing a pull request that fixes a bug), prioritize "
    "`review-change` if the primary ask is judging the quality of an "
    "existing change, diff, or pull request; use `investigate-bug` if the "
    "primary ask is reproducing or root-causing a defect that has no fix "
    "yet; use `validate-change` if the primary ask is executing checks and "
    "reporting validation evidence for an existing change; use "
    "`prepare-commit` if the primary ask is composing a commit for the "
    "current changes. Report defects found while reviewing within "
    "`review-change`'s structure unless the user separately asks for a fix. "
    "Validation may support either workflow without replacing its primary "
    "purpose, and prepare-commit's lightweight pre-commit checks do not "
    "replace a full `validate-change` or `review-change` pass."
)
TOOL_ENTRYPOINTS = {"CLAUDE.md", "GEMINI.md"}
METADATA_RE = re.compile(r"<!--\s*agent-rules:\s*(.*?)-->", re.DOTALL)
GENERATED_AT_RE = re.compile(r"^generated_at=.*$", re.MULTILINE)
MANAGED_START = "<!-- agent-rules-managed:start -->"
MANAGED_END = "<!-- agent-rules-managed:end -->"
BOUNDARY_PLACEHOLDER = "Add project-specific rules here."
VALIDATION_PLACEHOLDER = "# Add project-specific build/test/lint commands here."
GITIGNORE_AGENT_COMMENT = "# agent-rules (local only)"
SYNC_BASE_ROOT = ".agent-rules/bases"
# Copies of files --force is about to replace. Local-only, like the baselines.
BACKUP_ROOT = ".agent-rules/backups"


# Regions of a generated entrypoint that belong to the adopting repository.
# --sync refreshes everything else from the shared source and never these.
#
# Marking ownership in the file is what makes that guarantee structural. The
# alternative considered -- "only regenerate the managed block" -- does not
# work here: shared content lives outside that block too (the Validation
# guidance and the whole Final Report section), and it has been revised since
# repositories started adopting, so freezing it would strand them.
#
# The region name is the RenderContext field it fills.
LOCAL_REGION_RE = re.compile(
    r"<!--\s*agent-rules-local:(?P<name>[a-z_]+):start\s*-->\n"
    r"(?P<body>.*?)"
    r"\n<!--\s*agent-rules-local:(?P=name):end\s*-->",
    re.DOTALL,
)
LOCAL_MARKER_LINE_RE = re.compile(
    r"^<!--\s*agent-rules-local:[a-z_]+:(?:start|end)\s*-->\n", re.MULTILINE
)
