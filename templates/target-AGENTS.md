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
- Do not refactor unrelated files, or rename public APIs, files, directories, or user-facing concepts, unless explicitly requested.
- Prefer simple, explicit, maintainable changes.
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

{{REPOSITORY_SPECIFIC_BOUNDARIES}}

## Validation

Before choosing commands, check repository-local scripts and configuration first.

{{VALIDATION_COMMANDS}}

Use conservative parallelism for local build or test validation when the environment is unknown. Prefer `-j2`, or `-j1` when memory pressure, OOM, VM/WSL constraints, embedded devices, or previous instability are involved.

If validation cannot be run, explain why and provide the command that should be run later.

## Final Report

Include:

- Summary
- Changes
- Validation
- Not Included
- Test or documentation impact
- Follow-up
