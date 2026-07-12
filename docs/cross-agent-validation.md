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

Keep live model invocations outside the deterministic unit-test suite. They
require authentication, may incur cost, and can vary by execution environment.
