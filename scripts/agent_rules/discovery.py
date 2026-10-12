"""Repository discovery shared by the batch-list CLI and deployment GUI."""

from __future__ import annotations

from pathlib import Path


def find_git_repos(
    root: Path,
    *,
    descend_past_repos: bool = False,
    max_depth: int | None = None,
    skip_hidden: bool = False,
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

    `skip_hidden` ignores dot-directories below `root` (tool state such as
    ~/.nvm or ~/.vim/bundle) when scanning a broad root like a home folder.
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
                p
                for p in directory.iterdir()
                if p.is_dir()
                and not p.is_symlink()
                and not (skip_hidden and p.name.startswith("."))
            )
        except (PermissionError, OSError):
            return
        for child in children:
            walk(child, depth + 1)

    walk(root, 0)
    return sorted(found, key=lambda p: p.as_posix())
