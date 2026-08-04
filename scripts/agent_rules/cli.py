"""Argument parsing and the top-level entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .applying import apply_plan
from .batch import run_batch
from .checking import check_adoption, list_shared_skills
from .constants import DEFAULT_SHARED_URL, VALID_PROFILES, VALID_VISIBILITIES
from .planning import build_plan
from .source import (
    infer_profile_from_existing,
    parse_profile,
    resolve_target_repo,
    skills_installed,
)


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
        "--list-skills",
        action="store_true",
        help="List the shared skills that --skills installs, then exit.",
    )
    parser.add_argument(
        "--batch",
        metavar="FILE",
        help="Apply to multiple repositories listed in a .toml or .txt file.",
    )
    return parser.parse_args()


def print_profile_help() -> None:
    print("No agent profile selected.\n")
    print("Choose one:")
    print("- --profile codex   : create AGENTS.md only")
    print("- --profile claude  : create CLAUDE.md only")
    print("- --profile gemini  : create GEMINI.md only")
    print("- --profile all     : create AGENTS.md + CLAUDE.md + GEMINI.md")


def validate_args(args: argparse.Namespace, profile: str | None) -> None:
    if args.sync and args.force:
        raise SystemExit("Use either --sync or --force, not both.")
    if args.batch:
        return
    write_requested = not args.check
    if write_requested and not profile:
        print_profile_help()
        raise SystemExit(2)


def main() -> int:
    # Some Windows console code pages (e.g. cp949) can't encode every
    # character this script prints (box-drawing separators, em dashes).
    # Fall back instead of crashing mid-run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    args = parse_args()

    if args.list_skills:
        return list_shared_skills()

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
    # skills were installed by an earlier --skills run. --check needs the same
    # inference for a different reason: without it a health check silently
    # skips every skill assertion, so a deleted skill file reports clean.
    if (
        (args.sync or args.check)
        and not args.skills
        and profile
        and skills_installed(target_repo, profile)
    ):
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
