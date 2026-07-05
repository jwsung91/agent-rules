# AGENTS.md

This is the shared entrypoint for coding agents used across `jwsung91` repositories.
Agents must follow the shared rules in `rules/` before making changes.

## Agent Usage Model

Agent roles are execution modes, not fixed tool identities.

- **Primary Mode**: implementation, documentation update, investigation, or refactoring.
- **Review Mode**: cross-check, review, risk analysis, and validation gap review.

Use the mode requested by the task. Follow `rules/agent-collaboration.md` when multiple agents are used on the same task.

## Core Rules

- Investigate existing code, documentation, and behavior before editing.
- Keep changes scoped to the requested task.
- Do not refactor unrelated files, or rename public APIs, files, directories, or user-facing concepts, unless explicitly requested.
- Prefer simple, explicit, maintainable changes.
- Preserve existing structure, naming, and documentation tone.
- Avoid new dependencies unless they have a clear, task-specific justification.
- Follow repository-local formatter, linter, test, PR template, and verification conventions.
- Consider risks, compatibility concerns, and validation gaps appropriate to the task.
- Ask for clarification before proceeding when scope is ambiguous, instructions conflict, or a destructive action lacks explicit authorization. See `rules/clarification-protocol.md`.

## Commit Messages

Use Conventional Commits:

```text
<type>[optional scope]: <description>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `style`, `perf`, `build`, `ci`, `chore`.

Use `!` or a `BREAKING CHANGE:` footer for compatibility-breaking changes.
Keep the subject concise, lowercase, imperative mood, no trailing period.
Use `rules/commit-guidelines.md` for full detail.

## Validation

- Run the narrowest relevant checks first.
- Add or update tests when behavior changes; explain when not.
- Do not claim validation was run if it was not.
- Before committing, run at minimum: `git diff --check`.
- Use resource-safe parallelism: prefer `-j2` by default, `-j1` under memory pressure or resource-constrained environments (e.g., WSL, VMs).

Report validation using this format:

```text
Validation:
- [x] Ran: ...
- [ ] Not run: ... because ...
- Tests: added / updated / not needed / not added because ...
- Documentation: updated / not needed / not updated because ...
```

## Final Report

Include in every final response or PR summary:

- **Summary**: what changed and why
- **Changes**: files and behaviors affected
- **Validation**: what was run and results
- **Not Included**: what was intentionally left out
- **Follow-up**: known gaps or deferred work

For structured task requests, use `templates/task-instruction-template.md`.
