"""Subprocess boundary: every git invocation goes through here."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .models import FilePlan, IgnoreStatus


def run_command(command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def find_repo_root(path: Path) -> Path | None:
    code, stdout, _ = run_command(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    return Path(stdout).resolve() if code == 0 and stdout else None


def merge_base_is_ancestor(repo: Path, ancestor: str, descendant: str) -> str:
    code, _, stderr = run_command(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant]
    )
    if code == 0:
        return "yes"
    if code == 1:
        return "no"
    return f"unknown:{stderr or 'git merge-base failed'}"


def is_tracked(repo: Path, relative_path: str) -> bool:
    code, _, _ = run_command(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", relative_path]
    )
    return code == 0


def check_ignore_status(repo: Path, relative_path: str) -> IgnoreStatus:
    tracked = is_tracked(repo, relative_path)
    code, stdout, stderr = run_command(
        ["git", "-C", str(repo), "check-ignore", "-v", "--", relative_path]
    )
    if code == 0 and stdout:
        # Format: "<source>:<linenum>:<pattern>\t<pathname>"
        # A negation pattern (!foo) as the last match means the file is un-ignored.
        tab_idx = stdout.find("\t")
        rule_part = stdout[:tab_idx] if tab_idx != -1 else stdout
        pattern = rule_part.rsplit(":", 1)[-1].strip() if ":" in rule_part else ""
        if pattern.startswith("!"):
            return IgnoreStatus(path=relative_path, tracked=tracked, ignored=False)
        return IgnoreStatus(
            path=relative_path,
            tracked=tracked,
            ignored=True,
            matched_rule=stdout,
        )
    if code not in (0, 1):
        return IgnoreStatus(
            path=relative_path,
            tracked=tracked,
            ignored=False,
            warning=stderr or "git check-ignore failed",
        )
    return IgnoreStatus(path=relative_path, tracked=tracked, ignored=False)


def check_generated_files_ignored(
    target_repo: Path,
    git_root: Path | None,
    files: list[FilePlan],
) -> list[IgnoreStatus]:
    paths = [item.path for item in files]
    if git_root is None:
        return [
            IgnoreStatus(
                path=path,
                tracked=False,
                ignored=False,
                warning="target path is not inside a Git repository",
            )
            for path in paths
        ]

    statuses: list[IgnoreStatus] = []
    for path in paths:
        absolute_path = target_repo / path
        try:
            root_relative = absolute_path.relative_to(git_root).as_posix()
        except ValueError:
            statuses.append(
                IgnoreStatus(
                    path=path,
                    tracked=False,
                    ignored=False,
                    warning=f"{absolute_path} is outside git root {git_root}",
                )
            )
            continue
        statuses.append(check_ignore_status(git_root, root_relative))
    return statuses


def three_way_merge(local: str, base: str, upstream: str) -> tuple[str, bool]:
    """Merge text with Git's deterministic merge-file implementation."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        local_path = root / "local"
        base_path = root / "base"
        upstream_path = root / "upstream"
        local_path.write_text(local, encoding="utf-8")
        base_path.write_text(base, encoding="utf-8")
        upstream_path.write_text(upstream, encoding="utf-8")
        result = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "-L",
                "local",
                "-L",
                "base",
                "-L",
                "upstream",
                str(local_path),
                str(base_path),
                str(upstream_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode not in (0, 1):
            raise SystemExit(
                f"git merge-file failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout, result.returncode == 1
