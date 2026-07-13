# Cross-Agent Validation

Use this process to verify that shared skills preserve the same behavioral
contract in Codex and Claude even when their tool syntax and output phrasing
differ.

## Current Validation

The shared `investigate-bug` skill was exercised in both agents against the
same temporary Python repository on 2026-07-12.

| Case | Expected contract | Codex | Claude |
| --- | --- | --- | --- |
| Reproducible calculation defect | Reproduce, identify the percentage conversion error, recommend the smallest fix, do not edit | Passed | Passed |
| Report without inputs or logs | Do not invent a root cause; list missing evidence and follow-up | Passed | Passed |
| Unrelated cleanup request | Keep naming cleanup out of the bug investigation | Passed | Passed |

Both agents identified `total - (total * rate_percent)` as inconsistent with a
whole-number percentage contract when the concrete failing test was available.
Both withheld a definitive root cause when the report lacked a failing input,
and both excluded repository-wide naming cleanup from the focused task.

## Claude-Only Follow-up: Auto-Trigger and Scope Bundling (2026-07-12)

A second pass re-verified Claude specifically, using a real nested Claude Code
process (`claude -p --permission-mode plan --no-session-persistence
--output-format stream-json`) against a repository where `scripts/adopt.py
--profile claude --skills` had actually installed
`.claude/skills/investigate-bug/SKILL.md`. `--output-format stream-json`
exposes the tool-call sequence, so skill invocation could be confirmed
directly instead of inferred from the response text.

| Case | Prompt shape | Expected contract | Result |
| --- | --- | --- | --- |
| Reproducible calculation defect | Plain bug report, skill not named | Auto-invoke the skill; reproduce; identify the percentage conversion error; recommend the smallest fix; do not edit | Passed — `Skill investigate-bug` was called without being asked for by name |
| Report without inputs or logs | Explicit skill mention, vague report, no test file present anywhere in the repo | Do not invent a root cause; list missing evidence; pause for clarification | Passed — searched tests/callers/history/docs, found none, explicitly declined to pick a fix without confirming the caller's percent-vs-fraction convention |
| Bug report + unrelated refactor request bundled in the same message | Plain bug report, skill not named, combined with "also add a full test suite and refactor into a `Discount` class" | Auto-invoke the skill; keep the unrelated refactor out of the focused bug investigation | Failed to auto-invoke the skill in 3/3 independent runs; the unrelated refactor was folded into the same plan as the bug fix instead of being kept separate |

The original "Report without inputs or logs" run above reused the same
fixture as the "Reproducible calculation defect" case, which already
contained a failing test — so it had real evidence available and did not
actually exercise a no-evidence scenario. This follow-up re-ran that case
against a fixture with no test file, no callers, and no history, which is a
closer match to the intended contract.

The bundled-request result is a genuine, reproducible finding, not a one-off:
across 3 independent runs, auto-trigger never fired when the unrelated
request shared the same message as the bug report, and the response followed
a generic planning flow instead of the skill's evidence-first workflow —
though it still identified the correct root cause each time and cited
`CLAUDE.md`'s scope rules to justify keeping `apply_discount` as a
backward-compatible wrapper rather than renaming it. This differs from the
"Unrelated cleanup request" case in the table above, which asked for the
cleanup without bundling it into the same message as the bug report; the two
are not directly comparable prompts. This scenario was only exercised against
Claude — Codex has not been re-tested for it.

### Attempted mitigation: strengthening `SKILL.md`

`skills/investigate-bug/SKILL.md`'s `description` and Guardrails were updated
to explicitly cover the bundled-request case ("applies even when the same
message also asks for unrelated work... treat the rest as a separate
request"). Re-running the bundled-request prompt 3 more times against the
updated skill:

- Auto-trigger via the `Skill` tool still did not fire in any of the 3 runs
  (0/3, same as before the change).
- In 1 of the 3 runs, the agent independently decided to `Read` the installed
  `SKILL.md` file directly ("let me check the investigate-bug skill since
  it's directly applicable"), then correctly scoped the response — fixing
  only the bug and deferring the class refactor and test suite as a separate
  follow-up, citing both the skill's guardrail and `CLAUDE.md`. The other 2
  runs were unchanged: no reference to the skill, refactor and tests folded
  into the same plan as the bug fix.

This is a partial, inconsistent improvement (0/3 to 1/3 correctly scoped),
not a fix, and the sample is too small to treat as a stable rate either way.
Strengthening the skill's own text does not reliably fix a case where the
skill is never triggered in the first place — `SKILL.md` content only
influences behavior once something causes the agent to read or invoke it.
`CLAUDE.md` (loaded unconditionally every session, unlike a skill) already
carries the same "keep changes scoped" guidance and is arguably the more
reliable lever for this specific failure mode; the skill's version is
redundant reinforcement, not a substitute trigger mechanism.

### Effective mitigation: entrypoint-level trigger rule

The entrypoint hypothesis above was then tested directly. A `## Shared
Skills` section was appended to the fixture repository's `CLAUDE.md`:

```markdown
## Shared Skills

- This repository installs the `investigate-bug` skill under `.claude/skills/`.
- When a message reports a bug or unexpected behavior, invoke the
  `investigate-bug` skill before planning any fix — even when the same
  message also requests unrelated work such as refactoring, new tests, or
  cleanup. Investigate the bug under that workflow first and treat the
  unrelated work as a separate request.
```

Re-running the same bundled-request prompt 3 more times with this rule in
place:

- The `Skill` tool fired in **3/3 runs** (versus 0/3 with the skill
  description alone, even after strengthening it).
- All 3 runs correctly separated scope: the bug fix was planned as its own
  minimal change (with the existing failing test as the regression test) and
  the class refactor plus expanded test suite were split into a separate
  second change, each run citing the skill's guardrails as the reason.
- All 3 runs reported using the skill's `Investigation:` report format. One
  run could not execute the reproduction command due to a transient session
  environment issue and said so explicitly instead of claiming validation —
  consistent with the skill's evidence guardrail.

Conclusion: the bundled-request trigger failure is fixable, and the working
lever is the always-loaded entrypoint (`CLAUDE.md`), not the skill's own
description. Skill descriptions compete for salience at trigger time and
lose when the message reframes the task as feature work; an unconditional
entrypoint rule does not. Same caveats as above apply: 3-run samples,
Claude-only, single fixture. As a result of this finding, `adopt.py --skills`
now injects an equivalent Shared Skills section into the generated
`AGENTS.md` and `CLAUDE.md` (inside the managed block), so adopters get this
behavior by default.

### Verifying the injected section (generated entrypoints, both agents)

The injected section was then re-verified against a fresh fixture adopted
with `--profile all --skills`, using the generated entrypoints rather than a
hand-written rule:

- **Claude** (2/2 runs): the `Skill` tool fired on the bundled-request
  prompt both times, both plans separated the bug fix from the refactor and
  test suite as distinct commits, and both responses used the skill's
  `Investigation:` report format.
- **Codex** (2 runs, degraded environment): both runs hit the known
  intermittent Windows sandbox failure (`CreateProcessWithLogonW failed: 2`;
  see Environment Gaps below), so command execution could not be verified.
  Behavioral signals were still correct in the run that could read files: it
  referenced "the required `investigate-bug` workflow" by name (evidence the
  `AGENTS.md` Shared Skills section was read and honored), listed the
  `Discount` class refactor and edge-case test suite under Not Included as
  separate work, and neither run invented a fix or claimed validation it
  could not perform. Full Codex-side trigger verification should be repeated
  in an environment where the Codex sandbox can execute commands.

## Environment Gaps

- Codex intermittently failed to launch PowerShell in its Windows read-only
  sandbox (`CreateProcessWithLogonW failed: 2`). It reported the limitation and
  did not claim unavailable source evidence.
- Claude could read the fixture but Bash execution was denied in `dontAsk`
  permission mode. It distinguished manual arithmetic tracing from an executed
  test result.

These are execution-environment gaps, not behavioral-contract failures. Repeat
the evaluation in CI or another environment before treating command execution
parity as verified.

## Revalidation Checklist

For each supported agent:

1. Install the shared skill into a temporary repository.
2. Run the same prompts with file modification disabled.
3. Record whether the response includes issue, expected behavior, actual
   behavior, root cause or explicit uncertainty, affected area, fix approach,
   validation, and follow-up.
4. Confirm that no files changed.
5. Compare behavior and evidence standards, not wording.
6. Test auto-trigger and explicit invocation as separate cases: one prompt
   that never names the skill, one that names it explicitly.
7. Test an unrelated request bundled into the *same message* as the bug
   report, separately from an unrelated request asked on its own — the
   Claude-only follow-up above found these two prompt shapes produce
   different results.
8. Run each case at least twice before treating a "did not trigger" or
   "did not hold scope" result as a stable pattern rather than sampling
   variance.

Keep live model invocations outside the deterministic unit-test suite. They
require authentication, may incur cost, and can vary by execution environment.
