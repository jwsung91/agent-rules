# agent-rules

Shared working rules, agent entrypoints, and task templates for AI coding agents used across `jwsung91` repositories.

## Purpose

This repository defines common working rules for AI coding agents. It is intended to keep agent behavior consistent across repositories, especially for engineering judgment, task scope control, validation, documentation, and pull request discipline.

Supported agents:

- Codex
- Claude
- Gemini

## Directory Overview

- `AGENTS.md`: Shared coding agent entrypoint.
- `CLAUDE.md`: Claude-specific entrypoint.
- `GEMINI.md`: Gemini-specific entrypoint.
- `docs/lightweight-adoption.md`: Guide for applying these rules to target repositories using a lightweight local `AGENTS.md` and optional `.agents/` namespacing.
- `docs/scripted-adoption.md`: Usage guide for the Python adoption helper script.
- `scripts/adopt-agent-rules.py`: Helper script for creating or checking lightweight target-repository adoption files.
- `rules/agent-collaboration.md`: Primary/Review mode and multi-agent collaboration rules.
- `rules/commit-guidelines.md`: Conventional Commits-style commit message rules.
- `rules/`: Shared rules that apply across agents.
- `templates/`: Reusable task, review, and target-repository adoption templates.

## Agent Usage Model

Agent roles are execution modes, not fixed tool identities.

Any supported agent may be used in either:

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Actual agent assignment should be decided per task. This repository intentionally avoids environment-specific assumptions.

## Quick Start: Use These Rules in a Target Repository

The recommended adoption model is **lightweight local adoption**:

1. Keep this repository as the shared source of truth.
2. Add a short root-level `AGENTS.md` to each target repository.
3. Put only the highest-signal rules, repository-specific boundaries, and validation commands in that local file.
4. Explicitly tell the coding agent to follow the target repository's `AGENTS.md` when starting a task.

This works better than linking to this repository only, because some agent environments may not automatically open external links or may lose remote context during a task.

### Scripted adoption

For repeated use across repositories, prefer the Python helper script:

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --plan
python scripts/adopt-agent-rules.py /path/to/target-repo --profile codex --dry-run
python scripts/adopt-agent-rules.py /path/to/target-repo --profile codex
```

Choose the profile that matches the target repository workflow:

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --profile codex   # AGENTS.md
python scripts/adopt-agent-rules.py /path/to/target-repo --profile claude  # AGENTS.md + CLAUDE.md
python scripts/adopt-agent-rules.py /path/to/target-repo --profile gemini  # AGENTS.md + GEMINI.md
python scripts/adopt-agent-rules.py /path/to/target-repo --profile multi   # all entrypoints
```

Check and update an adopted repository:

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --check
python scripts/adopt-agent-rules.py /path/to/target-repo --check-latest
python scripts/adopt-agent-rules.py /path/to/target-repo --profile claude --update --dry-run
python scripts/adopt-agent-rules.py /path/to/target-repo --profile claude --update
```

Use `--local-copy` only when the target repository needs offline or pinned access. The helper copies under `.agents/agent-rules/` only; do not copy shared `rules/` or `templates/` to the target repository root.

See `docs/scripted-adoption.md` for `--merge`, `.gitignore` collision handling, `--detect`, `--force`, `--backup`, custom `--boundary`, and custom `--validation`.

### 1. Add `AGENTS.md` to the target repository

From the root of the target repository:

```bash
cat > AGENTS.md <<'EOF'
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
- Use resource-safe build and test commands; avoid full-core parallelism by default.
- Before committing, run lightweight checks for changed files, such as `git diff --check`.
- Use Conventional Commits for commit messages.
- Do not claim validation was run if it was not.
- Report what changed, what was intentionally not changed, validation results, and any test or documentation impact.

## Repository-specific Boundaries

Add project-specific rules here.

Examples:

- public API compatibility expectations
- benchmark or performance data boundaries
- packaging impact expectations
- supported language or build conventions
- documentation update expectations

## Validation

Before choosing commands, check repository-local scripts and configuration first.

Preferred checks for this repository:

```bash
git diff --check
# Add project-specific build/test/lint commands here.
```

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
EOF
```

Then edit the placeholders and commit it:

```bash
git add AGENTS.md
git commit -m "docs(agent): adopt shared agent rules"
```

### 2. Add optional agent-specific entrypoints

Use these only when a specific tool or workflow expects a tool-specific file. Keep them thin so the root `AGENTS.md` stays the source of repository-local truth.

```bash
cat > CLAUDE.md <<'EOF'
# CLAUDE.md

Follow `AGENTS.md` as the primary repository instruction file.

If internet access is available, also consult:

- https://github.com/jwsung91/agent-rules
EOF

cat > GEMINI.md <<'EOF'
# GEMINI.md

Follow `AGENTS.md` as the primary repository instruction file.

If internet access is available, also consult:

- https://github.com/jwsung91/agent-rules
EOF

git add CLAUDE.md GEMINI.md
git commit -m "docs(agent): add agent-specific entrypoints"
```

### 3. Optional: keep a local copy or pinned reference

Most repositories should not copy this entire repository. Prefer the short root `AGENTS.md` above.

Use a local copy only when the target repository needs offline access, pinned rules, or local agent-specific templates.

Recommended layout:

```text
target-repo/
  AGENTS.md
  .agents/
    agent-rules/
      SOURCE_COMMIT
      rules/
      templates/
```

Do **not** copy root-level `rules/` or `templates/` directly into a target repository unless that repository is dedicated to agent instructions. Those names may conflict with project domain rules, issue templates, documentation templates, or generated artifacts.

If you want a pinned reference instead of copying files, use a submodule under `.agents/`:

```bash
mkdir -p .agents
git submodule add https://github.com/jwsung91/agent-rules .agents/agent-rules
git commit -m "docs(agent): add shared agent rules reference"
```

Use this only when submodule maintenance is acceptable for the target repository.

### 4. Start tasks with an explicit mode and instruction source

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

Commit preparation task:

```text
Prepare a commit for the current changes.

Follow AGENTS.md and use Conventional Commits.
Before committing, check the diff and run lightweight validation that is relevant to the changed files.
Do not include unrelated changes.
```

### 5. Keep target repositories updated

For lightweight adoption, update the target repository's root `AGENTS.md` when these shared rules change in a way that affects daily work.

For `.agents/` copies, periodically refresh only the files that are actually used by that repository.

For submodules:

```bash
git submodule update --remote .agents/agent-rules
git add .agents/agent-rules
git commit -m "docs(agent): update shared agent rules reference"
```

## Recommended Usage

For most repositories:

1. Add a root-level `AGENTS.md` using the lightweight template or the adoption script.
2. Add repository-specific validation commands and boundaries.
3. Explicitly mention `AGENTS.md` and the desired mode when assigning agent tasks.
4. Use the templates in `templates/` when preparing task instructions or pull request review requests.
5. Use `rules/commit-guidelines.md` when preparing commits or instructing agents to commit changes.

Use `.agents/` namespacing only when local rule or template files are needed. Avoid adding root-level `rules/`, `skills/`, scripts, or automation unless the target repository explicitly needs them.

## Effectiveness Review

This repository is useful as a **soft-control layer** for agent behavior. It can improve consistency, but it is not a substitute for CI, tests, code review, or repository permissions.

It is most effective when:

- The target repository has a short root-level `AGENTS.md` that the agent can read locally.
- The task prompt explicitly says which mode to use: Primary Mode or Review Mode.
- Repository-specific validation commands are listed directly in the target repository.
- The rules are short enough to stay in context and specific enough to affect behavior.
- Review Mode is used for non-trivial changes, public API changes, build/package changes, security-sensitive changes, or changes with unclear validation coverage.

It is weak when:

- The target repository only links to this repository without a local summary.
- The agent is not told to read or follow the instruction file.
- The rules are too broad, too long, or conflict with repository-local conventions.
- There are no concrete validation commands.
- Teams expect the rules to enforce behavior automatically.

Practical judgment:

- **Worth using:** Yes, especially as a lightweight `AGENTS.md` convention across multiple repositories.
- **Expected benefit:** Better scope control, more consistent validation reporting, less accidental refactoring, clearer commit discipline, and cleaner review handoffs.
- **Main limitation:** Compliance depends on the agent loading and following the file. Hard guarantees still require automated checks, branch protections, human review, and clear repository permissions.
- **Best operating model:** Keep this repository as the shared source of truth, keep each target repository's `AGENTS.md` short and local, and use CI/review processes for enforcement.

## Verification Checklist for Target Repositories

Before considering a target repository adopted, check that:

- `AGENTS.md` exists at the repository root.
- It links to this repository.
- It includes local summaries of the most important shared rules.
- It lists repository-specific boundaries.
- It lists concrete validation commands.
- Task prompts mention Primary Mode or Review Mode.
- Final reports include validation status and any intentionally skipped checks.

This repository intentionally focuses on rules, templates, and lightweight adoption helpers. It does not define full agent skills, CI, package metadata, or runtime automation.
