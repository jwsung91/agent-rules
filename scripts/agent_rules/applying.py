"""Writing a plan to disk and reporting what happened."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .constants import BACKUP_ROOT, ENTRYPOINT_FILES, SYNC_BASE_ROOT
from .gitignore import add_to_gitignore, fail_on_ignored
from .gitio import check_generated_files_ignored
from .models import AdoptionPlan, FilePlan

# One stamp per process, so every file a single run backs up lands together.
_RUN_STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_path(target_repo: Path, relative_path: str) -> Path:
    """Where a file about to be overwritten is copied.

    One directory per run, so a --profile all --force keeps its three files
    together and repeated runs do not overwrite each other's copies.
    """
    return target_repo / BACKUP_ROOT / _RUN_STAMP / relative_path


def write_plan_file(
    target_repo: Path,
    plan: FilePlan,
    *,
    dry_run: bool,
    verbose: bool = False,
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
    if plan.action == "missing-managed-block":
        raise SystemExit(
            f"Refusing to update a generated file with no managed-block markers: {path}\n"
            "The markers are what separates this helper's content from yours. "
            "Without them a sync would either discard your edits or leave the "
            "old shared sections behind as duplicates.\n"
            "Re-run with --force to regenerate it from the templates. Your "
            "current file is copied under .agent-rules/backups/ first, so "
            "anything only that file has can be recovered."
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
        # The full text of every planned file runs to ~1,900 lines for
        # --profile all --skills, which is not a preview anyone can read.
        # Say what would happen by default; --verbose still shows the
        # content, which is how you confirm a merge kept a local edit.
        if verbose and plan.content is not None:
            print("-" * 72)
            print(plan.content.rstrip())
            print("-" * 72)
        elif plan.source is not None:
            print(f"Source: {plan.source}")
        return ("Updated" if existed else "Created", plan.path)

    if plan.action == "overwrite" and existed:
        # --force replaces the file wholesale, and nothing else in this
        # helper keeps a copy. A sync during a fleet rollout destroyed a
        # hand-edited section once; only an ad-hoc snapshot got it back.
        backup = backup_path(target_repo, plan.path)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        print(f"Backed up: {backup}")

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
            "missing-managed-block",
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
            # Skill files and sync baselines get the same local-only
            # treatment as entrypoints (see generated_local_paths above);
            # only genuinely different categories (e.g. .agents/ local
            # copies, which must stay trackable) fall into the else branch.
            is_locally_ignorable = Path(status.path).name in ENTRYPOINT_FILES or status.path.startswith(
                (".codex/skills/", ".claude/skills/", f"{SYNC_BASE_ROOT}/")
            )
            if is_locally_ignorable:
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
        bucket, path = write_plan_file(
            plan.target_repo, item, dry_run=args.dry_run, verbose=args.verbose
        )
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
    if (
        args.dry_run
        and not args.verbose
        and any(item.content is not None for item in plan.files)
    ):
        print("\nRe-run with --verbose to print the content of each planned file.")

    # Backups land beside the baselines and get the same local-only
    # treatment, so a --force run does not leave untracked copies behind.
    generated_local_paths.extend(
        backup_path(plan.target_repo, item.path)
        .relative_to(plan.target_repo)
        .as_posix()
        for item in plan.files
        if item.action == "overwrite" and (plan.target_repo / item.path).exists()
    )

    # Keyed on the planned files, not on what this run happened to write: an
    # idempotent --sync writes nothing, and a missing .gitignore entry still
    # needs repairing. add_to_gitignore() returns None when every entry is
    # already present, so this stays a no-op in the common case.
    gitignore_file: str | None = None
    if generated_local_paths and args.visibility == "local":
        gitignore_file = add_to_gitignore(
            git_root,
            generated_local_paths,
            dry_run=args.dry_run,
        )
        if gitignore_file and not args.dry_run:
            # .gitignore just changed on disk; the "Gitignore:" summary must
            # reflect the post-write state, not the ignore_statuses snapshot
            # taken before this repository had any .gitignore rule for these
            # paths.
            plan.ignore_statuses = check_generated_files_ignored(
                plan.target_repo, plan.git_root, plan.files
            )

    # .gitignore counts: a run that only migrated ignore entries still
    # changed the repository, and reporting it as "already current" would be
    # wrong.
    plan.written = created + updated + ([gitignore_file] if gitignore_file else [])
    print_summary(
        created,
        updated,
        skipped,
        plan,
        gitignore_file=gitignore_file,
        visibility=args.visibility,
    )
    return 0
