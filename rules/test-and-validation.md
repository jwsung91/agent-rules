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

## Resource-safe Validation

Prefer resource-safe validation, especially for C++, CMake, ROS 2, embedded, WSL, virtualized, or resource-limited environments.

- Run the narrowest relevant build or test target first.
- Use conservative parallelism by default when the environment is unknown.
- Prefer `-j2` for local validation when no repository-specific safe default is documented.
- Use `-j1` when memory pressure, OOM, kernel instability, VM/WSL constraints, or embedded devices are involved.
- Do not use all detected CPU cores by default.
- If using detected CPU cores, apply a conservative upper bound such as `min(detected_cores, 2)` or `min(detected_cores, 4)`.
- Increase parallelism only when the environment is known to be stable and has enough memory.
- Do not run full builds, full test suites, sanitizers, benchmarks, and documentation builds together unless required.
- Split validation into smaller steps when a command may consume excessive memory or CPU.
- If a previous command caused OOM, kernel instability, system reset, or severe slowdown, do not repeat it unchanged.
- Report resource-related failures separately from code failures.
- If full validation is unsafe or impractical, report the narrower validation performed and provide the full command that should be run in a suitable environment.

## Pre-commit Checks

Before committing, run lightweight checks appropriate to the files changed by the task when practical.

Prefer checking only changed files or the smallest affected area.

Prefer repository-provided formatter, linter, test, and verification commands over generic commands.

Before choosing commands, look for repository-local conventions such as formatter configs, lint configs, build presets, documented validation commands, verification scripts, and PR templates.

If the repository provides an official verification script or documented validation command, prefer that command for pre-PR validation unless the task scope or environment makes it impractical.

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
