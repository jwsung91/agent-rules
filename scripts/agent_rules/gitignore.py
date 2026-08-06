"""Keeping generated files out of the target repository's index."""

from __future__ import annotations

from pathlib import Path

from .constants import (
    BACKUP_ROOT,
    ENTRYPOINT_FILES,
    GITIGNORE_AGENT_COMMENT,
    SHARED_SKILLS,
    SKILL_ROOTS,
    SYNC_BASE_ROOT,
)
from .models import IgnoreStatus
from .render import dedupe

# Directories this helper creates and owns outright, so one pattern each
# covers everything they will ever contain.
OWNED_DIRECTORY_ROOTS = (SYNC_BASE_ROOT, BACKUP_ROOT)


def gitignore_patterns(paths: list[str]) -> list[str]:
    """Collapse generated file paths into the smallest stable ignore patterns.

    One entry per generated file made .gitignore grow with the number of
    skills times the number of agents times the files inside each skill (30
    lines for `--profile all --skills`), and grow again on every upstream
    addition. Each installed skill and the sync-baseline root are whole
    directories this helper owns, so one directory pattern each covers every
    file they will ever contain.

    Skill directories are named individually rather than ignoring
    `.codex/skills/` or `.claude/skills/` wholesale: those roots also hold
    skills the repository wrote itself, which are none of this helper's
    business.
    """
    patterns: list[str] = []
    for path in paths:
        owned = next(
            (
                root
                for root in OWNED_DIRECTORY_ROOTS
                if path.startswith(f"{root}/")
            ),
            None,
        )
        if owned is not None:
            patterns.append(f"{owned}/")
            continue
        for root in SKILL_ROOTS:
            prefix = f"{root}/"
            if path.startswith(prefix):
                skill_name = path[len(prefix) :].split("/", 1)[0]
                patterns.append(f"{root}/{skill_name}/")
                break
        else:
            # Entrypoints stay one line each; they are single files.
            patterns.append(path)
    return dedupe(patterns)


def is_unrooted_entrypoint_entry(line: str) -> bool:
    """True for an entrypoint listed without the leading slash.

    Earlier versions wrote a bare `AGENTS.md`, which gitignore matches at any
    depth -- including `.agents/agent-rules/AGENTS.md`, the local copy that is
    meant to be committed. Rewriting these to `/AGENTS.md` scopes them to the
    repository root, which is all they were ever meant to cover.
    """
    entry = line.strip()
    return entry in ENTRYPOINT_FILES


def is_legacy_gitignore_entry(line: str) -> bool:
    """True for a per-file entry written by an earlier version of this helper.

    Only paths *inside* a directory this helper owns count, never the
    directory pattern itself, so re-running does not strip what it just
    wrote. A repository's own entry (for a skill this helper does not
    install, say) never matches and is left alone.
    """
    entry = line.strip().lstrip("/")
    if not entry or entry.startswith("#"):
        return False
    if is_unrooted_entrypoint_entry(line):
        # Rewritten in place rather than dropped; see add_to_gitignore.
        return False
    owned_roots = [f"{SYNC_BASE_ROOT}/", f"{BACKUP_ROOT}/"]
    owned_roots += [
        f"{root}/{skill_name}/" for root in SKILL_ROOTS for skill_name in SHARED_SKILLS
    ]
    return any(
        entry.startswith(root) and entry != root for root in owned_roots
    )


def strip_legacy_gitignore_entries(lines: list[str]) -> tuple[list[str], int, int | None]:
    """Drop per-file entries and reroot bare entrypoint names.

    Returns the surviving lines, how many entries were removed, and the index
    in those lines where new patterns belong — the end of the first surviving
    agent-rules block, or None when no block survived. New patterns go into
    the existing block rather than a second one, and the block keeps its
    position: .gitignore resolves later patterns last, so moving it could
    change how it interacts with rules a repository wrote after it.
    """
    kept: list[str] = []
    removed = 0
    rerooted = 0
    insert_at: int | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() != GITIGNORE_AGENT_COMMENT:
            if is_legacy_gitignore_entry(line):
                removed += 1
            elif is_unrooted_entrypoint_entry(line):
                kept.append(f"/{line.strip()}")
                rerooted += 1
            else:
                kept.append(line)
            index += 1
            continue

        # A block is this comment plus the consecutive non-blank lines under
        # it. Kept entries stay under their comment; a block left with
        # nothing goes away entirely, along with one trailing blank line so
        # removing it does not leave a widening gap.
        block_end = index + 1
        while block_end < len(lines) and lines[block_end].strip():
            block_end += 1
        block = lines[index + 1 : block_end]
        block_kept = [item for item in block if not is_legacy_gitignore_entry(item)]
        removed += len(block) - len(block_kept)
        rerooted += sum(1 for item in block_kept if is_unrooted_entrypoint_entry(item))
        block_kept = [
            f"/{item.strip()}" if is_unrooted_entrypoint_entry(item) else item
            for item in block_kept
        ]
        if block_kept:
            kept.append(line)
            kept.extend(block_kept)
            if insert_at is None:
                insert_at = len(kept)
            index = block_end
        else:
            index = block_end
            if index < len(lines) and not lines[index].strip():
                index += 1
    return kept, removed + rerooted, insert_at


def add_to_gitignore(git_root: Path, paths: list[str], *, dry_run: bool) -> str | None:
    """Keep generated agent files out of Git, as few patterns as possible.

    Also migrates a .gitignore written by an earlier version, which listed
    every generated file individually. Returns the relative .gitignore path
    if modified, else None.
    """
    gitignore_path = git_root / ".gitignore"
    content = (
        gitignore_path.read_text(encoding="utf-8", errors="replace")
        if gitignore_path.exists()
        else ""
    )
    kept_lines, removed, insert_at = strip_legacy_gitignore_entries(content.splitlines())
    existing_normalized = {line.strip().lstrip("/") for line in kept_lines}
    to_add = [
        pattern
        for pattern in gitignore_patterns(paths)
        if pattern not in existing_normalized
    ]
    if not to_add and not removed:
        return None
    if dry_run:
        if to_add:
            print(f"Would add to .gitignore: {', '.join(to_add)}")
        if removed:
            print(
                f"Would replace {removed} per-file agent-rules entries in "
                ".gitignore with directory patterns"
            )
        return ".gitignore"

    if to_add:
        # A bare pattern with no slash (e.g. "AGENTS.md") matches at any depth
        # in gitignore semantics, not just the repo root — without the leading
        # "/" it would also match .agents/agent-rules/AGENTS.md from
        # --local-copy, silently excluding a file that's meant to be tracked.
        new_lines = [f"/{pattern}" for pattern in to_add]
        if insert_at is None:
            if kept_lines:
                kept_lines.append("")
            kept_lines.append(GITIGNORE_AGENT_COMMENT)
            kept_lines.extend(new_lines)
        else:
            kept_lines[insert_at:insert_at] = new_lines
    updated = "\n".join(kept_lines)
    if updated:
        updated += "\n"
    gitignore_path.write_text(updated, encoding="utf-8")
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
