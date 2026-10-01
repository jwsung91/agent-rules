"""Authenticated, single-job mailbox between the GUI and a local host worker."""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .gui_service import GuiError


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    action: Literal["connection", "models", "memories", "context", "analyze"]
    provider: Literal["codex", "claude"] = "codex"
    path: str = ""
    model: str = Field(default="", max_length=100)
    memories: list[str] = Field(default_factory=list, max_length=20)


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    result: dict | None = None
    error: str = Field(default="", max_length=2000)


class HostBridge:
    def __init__(self, token: str, workspace: Path):
        if len(token) < 32:
            raise ValueError("Host bridge token must contain at least 32 characters")
        self.token = token
        self.workspace = workspace.resolve()
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.accepted = threading.Event()
        self.pending: Job | None = None
        self.claimed = False
        self.reply: Reply | None = None
        self.last_seen = 0.0

    def poll(self) -> dict:
        with self.lock:
            self.last_seen = time.monotonic()
            if self.pending and not self.claimed:
                self.claimed = True
                self.accepted.set()
                return {"job": self.pending.model_dump()}
            return {"job": None}

    def complete(self, reply: Reply) -> dict:
        with self.lock:
            if (
                not self.pending
                or not self.claimed
                or reply.id != self.pending.id
                or self.reply
            ):
                raise GuiError("만료되었거나 일치하지 않는 호스트 AI 요청입니다.")
            self.reply = reply
            self.last_seen = time.monotonic()
            self.event.set()
        return {"ok": True}

    def call(
        self,
        action: str,
        provider: str = "codex",
        repo: Path | None = None,
        model: str = "",
        memories: list[str] | None = None,
        timeout: float = 360,
    ) -> dict:
        try:
            relative = repo.relative_to(self.workspace).as_posix() if repo else ""
        except ValueError as exc:
            raise GuiError(
                "AI 대상은 Docker에 연결한 작업 경로 안에서 선택하세요."
            ) from exc
        with self.lock:
            if self.pending:
                raise GuiError("호스트 AI가 다른 요청을 처리 중입니다.")
            if time.monotonic() - self.last_seen > 10:
                raise GuiError(
                    "호스트 AI 연결 프로그램이 꺼져 있습니다. 호스트에서 scripts/ai_bridge.py를 실행하세요."
                )
            self.pending = Job(
                id=secrets.token_urlsafe(24),
                action=action,
                provider=provider,
                path=relative,
                model=model,
                memories=memories or [],
            )
            self.claimed = False
            self.reply = None
            self.event.clear()
            self.accepted.clear()
        started = time.monotonic()
        try:
            if not self.accepted.wait(min(5, timeout)):
                raise GuiError(
                    "호스트 AI 요청 수신 시간이 초과됐습니다. 연결 프로그램을 확인하세요."
                )
            if not self.event.wait(max(0, timeout - (time.monotonic() - started))):
                raise GuiError(
                    "호스트 AI 응답 시간이 초과됐습니다. 연결 프로그램을 확인하세요."
                )
            if self.reply.error:
                raise GuiError(self.reply.error)
            if self.reply.result is None:
                raise GuiError("호스트 AI가 결과를 반환하지 않았습니다.")
            return self.reply.result
        finally:
            with self.lock:
                self.pending = None
                self.reply = None


def host_target(workspace: Path, relative: str) -> Path:
    from .gui_service import DeploymentService

    value = PurePosixPath(relative)
    if (
        not relative
        or value.is_absolute()
        or ".." in value.parts
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError("호스트 작업 경로 밖의 요청은 허용하지 않습니다.")
    candidate = workspace.joinpath(*value.parts)
    if any(p.is_symlink() for p in [candidate, *candidate.parents]):
        raise ValueError("심볼릭 링크 프로젝트는 허용하지 않습니다.")
    service = DeploymentService(workspace)
    repo = service.target(str(candidate))
    service.guard(repo)
    return repo


def run_job(job: Job, workspace: Path, memory_roots: list[Path]) -> dict:
    from . import gui_ai

    if job.action == "connection":
        return gui_ai.connection(job.provider)
    if job.action == "models":
        return gui_ai.models(job.provider)
    repo = host_target(workspace, job.path)
    if job.action == "memories":
        return gui_ai.home_memories(repo)
    for value in job.memories:
        path = Path(value).expanduser()
        if not path.is_absolute() or not any(
            path.resolve().is_relative_to(root.resolve())
            for root in [workspace, *memory_roots]
        ):
            raise ValueError(
                "추가 메모리는 작업 경로·기본 메모리 폴더 또는 --memory-root 안에 있어야 합니다."
            )
    if job.action == "context":
        return {"files": gui_ai.context(repo, job.memories)["files"]}
    return gui_ai.analyze(repo, job.model, job.memories, job.provider)
