# Commit Guidelines

Use Conventional Commits for commit messages.

## Format

```text
<type>[optional scope]: <description>
```

## Common Types

- `feat`: user-visible feature or capability
- `fix`: bug fix or behavior correction
- `docs`: documentation-only change
- `test`: test-only change
- `refactor`: internal restructuring without behavior change
- `style`: formatting or style-only change
- `perf`: performance improvement
- `build`: build system, packaging, or dependency change
- `ci`: CI configuration change
- `chore`: repository maintenance

## Scope

Use an optional scope when it helps clarify the affected area.

Examples:

```text
docs(agent): generalize agent usage modes
test(udp): add large payload regression test
fix(cmake): correct install target export
ci(vcpkg): update port validation workflow
build(conan): update package recipe
```

## Breaking Changes

Use `!` after the type or scope for compatibility-breaking changes:

```text
feat(api)!: rename transport builder option
```

Or include a footer:

```text
feat(api): rename transport builder option

BREAKING CHANGE: `set_timeout_ms` was renamed to `set_timeout`.
```

## Rules

- Keep the subject concise.
- Use lowercase type names.
- Prefer imperative mood.
- Do not end the subject with a period.
- Do not mix unrelated changes in one commit.
- Use `!` or `BREAKING CHANGE:` for compatibility-breaking changes.
- Mention validation in the PR body or final report, not necessarily in the commit title.
- Before committing, follow `rules/test-and-validation.md` for lightweight pre-commit checks.

## Branch Naming

Use the same type prefix as the primary commit:

```text
<type>/<short-description>
```

Examples:

```text
feat/add-transport-option
fix/udp-large-payload
docs/agent-usage-model
ci/vcpkg-port-validation
refactor/connection-pool
```

For agent-generated branches, prefix with the agent name:

```text
codex/adoption-helper-profiles
claude/fix-auth-middleware
```

Rules:

- Lowercase only.
- Use hyphens for spaces.
- Keep descriptions short and descriptive.
- Do not reuse branch names across unrelated tasks.

## Recommended Types by Change

- Documentation-only changes: `docs`
- Test-only changes: `test`
- CI workflow changes: `ci`
- Build, packaging, or dependency changes: `build`
- Repository housekeeping: `chore`
- Behavior fixes: `fix`
- User-visible capabilities: `feat`
