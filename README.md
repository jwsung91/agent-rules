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
- `docs/claude-codex-workflow.md`: Guide for running Codex and Claude together on the same repository.
- `scripts/adopt.py`: Helper script for creating or checking lightweight target-repository adoption files.
- `scripts/generate_batch_list.py`: Builds a `repos.toml`/`repos.txt` batch file by scanning a root folder for Git repositories.
- `rules/agent-collaboration.md`: Primary/Review mode and multi-agent collaboration rules.
- `rules/commit-guidelines.md`: Conventional Commits-style commit message rules.
- `rules/`: Shared rules that apply across agents.
- `templates/`: Reusable task, review, and target-repository adoption templates.
- `.github/workflows/tests.yml`: CI workflow that runs the test suite under `tests/` on push and pull request.

## Agent Usage Model

Agent roles are execution modes, not fixed tool identities.

Any supported agent may be used in either:

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Actual agent assignment should be decided per task. This repository intentionally avoids environment-specific assumptions.

## Quick Start: Use These Rules in a Target Repository

The recommended adoption model is **lightweight local adoption**:

1. Keep this repository as the shared source of truth.
2. Add a root-level agent entrypoint to each target repository using the adoption script. The script automatically adds the entrypoint to `.gitignore` — agent files are local-only and not committed.
3. Add repository-specific boundaries and validation commands.
4. Explicitly tell the coding agent to follow the entrypoint file when starting a task.

This works better than linking to this repository only, because some agent environments may not automatically open external links or may lose remote context during a task.

### Scripted adoption

Use `scripts/adopt.py` to create or manage agent entrypoints. Choose the profile for the agent used in that repository:

```bash
python scripts/adopt.py /path/to/repo --profile codex   # AGENTS.md only
python scripts/adopt.py /path/to/repo --profile claude  # CLAUDE.md only
python scripts/adopt.py /path/to/repo --profile gemini  # GEMINI.md only
python scripts/adopt.py /path/to/repo --profile all     # all three files
```

Preview before applying:

```bash
python scripts/adopt.py /path/to/repo --profile claude --dry-run
```

Check and update an existing adoption:

```bash
# Health check (exit 0 clean, 1 on FAIL, 2 on WARN-only)
python scripts/adopt.py /path/to/repo --check

# Sync after updating agent-rules (update or merge automatically)
python scripts/adopt.py /path/to/repo --sync
python scripts/adopt.py /path/to/repo --sync --dry-run
```

Apply to multiple repositories at once using a batch file. Build one by scanning a parent folder for Git repos with `scripts/generate_batch_list.py`:

```bash
python scripts/generate_batch_list.py /path/to/workspace --output repos.toml
```

Or write it by hand:

```toml
# repos.toml
[[repos]]
path = "/path/to/api"
profile = "claude"

[[repos]]
path = "/path/to/worker"
profile = "codex"
```

```bash
python scripts/adopt.py --batch repos.toml --dry-run
python scripts/adopt.py --batch repos.toml
python scripts/adopt.py --batch repos.toml --sync
python scripts/adopt.py --batch repos.toml --check
```

See `docs/scripted-adoption.md` for `--sync`, `--force`, `--local-copy`, `.gitignore` collision handling, custom `--boundary`, custom `--validation`, and `generate_batch_list.py` details.

### 1. Start tasks with an explicit mode and instruction source

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

### 2. Keep target repositories updated

After pulling a new version of `agent-rules`, sync adopted repositories:

```bash
# Single repository
python scripts/adopt.py /path/to/repo --sync

# All repositories at once
python scripts/adopt.py --batch repos.toml --sync
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

- An agent file (AGENTS.md, CLAUDE.md, or GEMINI.md) exists at the repository root.
- It is listed in `.gitignore` (local-only, not committed).
- It links to this repository.
- It includes local summaries of the most important shared rules.
- It lists repository-specific boundaries.
- It lists concrete validation commands.
- Task prompts mention Primary Mode or Review Mode.
- Final reports include validation status and any intentionally skipped checks.

This repository intentionally focuses on rules, templates, lightweight adoption
helpers, and a small set of cross-agent workflow skills. It is not intended to
be a comprehensive agent-skill catalog or runtime automation framework.

## Shared Skills

The repository includes a shared `investigate-bug` skill whose behavioral
contract is usable by Codex and Claude. Install it together with an entrypoint:

```bash
python scripts/adopt.py /path/to/repo --profile all --skills --visibility tracked
```

Use `--visibility local` (the default) for personal files, or
`--visibility tracked` when the target repository should share generated
entrypoints and skills with the team.

The adoption helper records generated baselines under `.agent-rules/bases/`.
Later `--sync` runs use them for 3-way merges, preserving non-conflicting edits
to generated entrypoints and skills and stopping before unresolved conflicts
are written.

See `docs/cross-agent-validation.md` for the shared behavioral evaluation and
its remaining environment-specific validation gaps.
