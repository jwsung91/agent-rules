"""Applying one operation across many repositories."""

from __future__ import annotations

import argparse
from pathlib import Path

from .applying import apply_plan
from .checking import check_adoption
from .models import BatchEntry
from .planning import build_plan
from .source import (
    infer_profile_from_existing,
    parse_profile,
    resolve_target_repo,
    skills_installed,
)

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]


def _read_batch_file_text(batch_file: Path) -> str:
    try:
        return batch_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"Batch file is not valid UTF-8: {batch_file}\n"
            f"({exc}). Re-save it as UTF-8 (e.g. from Notepad's 'Save As' encoding option)."
        ) from exc


def parse_batch_file(batch_file: Path) -> list[BatchEntry]:
    if batch_file.suffix == ".toml":
        return _parse_toml_batch(batch_file)
    return _parse_text_batch(batch_file)


def _parse_toml_batch(batch_file: Path) -> list[BatchEntry]:
    if tomllib is None:
        raise SystemExit("TOML batch files require Python 3.11+.")
    data = tomllib.loads(_read_batch_file_text(batch_file))
    repos = data.get("repos", [])
    if not isinstance(repos, list):
        raise SystemExit("TOML batch file must contain a [[repos]] array.")
    entries: list[BatchEntry] = []
    for item in repos:
        if not isinstance(item, dict) or "path" not in item:
            raise SystemExit(f"Each [[repos]] entry must have a 'path' field: {item}")
        entries.append(BatchEntry(path=item["path"], profile=item.get("profile")))
    return entries


def _parse_text_batch(batch_file: Path) -> list[BatchEntry]:
    entries: list[BatchEntry] = []
    for line in _read_batch_file_text(batch_file).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(BatchEntry(path=line))
    return entries


def run_batch(batch_file: Path, args: argparse.Namespace) -> int:
    entries = parse_batch_file(batch_file)
    if not entries:
        print("No repositories found in batch file.")
        return 0

    results: list[tuple[str, int]] = []
    for entry in entries:
        print(f"\n{'─' * 60}")
        print(f"  {entry.path}")
        print(f"{'─' * 60}")

        try:
            target_repo = resolve_target_repo(entry.path)
        except (SystemExit, Exception) as exc:
            # Catch broadly, not just SystemExit: a single misbehaving
            # repository (bad encoding, unexpected git state, ...) must not
            # abort the rest of the batch.
            print(f"FAIL: {exc}")
            results.append((entry.path, 1))
            continue

        try:
            profile = parse_profile(entry.profile or args.profile)
            if profile is None and (args.check or args.sync):
                profile = infer_profile_from_existing(target_repo)
        except (SystemExit, Exception) as exc:
            # Catch broadly, not just SystemExit: a single misbehaving
            # repository (bad encoding, unexpected git state, ...) must not
            # abort the rest of the batch.
            print(f"FAIL: {exc}")
            results.append((entry.path, 1))
            continue

        try:
            # Per-entry copy: skills inference for one repository must not
            # leak into the rest of the batch.
            entry_args = argparse.Namespace(**vars(args))
            if (
                (entry_args.sync or entry_args.check)
                and not entry_args.skills
                and profile
                and skills_installed(target_repo, profile)
            ):
                entry_args.skills = True

            if entry_args.check:
                code = check_adoption(
                    target_repo,
                    entry_args.shared_url,
                    check_skills=entry_args.skills,
                    visibility=entry_args.visibility,
                    profile_override=profile,
                    problems_only=entry_args.problems_only,
                )
            else:
                if not profile:
                    print("FAIL: no profile specified and none inferred from existing files.")
                    results.append((entry.path, 1))
                    continue
                plan = build_plan(target_repo, entry_args, profile)
                if entry_args.sync and plan.source_status.local_status in {"behind", "different", "diverged"}:
                    print(f"FAIL: local source is {plan.source_status.local_status}. Update agent-rules first.")
                    results.append((entry.path, 1))
                    continue
                code = apply_plan(plan, entry_args)
        except (SystemExit, Exception) as exc:
            print(f"FAIL: {exc}")
            code = 1

        results.append((entry.path, code))

    print(f"\n{'═' * 60}")
    succeeded = [p for p, c in results if c == 0]
    # Exit code 2 means WARN-only (from check_adoption); anything else non-zero failed.
    warned = [p for p, c in results if c == 2]
    failed = [p for p, c in results if c not in (0, 2)]
    print(f"{len(succeeded)} succeeded, {len(warned)} warned, {len(failed)} failed")
    if warned:
        print("\nWarnings only:")
        for p in warned:
            print(f"  - {p}")
    if failed:
        print("\nFailed:")
        for p in failed:
            print(f"  - {p}")
    if failed:
        return 1
    if warned:
        return 2
    return 0
