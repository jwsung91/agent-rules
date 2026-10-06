"""Local GUI operations backed by the existing adoption planner and writer."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass
import difflib
import hashlib
import io
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time

from .applying import apply_plan
from .checking import check_adoption
from .constants import DEFAULT_SHARED_URL, VALID_PROFILES, VALID_VISIBILITIES
from .gitignore import add_to_gitignore
from .gitio import find_repo_root
from .metadata import parse_metadata
from .models import AdoptionPlan
from .planning import build_plan
from .source import (
    infer_profile_from_existing,
    skills_installed,
    source_repo_root,
    local_source_head,
)


class GuiError(ValueError):
    pass


@dataclass
class Preview:
    plan: AdoptionPlan
    args: argparse.Namespace
    fingerprint: str
    expires: float


class DeploymentService:
    """One operation at a time, including legacy stdout-producing helpers."""

    def __init__(
        self,
        workspace: Path,
        shared_url: str = DEFAULT_SHARED_URL,
        home: Path | None = None,
    ):
        self.workspace = workspace.resolve(strict=True)
        # In Docker the user's home is the container's, so callers pass the
        # mounted workspace as the "home" the folder picker returns to.
        self.home = home or Path.home()
        if not self.workspace.is_dir():
            raise GuiError("작업 경로는 디렉터리여야 합니다.")
        self.shared_url = shared_url
        self.lock = threading.Lock()
        self.previews: dict[str, Preview] = {}

    def directory(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            raise GuiError(
                "서버 기준 절대 경로를 입력하세요. 홈은 ~로 지정할 수 있습니다."
            )
        if any(p.is_symlink() for p in [candidate, *candidate.parents]):
            raise GuiError("심볼릭 링크 폴더는 지원하지 않습니다.")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            raise GuiError("디렉터리를 선택하세요.")
        return resolved

    def browse(self, path: str, inspect_repositories: bool = True) -> dict:
        directory = self.directory(path or str(self.workspace))
        children = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name != ".git" and entry.is_dir(follow_symlinks=False):
                    children.append(
                        {
                            "name": entry.name,
                            "path": str(directory / entry.name),
                            "is_repository": (Path(entry.path) / ".git").exists()
                            and find_repo_root(Path(entry.path)) == Path(entry.path),
                        }
                    )
                    if len(children) > 1000:
                        raise GuiError(
                            "하위 폴더가 너무 많습니다. 원하는 경로를 직접 입력하세요."
                        )
        count = None
        if inspect_repositories:
            count = sum(
                "error" not in row
                for row in DeploymentService(directory, self.shared_url).discover()[
                    "repositories"
                ]
            )
        return {
            "repository_count": count,
            "path": str(directory),
            "parent": str(directory.parent),
            "home": str(self.home),
            "directories": sorted(children, key=lambda x: x["name"].casefold()),
        }

    def suggest_directories(self, value: str) -> dict:
        if not value.strip():
            return {
                "paths": list(dict.fromkeys([str(self.workspace), str(self.home)]))
            }
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            return {"paths": []}
        # A trailing separator means the user wants children; otherwise match
        # the last component among siblings, even if it is already a directory.
        trailing = value.endswith(("/", "\\"))
        parent = candidate if trailing else candidate.parent
        prefix = "" if trailing else candidate.name.casefold()
        # Dot-directories only when the typed name asks for one.
        hidden = prefix.startswith(".")
        try:
            listing = self.browse(str(parent), inspect_repositories=False)
        except (GuiError, OSError):
            return {"paths": []}
        return {
            "paths": [
                entry["path"] + os.sep
                for entry in listing["directories"]
                if entry["name"].casefold().startswith(prefix)
                and (hidden or not entry["name"].startswith("."))
            ][:30]
        }

    def change_workspace(self, path: str) -> dict:
        candidate = self.directory(path)
        # Discover before committing the switch: failed navigation keeps the
        # active workspace and its preview approvals intact.
        self.browse(str(candidate), inspect_repositories=False)
        result = DeploymentService(candidate, self.shared_url).discover()
        if not any("error" not in row for row in result["repositories"]):
            raise GuiError(
                "선택 가능한 Git 저장소가 없습니다. .git이 있는 저장소 또는 그 상위 폴더를 선택하세요. 하위 탐색 깊이는 3입니다."
            )
        self.workspace = candidate
        self.previews.clear()
        return result

    def target(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve(strict=True)
        if (
            not resolved.is_relative_to(self.workspace)
            or resolved == source_repo_root()
        ):
            raise GuiError(
                "선택한 작업 폴더 안의 대상 저장소만 허용됩니다. 원본 저장소는 제외됩니다."
            )
        if not resolved.is_dir() or find_repo_root(resolved) != resolved:
            raise GuiError("Git 저장소 루트를 선택하세요.")
        return resolved

    @staticmethod
    def safe_path(repo: Path, relative: str) -> Path:
        path = repo / relative
        for item in [path, *path.parents]:
            if item == repo:
                break
            if item.is_symlink() or not item.resolve().is_relative_to(repo):
                raise GuiError(
                    f"심볼릭 링크 경로는 GUI에서 지원하지 않습니다: {relative}"
                )
        return path

    def guard(self, repo: Path) -> None:
        for name in (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".gitignore",
            ".agents",
            ".codex",
            ".claude",
            ".agent-rules",
        ):
            path = self.safe_path(repo, name)
            if path.is_dir():
                for child in path.rglob("*"):
                    self.safe_path(repo, child.relative_to(repo).as_posix())

    def fingerprint(self, repo: Path) -> str:
        self.guard(repo)
        digest = hashlib.sha256()
        paths = set()
        for name in (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".gitignore",
            ".agents",
            ".codex",
            ".claude",
            ".agent-rules",
        ):
            p = repo / name
            paths.add(p)
            if p.is_dir():
                paths.update(p.rglob("*"))
        source = source_repo_root()
        for folder in ("templates", "skills", "rules", "scripts"):
            paths.update(
                p for p in (source / folder).rglob("*") if "__pycache__" not in p.parts
            )
        for path in sorted(paths):
            digest.update(str(path).encode())
            if path.is_file():
                digest.update(path.read_bytes())
                digest.update(str(path.stat().st_mode).encode())
            else:
                digest.update(b"directory" if path.is_dir() else b"missing")
        for directory, command in (
            (repo, ["ls-files", "--stage", "-z"]),
            (repo, ["config", "--list", "--show-origin"]),
        ):
            result = subprocess.run(
                ["git", "-C", str(directory), *command],
                capture_output=True,
                check=True,
                timeout=15,
            )
            digest.update(result.stdout)
        source_head, warning = local_source_head(source)
        if not source_head:
            raise GuiError(f"배포 소스 버전을 확인하지 못했습니다: {warning}")
        digest.update(source_head.encode())
        return digest.hexdigest()

    @staticmethod
    def agent_status(repo: Path) -> dict[str, str]:
        statuses = {}
        for agent, filename in (
            ("codex", "AGENTS.md"), ("claude", "CLAUDE.md"), ("gemini", "GEMINI.md")
        ):
            path = repo / filename
            if not path.is_file():
                statuses[agent] = "미설치"
            elif parse_metadata(path.read_text(encoding="utf-8", errors="replace")):
                statuses[agent] = "설치됨"
            else:
                statuses[agent] = "사용자 규칙"
        return statuses

    def discover(self) -> dict:
        from generate_batch_list import find_git_repos

        rows = []
        for repo in find_git_repos(self.workspace, max_depth=3, skip_hidden=True):
            if repo.resolve() == source_repo_root():
                continue
            try:
                self.guard(self.target(str(repo)))
                profile = infer_profile_from_existing(repo)
                rows.append(
                    {
                        "path": str(repo),
                        "name": repo.name,
                        "profile": profile,
                        "agents": self.agent_status(repo),
                        "status": "검사 전" if profile else "미설치",
                    }
                )
            except (GuiError, OSError, SystemExit) as exc:
                rows.append({"path": str(repo), "name": repo.name, "error": str(exc)})
        return {"workspace": str(self.workspace), "repositories": rows}

    def check(self, path: str, profile: str, visibility: str, skills: bool) -> dict:
        repo = self.target(path)
        self.guard(repo)
        self.options(profile, visibility)
        output = io.StringIO()
        with redirect_stdout(output):
            code = check_adoption(
                repo,
                self.shared_url,
                check_skills=skills or skills_installed(repo, profile),
                visibility=visibility,
                profile_override=profile,
                problems_only=True,
            )
        return {
            "code": code,
            "status": {0: "정상", 1: "확인 필요", 2: "경고"}.get(code, "오류"),
            "log": output.getvalue(),
            "agents": self.agent_status(repo),
        }

    @staticmethod
    def options(profile: str, visibility: str) -> None:
        if profile not in VALID_PROFILES or visibility not in VALID_VISIBILITIES:
            raise GuiError("지원하지 않는 에이전트 또는 공개 범위입니다.")

    def preview(
        self,
        path: str,
        profile: str,
        visibility: str,
        skills: bool,
        operation: str,
        boundaries: list[str] | None = None,
    ) -> dict:
        self.options(profile, visibility)
        if operation not in {"install", "sync"}:
            raise GuiError("설치 또는 동기화만 지원합니다.")
        repo = self.target(path)
        before = self.fingerprint(repo)
        args = argparse.Namespace(
            shared_url=self.shared_url,
            profile=profile,
            boundary=boundaries or [],
            validation=[],
            sync=operation == "sync",
            force=False,
            skills=skills or (operation == "sync" and skills_installed(repo, profile)),
            local_copy=False,
            visibility=visibility,
            dry_run=True,
            verbose=False,
        )
        plan = build_plan(repo, args, profile)
        if args.sync and plan.source_status.local_status in {
            "behind",
            "different",
            "diverged",
        }:
            raise GuiError("먼저 agent-rules 원본을 업데이트하세요.")
        for item in plan.files:
            self.safe_path(repo, item.path)
        log = io.StringIO()
        with redirect_stdout(log):
            code = apply_plan(plan, args)
        files = []
        for item in plan.files:
            if item.action == "no-op":
                continue
            old = (
                (repo / item.path).read_text(encoding="utf-8")
                if (repo / item.path).is_file()
                else ""
            )
            new = (
                item.content
                if item.content is not None
                else item.source.read_text(encoding="utf-8")
                if item.source
                else ""
            )
            files.append(self.diff(item.path, item.action, old, new))
        if visibility == "local" and code == 0:
            with tempfile.TemporaryDirectory(prefix="agent-rules-preview-") as tmp:
                temporary = Path(tmp)
                old = (
                    (repo / ".gitignore").read_text(encoding="utf-8")
                    if (repo / ".gitignore").exists()
                    else ""
                )
                (temporary / ".gitignore").write_text(old, encoding="utf-8")
                with redirect_stdout(io.StringIO()):
                    add_to_gitignore(
                        temporary, [item.path for item in plan.files], dry_run=False
                    )
                new = (temporary / ".gitignore").read_text(encoding="utf-8")
                if old != new:
                    files.append(
                        self.diff(
                            ".gitignore",
                            "update" if (repo / ".gitignore").exists() else "create",
                            old,
                            new,
                        )
                    )
        after = self.fingerprint(repo)
        if before != after:
            raise GuiError("미리보기 중 파일이 변경됐습니다. 다시 확인하세요.")
        self.previews = {
            k: v for k, v in self.previews.items() if v.expires > time.monotonic()
        }
        token = None
        if code == 0:
            if len(self.previews) >= 64:
                self.previews.pop(next(iter(self.previews)))
            token = secrets.token_urlsafe(24)
            self.previews[token] = Preview(plan, args, after, time.monotonic() + 900)
        return {
            "token": token,
            "code": code,
            "files": files,
            "warnings": plan.warnings,
            "source": plan.source_status.local_status,
            "log": log.getvalue(),
        }

    @staticmethod
    def diff(path: str, action: str, before: str, after: str) -> dict:
        return {
            "path": path,
            "action": action,
            "diff": "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=path,
                    tofile=path,
                )
            ),
        }

    def apply(self, token: str) -> dict:
        preview = self.previews.pop(token, None)
        if preview is None or preview.expires < time.monotonic():
            raise GuiError("미리보기가 없거나 만료됐습니다. 다시 확인하세요.")
        repo = self.target(str(preview.plan.target_repo))
        if self.fingerprint(repo) != preview.fingerprint:
            raise GuiError(
                "원본 또는 대상 파일이 변경됐습니다. 미리보기를 다시 실행하세요."
            )
        # Refresh Git ignore/tracking checks before using the reviewed content.
        current = build_plan(repo, preview.args, preview.plan.profile)
        if preview.args.sync and current.source_status.local_status in {
            "behind",
            "different",
            "diverged",
        }:
            raise GuiError(
                "원본 버전이 변경됐습니다. 원본을 업데이트하고 다시 확인하세요."
            )
        if self.fingerprint(repo) != preview.fingerprint:
            raise GuiError("적용 준비 중 파일이 변경됐습니다. 다시 확인하세요.")
        preview.plan.ignore_statuses = current.ignore_statuses
        preview.args.dry_run = False
        log = io.StringIO()
        try:
            with redirect_stdout(log):
                code = apply_plan(preview.plan, preview.args)
        except (Exception, SystemExit) as exc:
            return {
                "code": 1,
                "written": preview.plan.written,
                "log": log.getvalue()
                + f"\n적용 중 오류: {exc}\n일부 파일이 변경됐을 수 있습니다. 상태를 다시 확인하세요.",
            }
        return {"code": code, "written": preview.plan.written, "log": log.getvalue()}
