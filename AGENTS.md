# AGENTS.md

This is the shared entrypoint for coding agents used across `jwsung91` repositories.

Agents must follow the shared rules in `rules/` before making changes. In particular:

- Investigate the existing code, documentation, and behavior before editing.
- Keep changes scoped to the requested task.
- Do not refactor unrelated files or rename public APIs unless requested.
- Prefer simple, explicit, maintainable changes.
- Validate changes when possible with the narrowest relevant checks.
- Before committing, run lightweight checks for changed files when practical, such as `git diff --check`.
- Do not claim validation was run if it was not.
- Report what changed, what was intentionally not changed, and how the work was validated.

## Agent Usage Model

Agent roles are execution modes, not fixed tool identities.

Any supported agent may be used in either:

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Follow `rules/agent-collaboration.md` when multiple agents are used on the same task.

For structured task requests, use `templates/task-instruction-template.md`.
