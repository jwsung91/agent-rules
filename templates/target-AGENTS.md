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
- Do not refactor unrelated files.
- Do not rename public APIs, files, directories, or user-facing concepts unless explicitly requested.
- Prefer simple, explicit, maintainable changes.
- Follow repository-local formatter, linter, test, PR template, and verification conventions.
- Validate changes with the narrowest relevant checks when practical.
- Use resource-safe build and test commands; avoid full-core parallelism by default.
- Before committing, run lightweight checks for changed files, such as `git diff --check`.
- Use Conventional Commits for commit messages.
- Do not claim validation was run if it was not.
- Report what changed, what was intentionally not changed, validation results, and any test or documentation impact.

<!-- agent-rules-managed:end -->

## Repository-specific Boundaries

{{REPOSITORY_SPECIFIC_BOUNDARIES}}

## Validation

Before choosing commands, check repository-local scripts and configuration first.

Preferred checks for this repository:

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
