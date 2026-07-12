#!/usr/bin/env python3
"""Build a --batch repo list (repos.toml or repos.txt) from explicit repo paths.

repos.toml/.txt are user-maintained files (see docs/scripted-adoption.md);
this just saves typing them out by hand when you already know which
repositories to include.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adopt import infer_profile_from_existing, resolve_target_repo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a repos.toml/.txt batch list from explicitly given repository paths."
    )
    parser.add_argument("repos", nargs="+", metavar="REPO", help="Repository paths to include.")
    parser.add_argument(
        "--output",
        required=True,
        metavar="FILE",
        help="Output file path. Format is chosen by extension: .toml or .txt.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    return parser.parse_args()


def render_toml(entries: list[tuple[Path, str | None]]) -> str:
    blocks = []
    for path, profile in entries:
        lines = ["[[repos]]", f'path = "{path.as_posix()}"']
        if profile:
            lines.append(f'profile = "{profile}"')
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_text(entries: list[tuple[Path, str | None]]) -> str:
    return "\n".join(path.as_posix() for path, _ in entries) + "\n"


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    if output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing file: {output}\nUse --force to overwrite.")

    suffix = output.suffix.lower()
    if suffix not in {".toml", ".txt"}:
        raise SystemExit(f"Unsupported output extension: {output.suffix or '(none)'}. Use .toml or .txt.")

    entries: list[tuple[Path, str | None]] = []
    for repo_arg in args.repos:
        repo = resolve_target_repo(repo_arg)
        entries.append((repo, infer_profile_from_existing(repo)))

    content = render_toml(entries) if suffix == ".toml" else render_text(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")

    print(f"Wrote {len(entries)} repositor{'y' if len(entries) == 1 else 'ies'} to {output}")
    for repo, profile in entries:
        print(f"- {repo} (profile: {profile or 'unset'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
