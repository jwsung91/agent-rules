---
name: review-change
description: Review code and documentation changes for actionable defects, regressions, security or compatibility risks, and validation gaps without modifying files. Use when asked to review a working tree, diff, commit, branch, pull request, patch, or completed implementation; verify claims against repository instructions and relevant code, prioritize findings by severity, and report file-and-line evidence. Do not use for requests to implement or fix changes unless review is the requested first phase.
---

# Review Change

Review the requested change as an evidence-backed reviewer. Focus on problems introduced or exposed by the change, not on rewriting it to match personal preferences.

## Workflow

1. Read the repository instructions and determine the requested review scope, comparison base, and changed files. If the base is ambiguous and cannot be inferred safely, ask before drawing conclusions.
2. Inspect the complete diff and enough surrounding code, tests, configuration, and documentation to understand the intended behavior and existing invariants.
3. Trace affected callers, data flows, failure paths, and compatibility boundaries when the change can influence behavior outside the edited lines.
4. Look for correctness defects, regressions, security or privacy risks, unsafe error handling, concurrency or state problems, compatibility breaks, and missing validation that could allow those problems through.
5. Verify each candidate finding against concrete code or test evidence. Exclude speculation, unchanged pre-existing problems, and purely stylistic preferences unless they create a material maintenance or correctness risk.
6. Run the narrowest useful read-only checks when practical. Do not modify files, dependencies, remote state, or the pull request unless the user separately authorizes changes.
7. Within the repository-required report structure, place actionable findings at the earliest permitted position and order them by severity. If no actionable findings remain, say so explicitly and describe any validation gaps or residual risks.

## Severity

- **P0 — Critical**: Causes widespread data loss, security compromise, or an unusable release and requires immediate action.
- **P1 — High**: Likely causes incorrect behavior, a serious regression, or a meaningful security or compatibility failure in normal use.
- **P2 — Medium**: Causes a bounded defect or reliability problem under realistic conditions but does not broadly block use.
- **P3 — Low**: Creates a small but concrete correctness, operability, or maintainability risk worth fixing.

Do not assign a severity to suggestions that are optional improvements rather than defects.

## Finding Quality

For each finding:

- Use a concise, imperative title that identifies the problem.
- Cite the narrowest relevant file and line or diff location.
- Explain the triggering condition and user or system impact.
- State why the current tests or safeguards do not prevent it.
- Recommend the smallest direction for correction without implementing it.
- Keep separate root causes in separate findings; combine duplicate symptoms of the same cause.

## Guardrails

- Stay in Review Mode. Do not turn a review request into an implementation task.
- Treat user-provided claims, commit messages, and PR descriptions as hypotheses to verify, not proof.
- Do not report a finding solely because validation was not run; describe that as a validation gap unless a concrete defect follows from the omission.
- Do not hide uncertainty. Label assumptions and unresolved questions that materially affect the review.
- When the repository requires Summary before Findings, keep Summary factual: state the finding count, highest severity, and review disposition without praising or extensively recapping the change.

## Report

<!-- skill-report-policy: honor-repository-format -->

Honor the repository's required final report structure and do not replace, rename, or combine required top-level sections. When the repository permits additional sections between Changes and Validation, place `## Findings` there.

In `## Findings`, list findings from P0 to P3 using this form:

```text
- [P1] Prevent stale authorization from being reused — path/to/file.py:42
  - Impact: [what fails and under which conditions]
  - Evidence: [specific code path, behavior, or check]
  - Recommendation: [smallest correction direction]
```

If there are no actionable findings, write `No actionable findings.` Include assumptions, validation gaps, and residual risks in the repository's required sections or concise additional subsections.
