#!/usr/bin/env python3
"""Build a --batch repo list (repos.toml or repos.txt) by scanning a root folder.

repos.toml/.txt are user-maintained files (see docs/scripted-adoption.md);
this just saves typing them out by hand when many repos already live under
one parent folder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adopt import infer_profile_from_existing, resolve_target_repo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a repos.toml/.txt batch list by scanning a root folder for Git repositories."
    )
    parser.add_argument("root", metavar="ROOT", help="Folder to scan recursively for Git repositories.")
    parser.add_argument(
        "--output",
        required=True,
        metavar="FILE",
        help="Output file path. Format is chosen by extension: .toml or .txt.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    parser.add_argument(
        "--adopted-only",
        action="store_true",
        help="List only repositories that already carry an agent-rules metadata block.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        metavar="N",
        help="With --adopted-only, how many directory levels to search. Default: 3.",
    )
    return parser.parse_args()


def find_git_repos(
    root: Path, *, descend_past_repos: bool = False, max_depth: int | None = None
) -> list[Path]:
    """Recursively find Git repository roots under `root`.

    By default a directory with a .git entry ends that branch of the search,
    so submodules and vendored repos nested inside a found repo aren't picked
    up as separate entries.

    `descend_past_repos` keeps going instead, which is what --adopted-only
    needs: a repository can sit inside another one -- a workspace repo holding
    per-component repos, say -- and stopping at the outer one hides every
    adopted repository under it. Walking everything is expensive (37k
    directories under a real workspace root, versus 2k at depth 3), so that
    search is bounded by `max_depth`.
    """
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if (directory / ".git").exists():
            found.append(directory)
            if not descend_past_repos:
                return
        if max_depth is not None and depth >= max_depth:
            return
        try:
            children = sorted(
                p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
            )
        except (PermissionError, OSError):
            return
        for child in children:
            walk(child, depth + 1)

    walk(root, 0)
    return sorted(found, key=lambda p: p.as_posix())


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

    root = resolve_target_repo(args.root)
    repos = find_git_repos(
        root,
        descend_past_repos=args.adopted_only,
        max_depth=args.max_depth if args.adopted_only else None,
    )
    if not repos:
        raise SystemExit(f"No Git repositories found under: {root}")

    entries = [(repo, infer_profile_from_existing(repo)) for repo in repos]
    if args.adopted_only:
        # An inferred profile means an entrypoint carrying agent-rules
        # metadata, which is what "already adopted" means everywhere else in
        # this helper. Answering "which repositories have adopted this?"
        # otherwise takes a hand-rolled find | grep.
        entries = [(repo, profile) for repo, profile in entries if profile]
        if not entries:
            raise SystemExit(f"No adopted repositories found under: {root}")

    content = render_toml(entries) if suffix == ".toml" else render_text(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")

    print(f"Found {len(entries)} repositor{'y' if len(entries) == 1 else 'ies'} under {root}")
    for repo, profile in entries:
        print(f"- {repo} (profile: {profile or 'unset'})")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
