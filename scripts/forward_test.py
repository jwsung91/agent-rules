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
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ForwardTestCase:
    name: str
    files: dict[str, str]
    prompt: str


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
                "    return total - (total * rate_percent)\n"
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
    ),
}

AGENT_PROFILES = {"claude": "claude", "codex": "codex"}


@dataclass
class RunResult:
    returncode: int
    transcript_path: Path
    final_report: str
    skill_invocations: list[dict[str, str]] | None
    clean: bool
    new_paths: list[str]
    duration_seconds: float


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
    parser.add_argument("--runs", type=int, default=1, help="Number of repeated runs.")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory to write fixtures, transcripts, and summaries under.",
    )
    parser.add_argument("--claude-bin", default="claude", help="Override the claude executable (for testing).")
    parser.add_argument("--codex-bin", default="codex", help="Override the codex executable (for testing).")
    parser.add_argument("--timeout", type=int, default=240, help="Per-run timeout in seconds.")
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
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return 124, stdout, stderr
    return result.returncode, result.stdout, result.stderr


def build_fixture(case: ForwardTestCase, fixture_dir: Path) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in case.files.items():
        target = fixture_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_command(["git", "init", "-q"], fixture_dir, timeout=30)
    run_command(
        ["git", "-c", "user.email=forward-test@example.invalid", "-c", "user.name=Forward Test", "add", "-A"],
        fixture_dir,
        timeout=30,
    )
    run_command(
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
        timeout=30,
    )


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
    _, stdout, _ = run_command(["git", "status", "--short"], fixture_dir, timeout=30)
    return [line for line in stdout.splitlines() if line.strip()]


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


def run_claude(case: ForwardTestCase, fixture_dir: Path, run_dir: Path, claude_cmd: list[str], timeout: int) -> RunResult:
    transcript_path = run_dir / "transcript.jsonl"
    started = datetime.now(timezone.utc)
    code, stdout, stderr = run_command(
        [
            *claude_cmd,
            "-p",
            case.prompt,
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
    duration = (datetime.now(timezone.utc) - started).total_seconds()
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
        clean=True,  # filled in by caller after diffing git status
        new_paths=[],
        duration_seconds=duration,
    )


def run_codex(case: ForwardTestCase, fixture_dir: Path, run_dir: Path, codex_cmd: list[str], timeout: int) -> RunResult:
    transcript_path = run_dir / "transcript.jsonl"
    last_message_path = run_dir / "last_message.txt"
    started = datetime.now(timezone.utc)
    code, stdout, stderr = run_command(
        [
            *codex_cmd,
            "exec",
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
    duration = (datetime.now(timezone.utc) - started).total_seconds()
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


def do_run(
    case: ForwardTestCase,
    agent: str,
    profile: str,
    shared_url: str,
    run_dir: Path,
    claude_cmd: list[str],
    codex_cmd: list[str],
    timeout: int,
) -> RunResult:
    fixture_dir = run_dir / "fixture"
    build_fixture(case, fixture_dir)
    adopt_skills(fixture_dir, profile, shared_url)
    baseline = git_status_lines(fixture_dir)

    if agent == "claude":
        result = run_claude(case, fixture_dir, run_dir, claude_cmd, timeout)
    elif agent == "codex":
        result = run_codex(case, fixture_dir, run_dir, codex_cmd, timeout)
    else:
        raise SystemExit(f"Unsupported agent: {agent}")

    after = git_status_lines(fixture_dir)
    new_paths = [line for line in after if line not in baseline]
    result.new_paths = new_paths
    result.clean = not new_paths
    return result


def write_summary(run_dir: Path, agent: str, case: ForwardTestCase, result: RunResult) -> None:
    summary = {
        "agent": agent,
        "case": case.name,
        "prompt": case.prompt,
        "returncode": result.returncode,
        "duration_seconds": result.duration_seconds,
        "clean_worktree": result.clean,
        "new_paths_since_adoption": result.new_paths,
        "skill_invocations": result.skill_invocations,
        "transcript": str(result.transcript_path.relative_to(run_dir)),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    case = CASES[args.case]
    profile = args.profile or AGENT_PROFILES[args.agent]
    out_root = Path(args.out_dir).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_dir = out_root / f"{args.case}_{args.agent}_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    # posix=False: keeps backslashes literal, so a Windows path passed as an
    # override (e.g. in tests) isn't mangled the way POSIX-mode shlex would.
    claude_cmd = shlex.split(args.claude_bin, posix=False)
    codex_cmd = shlex.split(args.codex_bin, posix=False)

    results: list[RunResult] = []
    for index in range(1, args.runs + 1):
        run_dir = batch_dir / f"run-{index}"
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{args.runs}] running {args.agent} against case '{args.case}' ...")
        result = do_run(
            case,
            args.agent,
            profile,
            args.shared_url,
            run_dir,
            claude_cmd,
            codex_cmd,
            args.timeout,
        )
        write_summary(run_dir, args.agent, case, result)
        results.append(result)
        print(
            f"  exit={result.returncode} clean={result.clean} "
            f"duration={result.duration_seconds:.1f}s -> {run_dir}"
        )
        if not result.clean:
            print(f"  new paths since adoption: {result.new_paths}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
