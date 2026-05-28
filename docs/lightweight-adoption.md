# Lightweight Repository Adoption

Use this guide to apply `agent-rules` to a target repository without copying the full rules directory.

## Approach

Keep `agent-rules` as the shared source of truth.

In each target repository, add a small root-level `AGENTS.md` that includes:

- a link to `https://github.com/jwsung91/agent-rules`
- a short local summary of critical rules
- repository-specific boundaries
- repository-local validation commands
- final reporting expectations

This keeps the target repository lightweight while still giving agents enough local context to work safely.

## Why Not Link Only?

Some agents and execution environments may not automatically open external links.

For that reason, the target repository's `AGENTS.md` should include the most important rules locally, even if it links to the shared rule repository.

## Recommended Local `AGENTS.md` Structure

````md
# AGENTS.md

This repository follows the shared agent rules from:

- https://github.com/jwsung91/agent-rules

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
- Before committing, run lightweight checks for changed files, such as `git diff --check`.
- Use Conventional Commits for commit messages.
- Do not claim validation was run if it was not.
- Report what changed, what was intentionally not changed, validation results, and any test or documentation impact.

## Repository-local Conventions

Before choosing commands, check repository-local configuration and scripts first.

Look for files such as:

- formatter configuration
- linter configuration
- build presets
- PR templates
- formatter scripts
- verification scripts
- documented validation commands

Prefer repository-provided commands over generic commands.

## Repository-specific Boundaries

Add project-specific rules here.

Examples:

- public API compatibility expectations
- benchmark or performance data boundaries
- packaging impact expectations
- supported language or build conventions
- documentation update expectations

## Validation

List the preferred validation commands for this repository.

Examples:

```bash
git diff --check
# repository-specific build/test/verify commands
```

If validation cannot be run, explain why and provide the command that should be run later.

## Final Report

Include:

- Summary
- Changes
- Validation
- Not Included
- Test or documentation impact
- Follow-up
````

## Target Repository Guidance

When adding `AGENTS.md` to a target repository:

- Keep it short enough to be read quickly.
- Include only the most important shared rules.
- Add repository-specific boundaries and validation commands.
- Do not copy every file from `agent-rules`.
- Do not add `rules/`, `skills/`, scripts, or automation unless the target repository explicitly needs them.

## Usage Examples

Primary implementation task:

```text
Use Primary Mode.

Follow this repository's AGENTS.md.
If internet access is available, also consult https://github.com/jwsung91/agent-rules.

Keep the change scoped.
Validate with the narrowest relevant checks.
```

Review or cross-check task:

```text
Use Review Mode.

Follow this repository's AGENTS.md.
If internet access is available, also consult https://github.com/jwsung91/agent-rules.

Review for correctness, scope control, compatibility, repository-local convention compliance, and validation gaps.
Do not rewrite the implementation unless requested.
```
