"""Loopback-only web adapter. No arbitrary shell commands or remote browsing."""

from __future__ import annotations

from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .gui_service import DeploymentService, GuiError


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    profile: Literal["codex", "claude", "gemini", "all"] = "codex"
    visibility: Literal["local", "tracked"] = "local"
    skills: bool = True
    operation: Literal["install", "sync"] = "install"


class PreviewSelection(Selection):
    boundaries: list[str] = Field(default_factory=list, max_length=20)


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    model: str = Field(default="", max_length=100)
    memories: list[str] = Field(default_factory=list, max_length=20)


class DirectorySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default="", max_length=4096)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


def create_app(
    service: DeploymentService, port: int, session_token: str | None = None
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = session_token or secrets.token_urlsafe(32)
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    assets = Path(__file__).parent / "web"

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.headers.get("host") not in hosts:
            return JSONResponse(
                {"detail": "허용하지 않는 Host입니다."}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse(
                {"detail": "다른 사이트의 요청은 허용하지 않습니다."}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                {"detail": "다른 사이트의 요청은 허용하지 않습니다."}, status_code=403
            )
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            if not secrets.compare_digest(
                request.headers.get("x-session-token", ""), token
            ):
                return JSONResponse(
                    {"detail": "세션을 새로고침하세요."}, status_code=403
                )
        if request.method == "POST":
            if not request.headers.get("content-type", "").startswith(
                "application/json"
            ):
                return JSONResponse(
                    {"detail": "JSON 요청만 허용됩니다."}, status_code=415
                )
            body = await request.body()
            if len(body) > 16384:
                return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    async def execute(method, *args):
        # The core emits stdout; serialize all operations instead of redirecting
        # process-global stdout from multiple threads simultaneously.
        if not service.lock.acquire(blocking=False):
            raise HTTPException(
                409, "다른 작업이 진행 중입니다. 완료 후 다시 시도하세요."
            )
        try:
            return await run_in_threadpool(method, *args)
        except (GuiError, OSError, SystemExit) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"작업 실패: {exc}") from exc
        finally:
            service.lock.release()

    @app.get("/")
    def index():
        return FileResponse(assets / "index.html")

    @app.get("/app.js")
    def script():
        return FileResponse(assets / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def style():
        return FileResponse(assets / "style.css", media_type="text/css")

    @app.get("/api/session")
    def session():
        return {"token": token, "workspace": str(service.workspace)}

    @app.post("/api/workspace/suggest")
    async def suggest_workspace(selection: DirectorySelection):
        return await execute(service.suggest_directories, selection.path)

    @app.post("/api/workspace/browse")
    async def browse_workspace(selection: DirectorySelection):
        return await execute(service.browse, selection.path)

    @app.post("/api/workspace/change")
    async def change_workspace(selection: DirectorySelection):
        return await execute(service.change_workspace, selection.path)

    @app.post("/api/discover")
    async def discover():
        return await execute(service.discover)

    @app.post("/api/check")
    async def check(selection: Selection):
        return await execute(
            service.check,
            selection.path,
            selection.profile,
            selection.visibility,
            selection.skills,
        )

    @app.post("/api/preview")
    async def preview(selection: PreviewSelection):
        return await execute(
            service.preview,
            selection.path,
            selection.profile,
            selection.visibility,
            selection.skills,
            selection.operation,
            selection.boundaries,
        )

    @app.post("/api/ai/models")
    async def ai_models():
        from .gui_ai import models

        try:
            return await execute(models)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/ai/memories")
    async def ai_memories(selection: Analysis):
        from .gui_ai import home_memories

        return await execute(home_memories, service.target(selection.path))

    @app.post("/api/ai/connection")
    async def ai_connection():
        from .gui_ai import connection

        return await execute(connection)

    def ai_request(selection: Analysis, inspect_only: bool):
        from .gui_ai import analyze, context

        repo = service.target(selection.path)
        service.guard(repo)
        try:
            if inspect_only:
                return {"files": context(repo, selection.memories)["files"]}
            return analyze(repo, selection.model, selection.memories)
        except (ValueError, TimeoutError) as exc:
            raise GuiError(str(exc)) from exc

    @app.post("/api/ai/context")
    async def ai_context(selection: Analysis):
        return await execute(ai_request, selection, True)

    @app.post("/api/ai/analyze")
    async def ai_analyze(selection: Analysis):
        return await execute(ai_request, selection, False)

    @app.post("/api/apply")
    async def apply(approval: Approval):
        return await execute(service.apply, approval.token)

    return app
