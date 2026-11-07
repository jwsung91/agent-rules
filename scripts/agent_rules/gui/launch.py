#!/usr/bin/env python3
"""Run the local deployment GUI in the same environment as your repositories."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import threading
import webbrowser

from ..constants import DEFAULT_SHARED_URL, SOURCE_REF
from ..source import parse_source_ref, source_repo_root


def env_default(name: str, fallback: str) -> str:
    # Launch scripts and Compose pass settings through these variables, so the
    # defaults below are the only copy; an empty value means "use the default".
    return os.environ.get(name) or fallback


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the local agent-rules deployment GUI."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=env_default("AGENT_RULES_WORKSPACE", str(source_repo_root().parent)),
        help="Initial repository parent folder; editable in the GUI. "
        "Default: AGENT_RULES_WORKSPACE or the folder containing this checkout.",
    )
    parser.add_argument(
        "--codex", help="Codex CLI executable path (or AGENT_RULES_CODEX)."
    )
    parser.add_argument(
        "--claude", help="Claude Code CLI executable path (or AGENT_RULES_CLAUDE)."
    )
    parser.add_argument(
        "--container",
        action="store_true",
        help="Bind all container interfaces; publish the port on host loopback only.",
    )
    parser.add_argument(
        "--shared-url", default=env_default("AGENT_RULES_SHARED_URL", DEFAULT_SHARED_URL),
        help="Shared rules repository URL for links and version checks (or AGENT_RULES_SHARED_URL).",
    )
    parser.add_argument(
        "--source-ref", type=parse_source_ref,
        default=env_default("AGENT_RULES_SOURCE_REF", SOURCE_REF),
        help="Shared source branch (or AGENT_RULES_SOURCE_REF; default: main).",
    )
    parser.add_argument(
        "--max-depth", type=int, default=env_default("AGENT_RULES_MAX_DEPTH", "3"),
        help="Repository discovery depth (or AGENT_RULES_MAX_DEPTH; positive; default: 3).",
    )
    parser.add_argument(
        "--port", type=int, default=env_default("AGENT_RULES_PORT", "8765"),
        help="Listening port (or AGENT_RULES_PORT; 1024-65535; default: 8765).",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the local URL using this environment's browser handler.",
    )
    args = parser.parse_args()
    if args.max_depth < 1:
        parser.error("--max-depth must be positive")
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if not args.workspace.expanduser().is_dir():
        parser.error("--workspace must be an existing directory")
    try:
        import uvicorn
        from .service import DeploymentService
        from .web import create_app
    except ModuleNotFoundError as exc:
        parser.exit(
            1,
            f"Missing GUI dependency: {exc.name}. Run: python -m pip install -r requirements-gui.txt\n",
        )
    bridge_file = os.environ.get("AGENT_RULES_BRIDGE_FILE")
    if bridge_file and not Path(bridge_file).is_file():
        parser.exit(
            1,
            f"Host bridge token file not found: {bridge_file}\n"
            "Mount it (compose.yaml does) or unset AGENT_RULES_BRIDGE_FILE to run AI locally.\n",
        )
    if args.codex:
        os.environ["AGENT_RULES_CODEX"] = args.codex
    if args.claude:
        os.environ["AGENT_RULES_CLAUDE"] = args.claude
    host = "0.0.0.0" if args.container else "127.0.0.1"
    workspace = args.workspace.expanduser()
    service = DeploymentService(
        workspace, args.shared_url, home=workspace if args.container else None,
        source_ref=args.source_ref, max_depth=args.max_depth,
    )
    app = create_app(service, args.port)
    url = f"http://127.0.0.1:{args.port}"
    # Bind before opening the browser, so an occupied port never opens a
    # different application's page. No reload/workers: preview tokens are local.
    sock = socket.socket()
    try:
        sock.bind((host, args.port))
        sock.listen(128)
    except OSError as exc:
        sock.close()
        parser.exit(1, f"Cannot listen on {url}: {exc}\n")
    print(
        f"agent-rules GUI: {url}\nWorkspace: {args.workspace.expanduser().resolve()}\nStop with Ctrl+C.",
        flush=True,
    )
    if args.open_browser:
        threading.Timer(1, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.Server(
            uvicorn.Config(app, host=host, port=args.port, access_log=False)
        ).run(sockets=[sock])
    finally:
        sock.close()
    return 0
