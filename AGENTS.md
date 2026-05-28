# AGENTS.md

This is the Codex and generic coding agent entrypoint for `jwsung91` repositories.

Agents must follow the shared rules in `rules/` before making changes. In particular:

- Investigate the existing code, documentation, and behavior before editing.
- Keep changes scoped to the requested task.
- Do not refactor unrelated files or rename public APIs unless requested.
- Prefer simple, explicit, maintainable changes.
- Validate changes when possible with the narrowest relevant checks.
- Do not claim validation was run if it was not.
- Report what changed, what was intentionally not changed, and how the work was validated.

For structured task requests, use `templates/task-instruction-template.md`.
