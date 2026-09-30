# AGENTS.md

{{AGENT_RULES_METADATA}}

<!-- agent-rules-managed:start -->

This repository follows the shared agent rules from:

- {{SHARED_RULES_URL}}

Use this file as the repository-local instruction entrypoint.

If internet access is available, agents may consult the shared rules repository for detailed guidance. The rules below are the local summary that must be followed even when external links are not available.

## Agent Usage Model

Use agent roles as execution modes, not fixed tool identities.

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Use the mode requested by the task.

## Core Rules

- Investigate existing code, documentation, and behavior before editing.
- Keep changes scoped to the requested task.
- Preserve the agreed objective, authorized scope, and completion criteria across follow-ups. A status question does not cancel ongoing work; a short continuation resumes the agreed next step without expanding authorization.
- Separate explicitly requested additional work into stages or commits and keep it in the task; do not silently discard it as scope creep. Unrequested work stays out.
- For long-running work, retain a compact checkpoint of the repository, branch, execution environment, decisions, remaining steps, and latest evidence. Verify it against current state before resuming.
- Before performance experiments, define the baseline, target, allowed regressions, and experiment budget; stop or reassess when the budget is spent or evidence rejects the hypothesis.
- Before publishing a PR or release, inspect the destination repository's template and required submission procedure. Before merging, verify the intended head, required checks, and merge result.
- Never bypass commit signing, hooks, or required checks merely to make progress. Use an authorized working path or report the blocker; bypass requires an explicit user request.
- Do not refactor unrelated files, or rename public APIs, files, directories, or user-facing concepts, unless explicitly requested.
- Prefer simple, explicit, maintainable changes.
- After understanding the problem, prefer existing code, standard libraries, native platform features, and installed dependencies before new code, when they satisfy the required behavior and project conventions.
- Simplify implementation without dropping agreed requirements, compatibility, safety controls, or risk-appropriate validation; readable code matters more than minimum line counts.
- Preserve existing structure, naming, and documentation tone.
- Avoid new dependencies unless they have a clear, task-specific justification.
- Follow repository-local formatter, linter, test, PR template, and verification conventions.
- Consider risks, compatibility concerns, and validation gaps appropriate to the task.
- Ask for clarification before proceeding when scope is ambiguous, instructions conflict, or a destructive action lacks explicit authorization.

## Commit Messages

Use Conventional Commits:

```text
<type>[optional scope]: <description>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `style`, `perf`, `build`, `ci`, `chore`.

Use `!` or a `BREAKING CHANGE:` footer for compatibility-breaking changes.
Keep the subject concise, lowercase, imperative mood, no trailing period.

{{SHARED_SKILLS_SECTION}}

<!-- agent-rules-managed:end -->

## Repository-specific Boundaries

<!-- agent-rules-local:boundaries:start -->
{{REPOSITORY_SPECIFIC_BOUNDARIES}}
<!-- agent-rules-local:boundaries:end -->

## Validation

Before choosing commands, check repository-local scripts and configuration first.

<!-- agent-rules-local:validation_commands:start -->
{{VALIDATION_COMMANDS}}
<!-- agent-rules-local:validation_commands:end -->

Use conservative parallelism for local build or test validation when the environment is unknown. Prefer `-j2`, or `-j1` when memory pressure, OOM, VM/WSL constraints, embedded devices, or previous instability are involved.

If validation cannot be run, explain why and provide the command that should be run later.

## Final Report

For simple questions and progress updates, answer directly without mandatory headings.
For completed implementation or review reports, use the structure below. For PRs,
follow the destination repository template when one exists.

Before sending the response, verify that these Markdown headings appear verbatim, exactly once, and in this order; do not rename, omit, or combine them. Additional sections may appear after `## Changes` and before `## Validation`.

1. `## Summary`
2. `## Changes`
3. `## Validation`
4. `## Not Included`
5. `## Follow-up`

- **Summary**: what changed and why; begin with progress against the agreed plan
- **Changes**: files and behaviors affected
- **Validation**: what was run and results
- **Not Included**: what was intentionally left out
- **Follow-up**: known gaps or deferred work

For multi-step work, report completed stages out of the agreed total, the current
stage, remaining requested work, and blockers (or none) near the start of the
report, within Summary when that heading is required. Use meaningful stages and
completion evidence; do not invent percentages or split stages to inflate progress.
Stage counts describe scope completion, not elapsed time or effort. Include
requested PR, merge, or deployment steps before calling the whole task complete.
When additional requests change the plan, state the change and update the total;
do not silently drop unfinished work or count optional suggestions as requested work.
For small tasks, one sentence stating completion and remaining work is enough.
Progress reporting does not create a new approval gate or authorize extra actions.
