"""Turning templates and metadata into entrypoint file content."""

from __future__ import annotations

import argparse
import re
from dataclasses import replace
from pathlib import Path
from datetime import datetime

from .constants import (
    BOUNDARY_PLACEHOLDER,
    LOCAL_MARKER_LINE_RE,
    LOCAL_REGION_RE,
    ENTRYPOINT_FILES,
    ENTRYPOINT_SKILL_ROOTS,
    MANAGED_END,
    MANAGED_START,
    METADATA_RE,
    SHARED_SKILLS,
    SKILL_TRIGGER_PRIORITY_NOTE,
    SKILL_TRIGGER_RULES,
    VALIDATION_PLACEHOLDER,
)
from .metadata import render_metadata
from .models import DetectionResult, RenderContext, SourceStatus
from .source import read_template, required_files_for_profile


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


PRESERVED_PLACEHOLDERS = (
    ("boundaries", "{{REPOSITORY_SPECIFIC_BOUNDARIES}}"),
    ("validation_commands", "{{VALIDATION_COMMANDS}}"),
)
# Literal characters of template text used to locate a placeholder's expansion
# in an already-generated file. Long enough to be unambiguous, short enough to
# survive light local editing around the section.
PLACEHOLDER_ANCHOR = 40


def recover_placeholder(existing: str, template: str, placeholder: str) -> str | None:
    """Recover what `placeholder` expanded to in an already-generated file.

    Anchors are taken from the template itself -- the literal text on either
    side of the placeholder -- so no prose is hardcoded here and the recovery
    follows the template if it is edited. Returns None when the surrounding
    text cannot be found, in which case the caller keeps the freshly rendered
    value rather than guessing.
    """
    head, separator, tail = template.partition(placeholder)
    if not separator:
        return None
    lead, trail = head[-PLACEHOLDER_ANCHOR:], tail[:PLACEHOLDER_ANCHOR]
    if not lead or not trail:
        return None
    start = existing.find(lead)
    if start == -1:
        return None
    start += len(lead)
    end = existing.find(trail, start)
    if end == -1:
        return None
    return existing[start:end]


def strip_local_markers(text: str) -> str:
    """The same text without the region ownership markers."""
    return LOCAL_MARKER_LINE_RE.sub("", text)


def extract_local_regions(content: str) -> dict[str, str]:
    """Bodies of the repository-owned regions in a generated entrypoint.

    Keyed by region name, which is the RenderContext field the region fills.
    """
    return {
        match.group("name"): match.group("body")
        for match in LOCAL_REGION_RE.finditer(content)
    }


def with_preserved_sections(
    context: RenderContext,
    target_repo: Path,
    profile: str,
    args: argparse.Namespace,
) -> RenderContext:
    """Carry a repository's own boundaries and validation commands across a sync.

    Those two sections belong to the adopting repository, not to the shared
    source, but --sync re-renders the whole file and the 3-way merge then
    prefers the freshly rendered placeholder text over what the repository
    configured -- silently replacing real boundaries and validation commands
    with "Add project-specific rules here." Re-render the existing values
    instead, so the merge sees no change there.

    Values supplied on this run (--boundary/--validation) still win, and
    --force still regenerates from the templates: asking to overwrite is a
    different request.
    """
    primary = required_files_for_profile(profile)[0]
    path = target_repo / primary
    if not path.exists():
        return context
    existing = path.read_text(encoding="utf-8", errors="replace")
    template = read_template(f"target-{primary}")

    supplied = {"boundaries": bool(args.boundary), "validation_commands": bool(args.validation)}
    regions = extract_local_regions(existing)
    replacements: dict[str, str] = {}
    for field_name, placeholder in PRESERVED_PLACEHOLDERS:
        if supplied[field_name]:
            continue
        recovered = regions.get(field_name)
        if recovered is None:
            # Adopted before the ownership markers existed. Fall back to
            # locating the value by the template text around it, with the
            # markers stripped so the anchors match how that file was
            # actually generated. This sync writes the markers, after which
            # the marker path is used.
            recovered = recover_placeholder(
                existing, strip_local_markers(template), placeholder
            )
        if recovered is not None and recovered != getattr(context, field_name):
            replacements[field_name] = recovered
    return replace(context, **replacements) if replacements else context


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
    if len(set(SHARED_SKILLS)) > 1:
        lines.append(f"- {SKILL_TRIGGER_PRIORITY_NOTE}")
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
