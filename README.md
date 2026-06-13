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

This works better than linking to this repository only, because some agents and execution environments may not automatically open external links or may lose remote context during a task.

### Scripted adoption

For repeated use across repositories, prefer the Python helper script:

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --dry-run
python scripts/adopt-agent-rules.py /path/to/target-repo
```

Add optional tool-specific entrypoints:

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --entrypoints claude,gemini
```

Check an adopted repository:

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --check
```

See `docs/scripted-adoption.md` for safety options such as `--force`, `--backup`, custom `--boundary`, and custom `--validation`.

### Manual adoption

From the root of the target repository, add a short `AGENTS.md` based on `templates/target-AGENTS.md`, then edit repository-specific boundaries and validation commands.

Optional tool-specific files such as `CLAUDE.md` and `GEMINI.md` should stay thin and point back to `AGENTS.md` as the primary repository-local instruction file.

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
