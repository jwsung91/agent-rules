"""Undoing an adoption.

Kept apart from the write path on purpose. Removal answers different
questions -- is this file ours, is it committed, what would be lost -- and
mixing it into the planner would put a delete branch inside every code path
that writes.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .applying import backup_path
from .constants import BACKUP_ROOT
from .gitignore import remove_agent_rules_block
from .gitio import find_repo_root, is_tracked
from .metadata import parse_metadata
from .planning import shared_skill_file_specs
from .source import required_files_for_profile, sync_base_path


@dataclass
class RemovalPlan:
    target_repo: Path
    git_root: Path | None
    paths: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)
    tracked: list[str] = field(default_factory=list)


def adoption_paths(target_repo: Path, profile: str, *, skills: bool) -> list[str]:
    """Every path an adoption of this profile created, present or not.

    `.agents/agent-rules/` is deliberately absent: a local copy is meant to be
    committed and shared, so dropping it is a separate decision from undoing
    the adoption. Backups are absent for the obvious reason.
    """
    paths: list[str] = []
    for name in required_files_for_profile(profile):
        paths.append(name)
        paths.append(sync_base_path(name))
    if skills:
        for _source, relative_path in shared_skill_file_specs(profile):
            paths.append(relative_path)
            paths.append(sync_base_path(relative_path))
    return paths


def build_removal_plan(
    target_repo: Path, profile: str, *, skills: bool, force: bool
) -> RemovalPlan:
    git_root = find_repo_root(target_repo)
    plan = RemovalPlan(target_repo=target_repo, git_root=git_root)

    for relative_path in adoption_paths(target_repo, profile, skills=skills):
        path = target_repo / relative_path
        if not path.exists():
            continue

        # An entrypoint without the metadata block was written by someone
        # else; the same rule the write path uses before touching a file.
        # Baselines and skill files carry no metadata, so they are only ever
        # reached through a path this helper generated.
        if relative_path in required_files_for_profile(profile):
            content = path.read_text(encoding="utf-8", errors="replace")
            if not parse_metadata(content):
                plan.foreign.append(relative_path)
                continue

        if git_root is not None and not force:
            try:
                root_relative = path.relative_to(git_root).as_posix()
            except ValueError:
                root_relative = relative_path
            if is_tracked(git_root, root_relative):
                plan.tracked.append(relative_path)
                continue

        plan.paths.append(relative_path)
    return plan


def report_removal_blockers(plan: RemovalPlan) -> int:
    if plan.foreign:
        print(
            "Refusing to remove a file this helper did not generate "
            "(no agent-rules metadata block):\n"
        )
        for relative_path in plan.foreign:
            print(f"- {relative_path}")
        print("\nDelete it yourself if that is what you want.")
        return 1
    if plan.tracked:
        print("Refusing to remove tracked files:\n")
        for relative_path in plan.tracked:
            print(f"- {relative_path}")
        print(
            "\nThese are committed, so removing them changes the repository "
            "for everyone. Re-run with --force to remove them anyway; they "
            "are backed up first, and Git still has the committed copies."
        )
        return 1
    return 0


def prune_empty_parents(target_repo: Path, relative_path: str) -> None:
    """Drop directories the removal emptied, up to (not including) the repo."""
    directory = (target_repo / relative_path).parent
    while directory != target_repo and directory.is_relative_to(target_repo):
        if any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


def apply_removal(plan: RemovalPlan, *, dry_run: bool) -> int:
    blocked = report_removal_blockers(plan)
    if blocked:
        return blocked
    if not plan.paths:
        print("Nothing to remove: no generated files found for this profile.")
        return 0

    if dry_run:
        for relative_path in plan.paths:
            print(f"Would remove: {plan.target_repo / relative_path}")
        print(
            f"\nWould back up {len(plan.paths)} file(s) under {BACKUP_ROOT}/ "
            "before removing them."
        )
    else:
        for relative_path in plan.paths:
            source = plan.target_repo / relative_path
            # Backed up before deletion, always. An entrypoint holds the
            # repository's own boundaries and validation commands, and with a
            # local-only adoption Git has no copy of them either.
            destination = backup_path(plan.target_repo, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            source.unlink()
            prune_empty_parents(plan.target_repo, relative_path)
            print(f"Removed: {source}")

    gitignore_root = plan.git_root or plan.target_repo
    removed_entries = remove_agent_rules_block(gitignore_root, dry_run=dry_run)

    print("\nWould remove:" if dry_run else "\nRemoved:")
    print(f"- {len(plan.paths)} generated file(s)")
    if removed_entries:
        print(f"- {removed_entries} .gitignore entr(ies)")
    print(
        "\nLeft alone: .agents/agent-rules/ (a local copy is meant to be "
        "committed) and anything without an agent-rules metadata block."
    )
    if not dry_run:
        # The ignore rule that hid it went with the block, so it shows up in
        # git status -- deliberately. It holds the only copy of the
        # repository's boundaries and validation commands.
        backup_root = plan.target_repo / BACKUP_ROOT
        print(f"\nBackup kept at: {backup_root}")
        print("It is untracked now. Delete it once you are sure:")
        print(f"  rm -rf {backup_root}")
    return 0


__all__ = [
    "RemovalPlan",
    "adoption_paths",
    "apply_removal",
    "build_removal_plan",
    "prune_empty_parents",
    "report_removal_blockers",
]
