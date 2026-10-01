#!/usr/bin/env python3
"""Run the local deployment GUI in the same environment as your repositories."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import threading
import webbrowser


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the local agent-rules deployment GUI."
    )
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="Initial repository parent folder; editable in the GUI. Discovery depth is three.",
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
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the local URL using this environment's browser handler.",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if not args.workspace.expanduser().is_dir():
        parser.error("--workspace must be an existing directory")
    try:
        import uvicorn
        from agent_rules.gui_service import DeploymentService
        from agent_rules.gui_web import create_app
    except ModuleNotFoundError as exc:
        parser.exit(
            1,
            f"Missing GUI dependency: {exc.name}. Run: python -m pip install -r requirements-gui.txt\n",
        )
    if args.codex:
        os.environ["AGENT_RULES_CODEX"] = args.codex
    if args.claude:
        os.environ["AGENT_RULES_CLAUDE"] = args.claude
    host = "0.0.0.0" if args.container else "127.0.0.1"
    app = create_app(DeploymentService(args.workspace.expanduser()), args.port)
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


if __name__ == "__main__":
    raise SystemExit(main())
