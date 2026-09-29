#!/usr/bin/env python3
"""Automate the mechanical steps of a live cross-agent forward test.

Builds a fixture repository, adopts the shared skills into it, runs a real
`claude` or `codex` CLI invocation against a bundled-request prompt, and
records what happened: whether the fixture worktree stayed clean, the raw
transcript, and (for Claude) which `Skill` tool calls were made.

This script does NOT judge whether the response is *correct* (e.g. whether
scope was actually separated correctly) -- that judgment stays manual. Read
the saved transcript/final report and write the finding up by hand, the way
docs/cross-agent-validation.md's existing entries do. Automating that
judgment would reproduce the same false-positive risk this repository
already hit once with natural-language regex matching (see
docs/skill-authoring.md).

Keep this script's own runs out of the deterministic unit-test suite; it
shells out to real agent CLIs, requires authentication, and can incur cost.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import stat
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ForwardTestCase:
    name: str
    files: dict[str, str]
    prompt: str
    # Files written *after* the initial commit, left uncommitted so the run
    # starts with a working change for validation or commit preparation.
    pending_changes: dict[str, str] = field(default_factory=dict)


CASES: dict[str, ForwardTestCase] = {
    "percentage-discount-bug": ForwardTestCase(
        name="percentage-discount-bug",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent)\n"
            ),
            "test_discount.py": (
                "from discount import apply_discount\n\n\n"
                "def test_twenty_percent_discount():\n"
                "    assert apply_discount(100, 20) == 80\n"
            ),
        },
        prompt=(
            "apply_discount(100, 20) in discount.py returns -1900 but should "
            "return 80 -- something's wrong with the percentage math. While "
            "you're in there, can you also add a full test suite covering "
            "edge cases and refactor the function into a Discount class for "
            "better structure?"
        ),
    ),
    # Same percentage-discount defect as the bug case, but the ask is to
    # *review* a completed implementation for defects without touching it.
    # Exercises review-change's trigger and its read-only contract. The test
    # here locks in the wrong behavior, so it is itself a review finding.
    "percentage-discount-review": ForwardTestCase(
        name="percentage-discount-review",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount: 20% off 100 should return 80."""\n'
                "    return total - (total * rate_percent)\n"
            ),
            "test_discount.py": (
                "from discount import apply_discount\n\n\n"
                "def test_twenty_percent_discount():\n"
                "    # Locks in the current (incorrect) behavior.\n"
                "    assert apply_discount(100, 20) == -1900\n"
            ),
        },
        prompt=(
            "Review the apply_discount implementation in discount.py for "
            "correctness and report any defects by severity. The docstring "
            "says 20% off 100 should return 80. Do not modify any files -- "
            "this is a review only."
        ),
    ),
    # The ask is to *validate* a change by running checks and reporting the
    # evidence, without fixing anything. The test asserts the correct value,
    # so running it fails against the buggy code -- validate-change should
    # report that honestly rather than weaken the test. Exercises
    # validate-change's trigger and its non-mutating contract.
    "percentage-discount-validate": ForwardTestCase(
        name="percentage-discount-validate",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent / 100)\n"
            ),
            "test_discount.py": (
                "from discount import apply_discount\n\n\n"
                "def test_twenty_percent_discount():\n"
                "    assert apply_discount(100, 20) == 80\n"
            ),
        },
        prompt=(
            "I just changed apply_discount in discount.py. Validate the change "
            "by running the relevant checks and report exactly what passed or "
            "failed. Do not fix anything or weaken the tests -- validation only."
        ),
        pending_changes={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent)\n"
            ),
        },
    ),
    # The ask is to *commit* an existing working change. `pending_changes`
    # leaves an uncommitted addition after the initial commit so there is
    # something to commit. Exercises prepare-commit's trigger and its
    # message/scope discipline. Permission modes differ across runtimes;
    # record actual HEAD/index changes instead of assuming commits are blocked.
    "percentage-discount-commit": ForwardTestCase(
        name="percentage-discount-commit",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent / 100)\n"
            ),
        },
        prompt="Commit the current changes.",
        pending_changes={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent / 100)\n\n\n"
                "def apply_bulk_discount(total, rate_percent, quantity):\n"
                '    """Apply a percentage discount to a bulk order total."""\n'
                "    return apply_discount(total * quantity, rate_percent)\n"
            ),
        },
    ),
}

AGENT_PROFILES = {"claude": "claude", "codex": "codex"}


@dataclass
class RunResult:
    returncode: int | None
    transcript_path: Path
    final_report: str
    skill_invocations: list[dict[str, str]] | None
    clean: bool
    new_paths: list[str]
    duration_seconds: float
    changed_paths: list[str] = field(default_factory=list)
    git_before: dict[str, str] = field(default_factory=dict)
    git_after: dict[str, str] = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)



@dataclass
class RunProgress:
    run_dir: Path
    agent: str
    case: ForwardTestCase
    result: RunResult
    phase: str = "provenance"
    provenance: dict = field(default_factory=dict)

    def checkpoint(self, phase: str, result: RunResult | None = None) -> None:
        self.phase = phase
        if result is not None:
            self.result = result
        self.result.provenance = self.provenance
        write_summary(self.run_dir, self.agent, self.case, self.result, phase=phase)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live cross-agent forward test: fixture, adoption, "
        "agent invocation, and clean-worktree recording. Does not judge "
        "response correctness -- read the saved transcript for that."
    )
    parser.add_argument("--agent", required=True, choices=sorted(AGENT_PROFILES))
    parser.add_argument("--case", default="percentage-discount-bug", choices=sorted(CASES))
    parser.add_argument(
        "--profile",
        help="Adoption profile to install (default: matches --agent).",
    )
    parser.add_argument(
        "--shared-url",
        default=str(ROOT),
        help=f"Shared rules repository to adopt from. Default: {ROOT}",
    )
    parser.add_argument("--runs", type=positive_int, default=1, help="Number of repeated runs.")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory to write fixtures, transcripts, and summaries under.",
    )
    parser.add_argument("--claude-bin", default="claude", help="Override the claude executable (for testing).")
    parser.add_argument("--codex-bin", default="codex", help="Override the codex executable (for testing).")
    parser.add_argument("--timeout", type=positive_int, default=240, help="Per-run timeout in seconds.")
    parser.add_argument("--model", help="Explicit model to request; omitted means the CLI default (not inferred).")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero for process failures or mutations in non-commit cases; does not grade response quality.")
    return parser.parse_args()


def run_command(command: list[str], cwd: Path | None, timeout: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"Agent executable not found: {command[0]} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired can contain bytes even when text=True. The timeout
        # may also interrupt a UTF-8 character, so preserve readable partial output.
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return 124, stdout, stderr
    return result.returncode, result.stdout, result.stderr


def run_checked(command: list[str], cwd: Path, timeout: int, *, action: str) -> str:
    """Run a command that must succeed, or abort with its output.

    Every recorded result is relative to the fixture repository: if one of the
    setup git commands quietly fails, the run continues against a repository
    that has no baseline commit and its clean-worktree verdict means nothing.
    Fail loudly instead, the way adopt_skills() already does for the adoption
    step.
    """
    code, stdout, stderr = run_command(command, cwd, timeout)
    if code != 0:
        raise SystemExit(
            f"{action} failed (exit {code}): {shlex.join(command)}\n{stdout}\n{stderr}"
        )
    return stdout


def build_fixture(case: ForwardTestCase, fixture_dir: Path) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in case.files.items():
        target = fixture_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_checked(["git", "init", "-q"], fixture_dir, 30, action="git init")
    run_checked(
        ["git", "-c", "user.email=forward-test@example.invalid", "-c", "user.name=Forward Test", "add", "-A"],
        fixture_dir,
        30,
        action="git add",
    )
    run_checked(
        [
            "git",
            "-c",
            "user.email=forward-test@example.invalid",
            "-c",
            "user.name=Forward Test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "initial fixture",
        ],
        fixture_dir,
        30,
        action="git commit",
    )
    # Apply working changes left uncommitted on top of the initial commit, so a
    # case like prepare-commit starts with something to commit.
    for relative_path, content in case.pending_changes.items():
        target = fixture_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def adopt_skills(fixture_dir: Path, profile: str, shared_url: str) -> None:
    code, stdout, stderr = run_command(
        [
            sys.executable,
            str(ROOT / "scripts" / "adopt.py"),
            str(fixture_dir),
            "--profile",
            profile,
            "--skills",
            "--shared-url",
            shared_url,
        ],
        cwd=ROOT,
        timeout=60,
    )
    if code != 0:
        raise SystemExit(f"adopt.py failed (exit {code}):\n{stdout}\n{stderr}")


def git_status_lines(fixture_dir: Path) -> list[str]:
    # Checked, not best-effort: a failed `git status` used to yield an empty
    # list, which reads as "no new paths" and reports the run as clean --
    # exactly the false negative this script exists to rule out.
    stdout = run_checked(
        ["git", "status", "--short"], fixture_dir, 30, action="git status"
    )
    return [line for line in stdout.splitlines() if line.strip()]


def snapshot_worktree(fixture_dir: Path) -> dict[str, tuple[int, str]]:
    """Capture file contents and modes, including ignored files, outside .git.

    Do not follow symlinks: record their targets instead. Exclude timestamps
    so reading a file or rewriting identical contents does not count as an edit.
    """
    snapshot: dict[str, tuple[int, str]] = {}

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            if path == fixture_dir / ".git":
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                content = str(path.readlink())
            elif stat.S_ISDIR(mode):
                visit(path)
                continue
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
                content = digest.hexdigest()
            else:
                raise SystemExit(f"Cannot snapshot unsupported fixture file: {path}")
            snapshot[path.relative_to(fixture_dir).as_posix()] = (mode, content)

    visit(fixture_dir)
    return snapshot


def extract_claude_skill_invocations(transcript_path: Path) -> list[dict[str, str]]:
    invocations: list[dict[str, str]] = []
    with transcript_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            for block in entry.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    invocations.append(block.get("input", {}))
    return invocations


def extract_claude_final_report(transcript_path: Path) -> str:
    final_report = ""
    with transcript_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "result":
                final_report = entry.get("result", "")
    return final_report


def run_claude(case: ForwardTestCase, fixture_dir: Path, run_dir: Path, claude_cmd: list[str], timeout: int, model: str | None = None) -> RunResult:
    transcript_path = run_dir / "transcript.jsonl"
    started = time.monotonic()
    code, stdout, stderr = run_command(
        [
            *claude_cmd,
            "-p",
            case.prompt,
            *(["--model", model] if model else []),
            "--permission-mode",
            "plan",
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        fixture_dir,
        timeout,
    )
    duration = time.monotonic() - started
    transcript_path.write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    final_report = extract_claude_final_report(transcript_path)
    (run_dir / "final_report.txt").write_text(final_report, encoding="utf-8")
    skill_invocations = extract_claude_skill_invocations(transcript_path)
    return RunResult(
        returncode=code,
        transcript_path=transcript_path,
        final_report=final_report,
        skill_invocations=skill_invocations,
        clean=True,  # filled in by caller after comparing the fixture
        new_paths=[],
        duration_seconds=duration,
    )


def run_codex(case: ForwardTestCase, fixture_dir: Path, run_dir: Path, codex_cmd: list[str], timeout: int, model: str | None = None) -> RunResult:
    transcript_path = run_dir / "transcript.jsonl"
    last_message_path = run_dir / "last_message.txt"
    started = time.monotonic()
    code, stdout, stderr = run_command(
        [
            *codex_cmd,
            "exec",
            *(["--model", model] if model else []),
            "--ephemeral",
            "-C",
            str(fixture_dir),
            "-s",
            "read-only",
            "--json",
            "-o",
            str(last_message_path),
            case.prompt,
        ],
        cwd=ROOT,
        timeout=timeout,
    )
    duration = time.monotonic() - started
    transcript_path.write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    final_report = last_message_path.read_text(encoding="utf-8") if last_message_path.exists() else ""
    (run_dir / "final_report.txt").write_text(final_report, encoding="utf-8")
    return RunResult(
        returncode=code,
        transcript_path=transcript_path,
        final_report=final_report,
        # Codex's --json event schema isn't parsed here (unlike Claude's
        # stream-json). Recording that fact instead of guessing at a schema
        # is the honest choice; inspect transcript.jsonl by hand for this.
        skill_invocations=None,
        clean=True,
        new_paths=[],
        duration_seconds=duration,
    )



def git_evidence(fixture_dir: Path) -> dict[str, str]:
    head = run_checked(["git", "rev-parse", "HEAD"], fixture_dir, 30, action="read HEAD").strip()
    index = run_checked(["git", "ls-files", "--stage", "-z"], fixture_dir, 30, action="read index")
    return {"head": head, "index_sha256": hashlib.sha256(index.encode("utf-8")).hexdigest()}


def collect_provenance(agent: str, command: list[str], run_dir: Path, model: str | None) -> dict:
    code, version, error = run_command([*command, "--version"], run_dir, 30)
    digest = hashlib.sha256()
    sources = [ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")]
    for directory in ("rules", "skills", "templates", "scripts"):
        sources.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for path in sorted(sources):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "cli_version_output": version.strip()[:2000] if code == 0 else None,
        "cli_version_error": error.strip()[:2000] if code != 0 else None,
        "requested_model": model,
        "effective_model": None,  # Never guess a default or alias resolution.
        "execution_mode": "plan" if agent == "claude" else "read-only",
        "source_commit": run_checked(["git", "rev-parse", "HEAD"], ROOT, 30, action="read source HEAD").strip(),
        "source_dirty": bool(run_checked(["git", "status", "--porcelain"], ROOT, 30, action="read source status").strip()),
        "source_content_sha256": digest.hexdigest(),
    }


def do_run(
    case: ForwardTestCase,
    agent: str,
    profile: str,
    shared_url: str,
    run_dir: Path,
    claude_cmd: list[str],
    codex_cmd: list[str],
    timeout: int,
    model: str | None = None,
    progress: RunProgress | None = None,
) -> RunResult:
    if progress:
        progress.checkpoint("fixture_setup")
    fixture_dir = run_dir / "fixture"
    build_fixture(case, fixture_dir)
    if progress:
        progress.checkpoint("adoption")
    adopt_skills(fixture_dir, profile, shared_url)
    if progress:
        progress.checkpoint("baseline")
    baseline = git_status_lines(fixture_dir)
    baseline_files = snapshot_worktree(fixture_dir)
    before_git = git_evidence(fixture_dir)
    if progress:
        progress.result.git_before = before_git
        progress.checkpoint("agent_execution")

    if agent == "claude":
        result = run_claude(case, fixture_dir, run_dir, claude_cmd, timeout, **({"model": model} if model else {}))
    elif agent == "codex":
        result = run_codex(case, fixture_dir, run_dir, codex_cmd, timeout, **({"model": model} if model else {}))
    else:
        raise SystemExit(f"Unsupported agent: {agent}")

    result.git_before = before_git
    if progress:
        progress.checkpoint("postcheck", result)
    after = git_status_lines(fixture_dir)
    new_paths = [line for line in after if line not in baseline]
    after_files = snapshot_worktree(fixture_dir)
    result.changed_paths = sorted(
        path for path in baseline_files.keys() | after_files.keys()
        if baseline_files.get(path) != after_files.get(path)
    )
    result.new_paths = new_paths
    result.git_before = before_git
    result.git_after = git_evidence(fixture_dir)
    result.clean = not result.changed_paths and baseline == after and result.git_before == result.git_after
    return result


def write_summary(
    run_dir: Path, agent: str, case: ForwardTestCase, result: RunResult,
    *, phase: str = "complete", failure: dict | None = None,
) -> None:
    summary = {
        "schema_version": 3,
        "phase": phase,
        "failure": failure,
        "execution_status": (
            "interrupted" if failure and failure["type"] == "KeyboardInterrupt"
            else "error" if failure else "running" if phase != "complete"
            else "timeout" if result.returncode == 124
            else "error" if result.returncode else "completed"
        ),
        "behavioral_verdict": "not_evaluated",
        "provenance": result.provenance,
        "git_before": result.git_before,
        "git_after": result.git_after,
        "head_changed": (result.git_before.get("head") != result.git_after.get("head")) if result.git_before and result.git_after else None,
        "index_changed": (result.git_before.get("index_sha256") != result.git_after.get("index_sha256")) if result.git_before and result.git_after else None,
        "agent": agent,
        "case": case.name,
        "prompt": case.prompt,
        "returncode": result.returncode,
        "duration_seconds": result.duration_seconds,
        "clean_worktree": result.clean if phase == "complete" else None,
        "postcheck_completed": phase == "complete",
        "new_paths_since_adoption": result.new_paths,
        "changed_paths_since_adoption": result.changed_paths,
        "skill_invocations": result.skill_invocations,
        "transcript": str(result.transcript_path.relative_to(run_dir)),
    }
    destination = run_dir / "summary.json"
    temporary = run_dir / "summary.json.tmp"
    temporary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)


def main() -> int:
    args = parse_args()
    case = CASES[args.case]
    profile = args.profile or AGENT_PROFILES[args.agent]
    out_root = Path(args.out_dir).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root.mkdir(parents=True, exist_ok=True)
    batch_dir = Path(tempfile.mkdtemp(prefix=f"{args.case}_{args.agent}_{timestamp}_", dir=out_root))
    # posix=False: keeps backslashes literal, so a Windows path passed as an
    # override (e.g. in tests) isn't mangled the way POSIX-mode shlex would.
    claude_cmd = shlex.split(args.claude_bin, posix=False)
    codex_cmd = shlex.split(args.codex_bin, posix=False)

    results: list[RunResult] = []
    for index in range(1, args.runs + 1):
        run_dir = batch_dir / f"run-{index}"
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{args.runs}] running {args.agent} against case '{args.case}' ...")
        progress = RunProgress(
            run_dir, args.agent, case,
            RunResult(None, run_dir / "transcript.jsonl", "", None, False, [], 0),
        )
        progress.checkpoint("provenance")
        try:
            progress.provenance = collect_provenance(
                args.agent, claude_cmd if args.agent == "claude" else codex_cmd, run_dir, args.model
            )
            result = do_run(
                case, args.agent, profile, args.shared_url, run_dir,
                claude_cmd, codex_cmd, args.timeout, model=args.model, progress=progress,
            )
            result.provenance = progress.provenance
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            # Persist partial evidence even when setup or post-run inspection fails.
            # Do not label an unperformed cleanliness check as success or failure.
            write_summary(
                run_dir, args.agent, case, progress.result, phase=progress.phase,
                failure={"type": type(exc).__name__, "message": str(exc)},
            )
            print(f"Run failed during {progress.phase}: {exc}", file=sys.stderr)
            return 130 if isinstance(exc, KeyboardInterrupt) else 1
        write_summary(run_dir, args.agent, case, result)
        results.append(result)
        print(
            f"  exit={result.returncode} clean={result.clean} "
            f"duration={result.duration_seconds:.1f}s -> {run_dir}"
        )
        if not result.clean:
            print(f"  changed files since adoption: {result.changed_paths}")
            print(f"  new Git status entries since adoption: {result.new_paths}")
        if result.skill_invocations is not None:
            print(f"  skill invocations: {result.skill_invocations}")

    clean_count = sum(1 for r in results if r.clean)
    print(f"\n{clean_count}/{len(results)} runs left the fixture worktree clean.")
    print(f"Results written under: {batch_dir}")
    print(
        "\nThis only records mechanical facts (exit code, cleanliness, skill "
        "calls, raw transcripts). Read each run's final_report.txt yourself "
        "to judge whether the response is behaviorally correct, then write "
        "the finding up in docs/cross-agent-validation.md by hand."
    )
    if args.strict and any(
        r.returncode != 0 or (case.name != "percentage-discount-commit" and not r.clean)
        for r in results
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
