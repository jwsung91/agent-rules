"""Keep the latest successful AI proposal per repository across GUI restarts.

Records live where the AI runs (the host), outside target repositories, so a
restarted GUI or Docker container can reload them without a new analysis.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ..gitio import run_command

VERSION = 1


def store_dir() -> Path:
    override = os.environ.get("AGENT_RULES_PROPOSAL_DIR")
    if override:
        return Path(override).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(cache) / "agent-rules" / "ai-proposals"


def record_path(repo: Path) -> Path:
    key = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:32]
    return store_dir() / f"{key}.json"


def head_commit(repo: Path) -> str | None:
    code, stdout, _ = run_command(["git", "-C", str(repo), "rev-parse", "HEAD"])
    return stdout if code == 0 and stdout else None


def save(repo: Path, provider: str, model: str, memories: list[str], proposal: dict) -> Path:
    """Write the record to a temporary file, then replace the previous one."""
    record = {
        "version": VERSION,
        "repo": str(repo.resolve()),
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": head_commit(repo),
        "provider": provider,
        "model": model,
        "memories": memories,
        "proposal": proposal,
    }
    target = record_path(repo)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkstemp creates the file with owner-only permissions; proposals can quote
    # memory contents. The temporary file shares the directory so os.replace
    # stays atomic and a crash leaves the previous record intact.
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target


def load(repo: Path) -> dict:
    """Return the saved record, marked stale when the repository HEAD moved."""
    try:
        record = json.loads(record_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"saved": None}
    if (
        not isinstance(record, dict)
        or record.get("version") != VERSION
        or record.get("repo") != str(repo.resolve())
        or not isinstance(record.get("proposal"), dict)
    ):
        return {"saved": None}
    current = head_commit(repo)
    record["stale"] = bool(record.get("commit") and current and record["commit"] != current)
    return {"saved": record}
