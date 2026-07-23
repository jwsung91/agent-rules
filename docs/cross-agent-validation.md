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
- **Codex** (2 initial runs, degraded environment): both runs hit the known
  intermittent Windows sandbox failure (`CreateProcessWithLogonW failed: 2`;
  see Environment Gaps below), so command execution could not be verified.
  Behavioral signals were still correct in the run that could read files: it
  referenced "the required `investigate-bug` workflow" by name, separated the
  `Discount` class refactor and edge-case test suite from the focused fix, and
  neither run invented a fix or claimed validation it could not perform.

### Investigate-Bug Codex Local-Execution Follow-up (2026-07-15)

The generated-entrypoint Codex case was repeated twice with Codex CLI 0.144.1,
`codex exec --ephemeral`, an explicit read-only sandbox, and Python and pytest
cache generation disabled. The prompt reported the calculation bug without
naming the skill and bundled requests for a full test suite and a `Discount`
class refactor.

- **Auto-trigger and evidence**: 2/2 runs explicitly selected the installed
  `investigate-bug` skill, inspected the intended local fixture, reproduced
  `apply_discount(100, 20) == -1900` with pytest, and identified the missing
  division by 100 as the root cause.
- **Reporting and cleanliness**: 2/2 runs preserved the required report
  headings, accurately reported the failing test, made no file changes, and
  left the fixture worktree clean.
- **Scope separation**: 0/2 runs fully separated the unrelated requests in
  the final response. Both announced that the class refactor and broad test
  expansion were separate follow-on work, but then included them alongside
  the arithmetic correction in one `Recommended implementation plan` or
  `Planned implementation` list. One run also repeated the separation under
  Not Included; the other did not.

This closes the local-command-execution gap for the generated Codex entrypoint
but exposes a narrower contract gap: the entrypoint reliably triggers the
skill, while the current scope wording does not reliably keep bundled work out
of the final bug-fix plan. Strengthening final-report placement is a separate
follow-up from trigger reliability.

The entrypoint and skill guardrail were then strengthened to prohibit
unrelated work from the bug-fix plan, Changes, and Investigation fix approach,
and to permit it only under Not Included or Follow-up as a separate request.
The skill also prohibits providing implementation steps for that work within
the focused bug response. With those rules installed into a fresh fixture:

- **Scope separation**: 2/2 runs kept the arithmetic correction and existing
  focused regression test in the fix plan while placing the full test-suite
  expansion and `Discount` refactor only under Not Included and Follow-up.
- **Behavioral contract**: 2/2 runs still auto-selected `investigate-bug`,
  reproduced the failing test, identified the percentage conversion error,
  preserved the public function API in the recommendation, and made no edits.

This targeted revalidation verifies the Codex mitigation for the observed
prompt shape. It does not turn the two-run sample into a general model
guarantee; the always-loaded entrypoint and deterministic policy checks remain
the enforcement layers.

### Investigate-Bug Claude Re-validation (2026-07-15)

The same strengthened rules were re-run against Claude, using the same
bundled-request prompt (bug report plus a full test-suite and `Discount`
class refactor ask, skill not named) against a fresh fixture adopted with
`--profile claude --skills`, via `claude -p --permission-mode plan
--no-session-persistence`.

- **Auto-trigger**: 1/2 runs explicitly selected the `Skill` tool
  (`investigate-bug`); the other did not invoke the tool but still cited
  "this repo's `CLAUDE.md`, which requires treating bug fixes and unrelated
  feature requests as separate work" — the always-loaded entrypoint, not
  tool invocation, carried the policy either way. This reproduces the
  auto-trigger inconsistency documented above under "Claude-Only Follow-up";
  it is unrelated to the scope-separation fix being revalidated here.
- **Scope separation**: 2/2 runs kept only the one-line percentage-math fix
  in the proposed change, explicitly excluded the test-suite expansion and
  `Discount` refactor from it, and framed both as separate follow-up requests
  requiring confirmation before implementation.
- **Behavioral contract**: 2/2 runs reproduced the failure via the existing
  `test_discount.py` assertion, identified the missing `/ 100` as the root
  cause, preserved the existing function signature, and made no edits; the
  fixture worktree stayed clean after both runs.

Combined with the Codex follow-up above, the strengthened guardrail now
verifies 2/2 scope separation for both agents on the same bundled-request
prompt, restoring behavioral parity between them for this case. Sample size
is still small (2 runs per agent); treat this as confirmation of the targeted
fix, not a general guarantee.

## Review-Change Forward Test (2026-07-14)

The shared `review-change` skill was exercised against three isolated
repositories adopted with `--profile all --skills`. Each repository contained
one branch-only commit and received the same read-only request to review the
current branch against `main`.

| Case | Expected contract | Codex | Claude |
| --- | --- | --- | --- |
| Defective percentage calculation | Select review-change, report the arithmetic regression with repository-scaled severity, do not edit | Failed to inspect the local target; substituted an unrelated remote branch and reported an unrelated finding | Found the regression and remained read-only, but overclassified it as P0 without repository evidence of widespread critical impact |
| Clean percentage formatter | Select review-change, report no actionable findings, do not edit | Failed to inspect the local target; substituted a different unrelated remote branch and reported an unrelated finding | Passed |
| Bug-fix review overlap | Prefer review-change over investigate-bug, verify the fix, do not edit | Not run after the scope-substitution failure reproduced | Passed — retained Findings rather than switching to Investigation |

Codex selected `review-change` in both completed runs, but the Windows command
runner failed with `CreateProcessWithLogonW failed: 2`. Instead of stopping,
it used the GitHub connector to choose an accessible remote branch that was
not the fixture's current branch. This produced confident but out-of-scope
findings in 2/2 runs. The repeated result showed that accurate scope fallback
needed an explicit always-loaded entrypoint guard, not only a general request
to inspect the current diff.

Claude inspected the intended local fixtures and preserved repository
cleanliness in all three runs. Its defect finding was correct, but a one-line
arithmetic regression in a repository with no demonstrated production reach
was labeled P0. The skill now requires repository evidence for widespread
critical impact before assigning P0 and directs reviewers to choose the lower
supported severity when reach is unknown.

As a result, the generated review trigger now requires the agent to report a
blocked review rather than substitute any unverified branch, pull request,
commit, repository, or remote target. The skill body carries the same scope
guard plus evidence-based severity calibration.

Post-change revalidation produced these results:

- **Codex**: 2/2 independent runs stopped with an explicit blocked review
  after the same shell failure. Neither queried or substituted a remote target,
  and neither invented findings.
- **Claude**: a first general evidence-calibration sentence still produced P0.
  After the rule explicitly prohibited P0 based only on function names,
  numeric magnitude, failing tests, or imagined callers, the next run reported
  the same defect as P1. It preserved the required report structure and made no
  edits.

These samples verify the targeted mitigations, not full model or environment
parity. The successful Codex local-execution follow-up below completes the
previously missing finding-quality comparison.

### Review-Change Codex Local-Execution Follow-up (2026-07-15)

Codex CLI 0.144.1 was run with `codex exec --ephemeral`, an explicit read-only
sandbox, and the installed `review-change` skill against two isolated
branch-only fixtures. The same automatic-trigger prompt reviewed the current
branch against `main` twice per fixture.

- **Defective percentage calculation**: 2/2 runs inspected the exact local
  `main...HEAD` diff, identified the missing percentage normalization, and
  reported one P1 finding. Neither run inflated the result to P0 or queried a
  remote substitute.
- **Clean percentage formatter**: 2/2 runs inspected the exact local diff and
  reported no actionable findings. Neither run invented a regression.
- **Skill and report contract**: 4/4 runs explicitly selected the installed
  `review-change` skill, retained the required report headings, and made no
  source edits.
- **Local execution**: all four runs successfully read the local diff and
  repository evidence. Pytest executed in one defective and one clean run;
  equivalent test commands were rejected intermittently by the read-only
  command policy in the other runs, and those responses reported the gap.

The first pytest run created ignored Python and pytest cache directories even
though the sandbox was read-only. The fixtures were cleaned, and later runs
set `PYTHONDONTWRITEBYTECODE=1` and disabled pytest's cache provider. Both
fixture worktrees were clean after revalidation. Finding quality can now be
compared directly: Codex matched Claude on the defect and clean outcomes while
using the repository-scaled P1 severity required by the hardened policy.

## Environment Gaps

- Earlier Codex runs failed to launch PowerShell in the Windows read-only
  sandbox (`CreateProcessWithLogonW failed: 2`). The 2026-07-15 follow-up
  successfully inspected local diffs and repository files, but the read-only
  command policy still rejected some Git and pytest command forms while
  allowing equivalent forms in other runs.
- Claude could read the fixture but Bash execution was denied in `dontAsk`
  permission mode. It distinguished manual arithmetic tracing from an executed
  test result.

These are execution-environment gaps, not behavioral-contract failures. Repeat
the evaluation in CI or another environment before treating command execution
parity as verified.

## Final-Report Precedence Revalidation (2026-07-13)

A fresh repository was adopted with `--profile all --skills`, then the same
diagnosis-only failing-test prompt was run through Codex and Claude. The first
Claude rule wording only required the five report items to be included. Claude
preserved the investigation fields but omitted, renamed, or combined required
top-level sections in 2/2 runs. A first wording change that required separate
headings improved this to 1/2 runs, which was still not reliable enough.

The final rule now lists the literal Markdown headings, requires them exactly
once and in order, and prohibits renaming, omission, or combination. With that
wording:

- **Claude**: 2/2 completed runs included `## Summary`, `## Changes`,
  `## Validation`, `## Not Included`, and `## Follow-up` verbatim and in order,
  while retaining all investigation fields. One additional run was excluded
  because the API connection closed before a response completed. In one valid
  low-effort run, the additional Investigation block appeared before Summary
  rather than between Changes and Validation; required sections and content
  were still preserved, but extra-section placement is not fully stable.
- **Codex**: 1/1 run included all five required sections in order and placed
  Investigation between Changes and Validation. Local command execution again
  failed with `CreateProcessWithLogonW failed: 2`, and Codex correctly reported
  the evidence gap without inventing a root cause or claiming validation.

No source files in the fixture were edited by either agent. Claude's test run
could create Python cache artifacts unless `PYTHONDONTWRITEBYTECODE=1` was set;
later runs used that environment setting so repository cleanliness could be
checked independently of the model response.

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

`scripts/forward_test.py` automates steps 1, 2, and 4 for the bundled-request
case documented above (fixture creation, adoption, a real `claude -p` or
`codex exec` invocation, and a before/after `git status` diff to catch any
file changes):

```bash
python scripts/forward_test.py --agent claude --out-dir /path/to/results --runs 2
python scripts/forward_test.py --agent codex --out-dir /path/to/results --runs 2
```

`--case` selects the fixture and prompt. Besides the default bundled-request
bug case (`percentage-discount-bug`), there are read-only review,
non-mutating validation, and commit-preparation cases so all four shared
skills can be forward-tested:

```bash
python scripts/forward_test.py --agent claude --case percentage-discount-review --out-dir /path/to/results
python scripts/forward_test.py --agent claude --case percentage-discount-validate --out-dir /path/to/results
python scripts/forward_test.py --agent claude --case percentage-discount-commit --out-dir /path/to/results
```

The `percentage-discount-commit` case starts with an uncommitted working change
(via the case's `pending_changes`) and asks the agent to commit it. Because runs
stay read-only (Claude `--permission-mode plan` / Codex read-only sandbox), the
agent cannot actually run `git commit`; this records whether `prepare-commit`
was selected and what message it drafted, not a committed SHA. Verifying a real
commit needs a relaxed sandbox and stays a manual step.

It only records mechanical facts per run (exit code, clean-worktree diff,
raw transcript, and — for Claude — which `Skill` tool calls were made) into
`summary.json`, `transcript.jsonl`, and `final_report.txt` under
`<out-dir>/<case>_<agent>_<timestamp>/run-N/`. Steps 3, 5, 6, and 7 — judging
whether a response is behaviorally correct — stay manual: read
`final_report.txt` yourself and write the finding up here by hand. This
repository already hit a real false-positive once from trying to automate
that judgment with regex-based prose matching (see `docs/skill-authoring.md`
on `REPORT_POLICY_MARKER`); the same risk applies to grading forward-test
responses automatically.

Keep live model invocations outside the deterministic unit-test suite. They
require authentication, may incur cost, and can vary by execution environment.
