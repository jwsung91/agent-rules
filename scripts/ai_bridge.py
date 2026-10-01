#!/usr/bin/env python3
"""Run AI CLIs on the host; poll the local Docker GUI for scoped requests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Host bridge redirects are not allowed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument(
        "--init-token",
        action="store_true",
        help="Create a shared token file and exit; never overwrites an existing file.",
    )
    parser.add_argument(
        "--workspace", type=Path, help="Host folder mounted as /workspace in Docker."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--codex")
    parser.add_argument("--claude")
    parser.add_argument("--memory-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    token_file = args.token_file.expanduser()
    if args.init_token:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(48))
        print(f"Created bridge token: {token_file}")
        return 0
    if not args.workspace or not args.workspace.expanduser().is_dir():
        parser.error("--workspace must be an existing host directory")
    parsed = urlparse(args.url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        parser.error("--url must be a loopback HTTP address")
    from agent_rules.gui_bridge import Job, run_job

    token = token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        parser.error("Invalid bridge token; use --init-token with a new file")
    for provider in ("codex", "claude"):
        if getattr(args, provider):
            os.environ[f"AGENT_RULES_{provider.upper()}"] = getattr(args, provider)
    workspace = args.workspace.expanduser().resolve()
    roots = [
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "memories",
        Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        / "projects",
        *(p.expanduser().resolve() for p in args.memory_root),
    ]
    opener = build_opener(NoRedirect)

    def request(action, payload):
        req = Request(
            args.url.rstrip("/") + "/api/bridge/" + action,
            json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Bridge-Token": token},
        )
        with opener.open(req, timeout=15) as response:
            return json.loads(response.read(1_000_001))

    print(f"Host AI bridge: {args.url} · workspace: {workspace}", flush=True)
    disconnected = False
    try:
        while True:
            try:
                data = request("poll", {})
                if disconnected:
                    print("GUI connection restored", flush=True)
                disconnected = False
                if data.get("job"):
                    job = Job.model_validate(data["job"])
                    reply = {"id": job.id}
                    try:
                        reply["result"] = run_job(job, workspace, roots)
                    except Exception as exc:
                        reply["error"] = str(exc)[:2000]
                    request("result", reply)
                else:
                    time.sleep(1)
            except (URLError, OSError, ValueError):
                if not disconnected:
                    print(
                        "GUI unavailable or token rejected; check URL, token and GUI process.",
                        flush=True,
                    )
                disconnected = True
                time.sleep(3)
    except KeyboardInterrupt:
        print("Host AI bridge stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
