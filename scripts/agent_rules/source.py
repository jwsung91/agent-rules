"""The shared agent-rules checkout: locating it, and comparing against it."""

from __future__ import annotations

from pathlib import Path

from .constants import (
    LEGACY_CODEX_SKILL_ROOT,
    ENTRYPOINT_FILES,
    ENTRYPOINT_SKILL_ROOTS,
    PROFILE_FILES,
    PROFILE_SKILL_ROOTS,
    SHARED_SKILLS,
    SOURCE_REF,
    SYNC_BASE_ROOT,
    VALID_PROFILES,
)
from .gitio import merge_base_is_ancestor, run_command
from .metadata import parse_metadata
from .models import SourceStatus


def resolve_target_repo(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Target path does not exist: {path}")
    if not path.is_dir():
        raise SystemExit(f"Target path is not a directory: {path}")
    return path


def source_repo_root() -> Path:
    # scripts/agent_rules/source.py -> scripts/agent_rules -> scripts -> root.
    # Anchored on this file's location, so moving this module between
    # directories means updating this depth.
    return Path(__file__).resolve().parents[2]


def template_dir() -> Path:
    return source_repo_root() / "templates"


def read_template(name: str) -> str:
    path = template_dir() / name
    if not path.exists():
        raise SystemExit(f"Template file not found: {path}")
    return path.read_text(encoding="utf-8")


def parse_profile(value: str | None) -> str | None:
    if value is None:
        return None
    profile = value.strip().lower()
    if profile not in VALID_PROFILES:
        raise SystemExit(
            f"Unsupported profile: {value}. Supported values: {', '.join(sorted(VALID_PROFILES))}."
        )
    return profile


def required_files_for_profile(profile: str) -> list[str]:
    if profile not in PROFILE_FILES:
        raise SystemExit(
            f"Unsupported profile: {profile}. Supported values: {', '.join(sorted(VALID_PROFILES))}."
        )
    return list(PROFILE_FILES[profile])


def profile_skill_support(profile: str) -> tuple[list[str], list[str]]:
    """Split a profile's required entrypoints into ones with a shared-skill
    installation path (ENTRYPOINT_SKILL_ROOTS) and ones without (currently
    just GEMINI.md, since Gemini has no shared-skill convention yet)."""
    required = required_files_for_profile(profile)
    supported = [f for f in required if ENTRYPOINT_SKILL_ROOTS.get(f)]
    unsupported = [f for f in required if not ENTRYPOINT_SKILL_ROOTS.get(f)]
    return supported, unsupported


def local_source_head(root: Path | None = None) -> tuple[str | None, str | None]:
    root = root or source_repo_root()
    code, stdout, stderr = run_command(["git", "-C", str(root), "rev-parse", "HEAD"])
    if code != 0 or not stdout:
        return None, stderr or "git rev-parse failed"
    return stdout, None


def remote_main_head(shared_url: str) -> tuple[str | None, str | None]:
    code, stdout, stderr = run_command(
        ["git", "ls-remote", shared_url, f"refs/heads/{SOURCE_REF}"]
    )
    if code != 0 or not stdout:
        return None, stderr or "git ls-remote failed"
    return stdout.split()[0], None


def resolve_latest_status(
    local_head: str | None,
    remote_head: str | None,
    repo: Path | None = None,
) -> str:
    if not local_head or not remote_head:
        return "unknown"
    if local_head == remote_head:
        return "current"

    if repo is None:
        return "different"

    local_before_remote = merge_base_is_ancestor(repo, local_head, remote_head)
    if local_before_remote == "yes":
        return "behind"
    if local_before_remote.startswith("unknown:"):
        return "different"

    remote_before_local = merge_base_is_ancestor(repo, remote_head, local_head)
    if remote_before_local == "yes":
        return "ahead"
    if remote_before_local.startswith("unknown:"):
        return "different"
    return "diverged"


def latest_reference(source_status: SourceStatus) -> str | None:
    return source_status.remote_head or source_status.local_head


def target_commit_status(
    source_commit: str | None,
    source_status: SourceStatus,
    repo: Path | None = None,
) -> str:
    latest = latest_reference(source_status)
    if not source_commit or not latest:
        return "unknown"
    if source_commit == latest:
        return "current"
    if repo is None:
        return "different"

    applied_before_latest = merge_base_is_ancestor(repo, source_commit, latest)
    if applied_before_latest == "yes":
        return "behind"
    if applied_before_latest.startswith("unknown:"):
        return "different"
    return "different"


_SOURCE_STATUS_CACHE: dict[str, SourceStatus] = {}


def get_source_status(shared_url: str) -> SourceStatus:
    # Cached per URL: batch runs would otherwise repeat the same
    # `git ls-remote` network call once per repository.
    cached = _SOURCE_STATUS_CACHE.get(shared_url)
    if cached is not None:
        return cached
    warnings: list[str] = []
    local_head, local_warning = local_source_head()
    if local_warning:
        warnings.append(f"WARN: local source HEAD unavailable: {local_warning}")
    remote_head, remote_warning = remote_main_head(shared_url)
    if remote_warning:
        warnings.append(f"WARN: remote main HEAD unavailable: {remote_warning}")
    status = SourceStatus(
        local_head=local_head,
        remote_head=remote_head,
        local_status=resolve_latest_status(local_head, remote_head, source_repo_root()),
        warnings=warnings,
    )
    _SOURCE_STATUS_CACHE[shared_url] = status
    return status


def sync_base_path(relative_path: str) -> str:
    return f"{SYNC_BASE_ROOT}/{relative_path}"


def infer_profile_from_existing(target_repo: Path) -> str | None:
    for name in ENTRYPOINT_FILES:
        p = target_repo / name
        if p.exists():
            m = parse_metadata(p.read_text(encoding="utf-8", errors="replace"))
            if m.get("profile"):
                return m["profile"]
    return None


def adoption_is_current(target_repo: Path, profile: str | None) -> bool:
    """True when every file this profile generates exists and is ours.

    Deliberately strict about the metadata block: a file that exists without
    one was written by someone else, and --sync handles those differently
    (merge for AGENTS.md, refuse for the rest), so the plain refusal and its
    explanation remain the better answer in that case.
    """
    if profile not in VALID_PROFILES:
        return False
    for name in required_files_for_profile(profile):
        path = target_repo / name
        if not path.exists():
            return False
        if not parse_metadata(path.read_text(encoding="utf-8", errors="replace")):
            return False
    return True


def skills_installed(target_repo: Path, profile: str) -> bool:
    for root in profile_skill_roots(profile, target_repo):
        for skill_name in SHARED_SKILLS:
            if (target_repo / root / skill_name / "SKILL.md").exists():
                return True
    return False


def codex_skill_root(target_repo: Path) -> str:
    """Keep legacy installations in place; never create duplicate named skills."""
    current = PROFILE_SKILL_ROOTS["codex"][0]

    def present(root: str) -> bool:
        return any(
            (target_repo / root / name).exists()
            or (target_repo / sync_base_path(f"{root}/{name}")).exists()
            for name in SHARED_SKILLS
        )

    legacy = present(LEGACY_CODEX_SKILL_ROOT)
    if legacy and present(current):
        raise SystemExit(
            "Both legacy and current Codex shared-skill roots exist. "
            "Reconcile the duplicate installations before adopting, syncing, or removing."
        )
    return LEGACY_CODEX_SKILL_ROOT if legacy else current


def profile_skill_roots(profile: str, target_repo: Path | None = None) -> tuple[str, ...]:
    roots = PROFILE_SKILL_ROOTS.get(profile, ())
    if target_repo is None or profile not in {"codex", "all"}:
        return roots
    codex_root = codex_skill_root(target_repo)
    return tuple(codex_root if r == PROFILE_SKILL_ROOTS["codex"][0] else r for r in roots)
