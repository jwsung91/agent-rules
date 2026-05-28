# Test and Validation

Use validation that is appropriate to the size and risk of the change.

- Run the narrowest relevant checks first.
- Add or update tests when behavior changes.
- If behavior changes but tests are not added, explain why.
- Check whether user-facing behavior, public APIs, configuration, commands, or workflows require documentation updates.
- Treat missing or outdated documentation as a validation gap when the change affects how users or maintainers work.
- Prefer deterministic tests.
- Avoid hardware-specific, environment-specific, or timing-sensitive assumptions unless the task requires them.
- Do not claim tests, checks, builds, or manual validation were run if they were not.
- If validation cannot be run, explain why and provide the commands that should be run.
- Report failures clearly, including whether they are related to the change.

Use this summary format:

```text
Validation:
- [x] Ran: ...
- [ ] Not run: ... because ...
- Tests: added, updated, not needed, or not added because ...
- Documentation: updated, not needed, or not updated because ...
```

## Pre-commit Checks

Before committing, run lightweight checks appropriate to the files changed by the task when practical.

Prefer checking only changed files or the smallest affected area.

Recommended baseline:

```bash
git diff --check
```

If the repository defines formatters, linters, or test commands, use the narrowest relevant command for the changed files or affected area.

Examples:

```bash
# C++ formatting check, when clang-format is configured
clang-format --dry-run --Werror <changed-files>

# Python formatting/lint check, when Ruff is configured
ruff format --check <changed-files>
ruff check <changed-files>

# Markdown or web documentation formatting check, when Prettier is configured
npx prettier --check <changed-files>
```

Do not run broad repository-wide formatting unless explicitly requested.

Do not include unrelated formatting changes in the same commit.

If checks cannot be run, report why and provide the command that should be run later.
