#!/usr/bin/env python3
"""Adopt agent-rules in a target repository.

This script creates a lightweight repository-local AGENTS.md and optional
tool-specific entrypoints that point back to the shared agent-rules repository.
It intentionally avoids copying the full rules directory by default.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_SHARED_URL = "https://github.com/jwsung91/agent-rules"


@dataclass(frozen=True)
class RenderContext:
    shared_rules_url: str
    boundaries: str
    validation_commands: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or check lightweight agent-rules adoption files in a target repository."
        )
    )
    parser.add_argument(
        "target_repo",
        nargs="?",
        default=".",
        help="Path to the target repository root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--entrypoints",
        default="",
        help=(
            "Comma-separated optional entrypoints to create. "
            "Supported values: claude, gemini, all. Default: none."
        ),
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing target files.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create timestamped .bak files before overwriting existing files.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether a target repository appears to have adopted agent-rules.",
    )
    return parser.parse_args()


def resolve_target_repo(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Target path does not exist: {path}")
    if not path.is_dir():
        raise SystemExit(f"Target path is not a directory: {path}")
    return path


def find_repo_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def template_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "templates"


def read_template(name: str) -> str:
    path = template_dir() / name
    if not path.exists():
        raise SystemExit(f"Template file not found: {path}")
    return path.read_text(encoding="utf-8")


def format_boundaries(items: list[str]) -> str:
    if items:
        return "\n".join(f"- {item}" for item in items)

    return (
        "Add project-specific rules here.\n\n"
        "Examples:\n\n"
        "- public API compatibility expectations\n"
        "- benchmark or performance data boundaries\n"
        "- packaging impact expectations\n"
        "- supported language or build conventions\n"
        "- documentation update expectations"
    )


def format_validation_commands(commands: list[str]) -> str:
    if not commands:
        commands = [
            "git diff --check",
            "# Add project-specific build/test/lint commands here.",
        ]

    return "```bash\n" + "\n".join(commands) + "\n```"


def render(content: str, context: RenderContext) -> str:
    replacements = {
        "{{SHARED_RULES_URL}}": context.shared_rules_url,
        "{{REPOSITORY_SPECIFIC_BOUNDARIES}}": context.boundaries,
        "{{VALIDATION_COMMANDS}}": context.validation_commands,
    }

    rendered = content
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def parse_entrypoints(value: str) -> set[str]:
    if not value:
        return set()

    raw_items = [item.strip().lower() for item in value.split(",") if item.strip()]
    if "all" in raw_items:
        return {"claude", "gemini"}

    supported = {"claude", "gemini"}
    unknown = sorted(set(raw_items) - supported)
    if unknown:
        raise SystemExit(
            "Unsupported entrypoint(s): "
            + ", ".join(unknown)
            + ". Supported values: claude, gemini, all."
        )

    return set(raw_items)


def backup_existing_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def write_file(path: Path, content: str, *, force: bool, backup: bool, dry_run: bool) -> None:
    existed = path.exists()
    if existed and not force:
        raise SystemExit(
            f"Refusing to overwrite existing file: {path}\n"
            "Use --force to overwrite, and optionally --backup to save a copy first."
        )

    if dry_run:
        action = "Would update" if existed else "Would create"
        print(f"{action}: {path}")
        print("-" * 72)
        print(content.rstrip())
        print("-" * 72)
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    if existed and backup:
        backup_path = backup_existing_file(path)
        print(f"Backed up existing file: {backup_path}")

    path.write_text(content, encoding="utf-8")
    print(f"{'Updated' if existed else 'Created'}: {path}")


def check_file_contains(path: Path, required: list[str]) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, ["file is missing"]

    content = path.read_text(encoding="utf-8", errors="replace")
    missing = [text for text in required if text not in content]
    return not missing, missing


def check_adoption(target_repo: Path, shared_url: str) -> int:
    checks: list[tuple[str, bool, list[str]]] = []

    agents_ok, agents_missing = check_file_contains(
        target_repo / "AGENTS.md",
        [
            shared_url,
            "Agent Usage Model",
            "Core Rules",
            "Repository-specific Boundaries",
            "Validation",
            "Final Report",
        ],
    )
    checks.append(("AGENTS.md", agents_ok, agents_missing))

    for name in ("CLAUDE.md", "GEMINI.md"):
        path = target_repo / name
        if path.exists():
            ok, missing = check_file_contains(path, ["AGENTS.md"])
            checks.append((name, ok, missing))

    all_ok = True
    for name, ok, missing in checks:
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}")
        if missing:
            for item in missing:
                print(f"  - missing: {item}")
        all_ok = all_ok and ok

    if not all_ok:
        print("\nAdoption check failed. Review the missing items above.")
        return 1

    print("\nAdoption check passed.")
    return 0


def main() -> int:
    args = parse_args()
    target_repo = resolve_target_repo(args.target_repo)

    git_root = find_repo_root(target_repo)
    if git_root is None:
        print(
            f"Warning: target path does not appear to be inside a Git repository: {target_repo}",
            file=sys.stderr,
        )
    elif git_root != target_repo:
        print(
            f"Warning: target path is inside a Git repository but not the root.\n"
            f"  target: {target_repo}\n"
            f"  root:   {git_root}",
            file=sys.stderr,
        )

    if args.check:
        return check_adoption(target_repo, args.shared_url)

    entrypoints = parse_entrypoints(args.entrypoints)
    context = RenderContext(
        shared_rules_url=args.shared_url,
        boundaries=format_boundaries(args.boundary),
        validation_commands=format_validation_commands(args.validation),
    )

    files: dict[str, str] = {
        "AGENTS.md": render(read_template("target-AGENTS.md"), context)
    }

    if "claude" in entrypoints:
        files["CLAUDE.md"] = render(read_template("target-CLAUDE.md"), context)
    if "gemini" in entrypoints:
        files["GEMINI.md"] = render(read_template("target-GEMINI.md"), context)

    for relative_path, content in files.items():
        write_file(
            target_repo / relative_path,
            content,
            force=args.force,
            backup=args.backup,
            dry_run=args.dry_run,
        )

    print("\nNext steps:")
    print("1. Review repository-specific boundaries in AGENTS.md.")
    print("2. Add project-specific validation commands if needed.")
    print("3. Run: git diff --check")
    print('4. Commit with: docs(agent): adopt shared agent rules')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
