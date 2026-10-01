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
- `scripts/adopt.py`: Helper script for creating or checking lightweight target-repository adoption files. This path is the stable entry point; it re-exports the implementation.
- `scripts/agent_rules/`: Implementation modules behind `adopt.py`, split by concern (constants, models, metadata, gitio, source, render, gitignore, planning, checking, applying, batch, cli).
- `scripts/generate_batch_list.py`: Builds a `repos.toml`/`repos.txt` batch file by scanning a root folder for Git repositories.
- `docker/`: Start, stop, and host AI CLI check scripts for the Docker GUI and host AI bridge on Linux/WSL.
- `rules/agent-collaboration.md`: Primary/Review mode and multi-agent collaboration rules.
- `rules/commit-guidelines.md`: Conventional Commits-style commit message rules.
- `rules/`: Shared rules that apply across agents.
- `templates/`: Reusable task, review, and target-repository adoption templates.
- `.github/workflows/tests.yml`: CI workflow that runs the test suite under `tests/` on push and pull request.
- `ruff.toml`: Lint configuration for `scripts/` and `tests/`, pinning the rule selection CI enforces so a ruff upgrade cannot change it silently.

## Agent Usage Model

Agent roles are execution modes, not fixed tool identities.

Any supported agent may be used in either:

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Actual agent assignment should be decided per task. This repository intentionally avoids environment-specific assumptions.

## Local Web GUI

Run the deployment screen directly on Linux, WSL, or Windows using Python 3.10+
and Git. GUI dependencies are optional; the existing CLI remains usable without them.

```bash
python3 -m venv ~/.venvs/agent-rules
~/.venvs/agent-rules/bin/python -m pip install -r requirements-gui.txt
~/.venvs/agent-rules/bin/python scripts/gui.py --workspace /path/to/workspace
```

Optional [Docker setup](docs/docker-gui.md) packages only the deployment GUI.
A host bridge calls the PC's existing Codex or Claude Code, reusing its login and memories.

Open `http://127.0.0.1:8765` in a browser. Select repositories, inspect their
status, preview installation or sync changes, then apply the reviewed plan.
See [GUI setup and operation](docs/local-gui.md) for Windows, SSH access, and
preview invalidation behavior.

## Deploy Rules and Skills

Run these commands from your `agent-rules` checkout. The deployment tools do
not commit or push target repositories.

| Tool | Responsibility |
| --- | --- |
| [`scripts/generate_batch_list.py`](scripts/generate_batch_list.py) | Discover repositories and write a candidate batch list |
| [`scripts/adopt.py`](scripts/adopt.py) | Install, sync, check, or remove an adoption; supports batch install, sync, and check |
| [`scripts/agent_rules/`](scripts/agent_rules/) | Internal implementation; keep using the public scripts above |

### One repository

```bash
# Preview the Codex entrypoint and four shared skills.
python scripts/adopt.py /path/to/repo --profile codex --skills --dry-run
# Apply after reviewing the preview.
python scripts/adopt.py /path/to/repo --profile codex --skills
# Check the installation.
python scripts/adopt.py /path/to/repo --check --problems-only
```

Use `claude` for Claude, `gemini` for Gemini, or `all` when all three are used.
Shared skills are available for Codex and Claude. Generated files default to
local visibility; the tool updates the target's `.gitignore`. Add the target's
own boundaries and confirmed validation commands after installation.

### Multiple repositories

```bash
python scripts/generate_batch_list.py /path/to/workspace --output /path/to/repos.toml
# Edit the list: keep intended targets, exclude agent-rules itself and unrelated repositories.
python scripts/adopt.py --batch /path/to/repos.toml --profile codex --skills --dry-run
python scripts/adopt.py --batch /path/to/repos.toml --profile codex --skills
python scripts/adopt.py --batch /path/to/repos.toml --check --problems-only
```

Discovery writes a list; it does not install anything. Per-repository profiles
in the list override the command-line profile. TOML lists require Python 3.11+;
use a `.txt` list on Python 3.10. Keep machine-specific lists outside the shared
source checkout.

### Update installed repositories

After updating the `agent-rules` source, preview and sync the reviewed list:

```bash
python scripts/adopt.py --batch /path/to/repos.toml --sync --dry-run
python scripts/adopt.py --batch /path/to/repos.toml --sync
python scripts/adopt.py --batch /path/to/repos.toml --check --problems-only
```

Sync detects existing profiles and skills and preserves non-conflicting local
edits. To add skills to an entrypoint-only installation, use `--sync --skills`.
Merging changes into this repository does not automatically deploy them elsewhere.

See the [deployment guide](docs/scripted-adoption.md) for tracked visibility,
offline copies, conflicts, backups, removal, and legacy skill paths. Use the
[manual adoption guide](docs/lightweight-adoption.md) when editing entrypoints
without the tool.

## Start Tasks with the Installed Rules

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

## Task Continuity and Completion

For long-running work, use `templates/task-checkpoint-template.md` or an existing
project task record to retain scope, environment, decisions, evidence, and the
next step. Short follow-ups continue the agreed work; status questions do not
cancel it. Explicitly requested additional work stays in separate stages rather
than being silently deferred.

Implementation choices follow a bounded reuse-first sequence: existing code,
standard library, native platform features, installed dependencies, then new
code that meets the agreed requirements. See
[`rules/engineering-principles.md`](rules/engineering-principles.md).
This guidance is informed by [Ponytail](https://github.com/DietrichGebert/ponytail)
and expressed in this repository's own rules; it does not install Ponytail or
activate a persistent mode. Requirements, compatibility, safety, and appropriate
validation take precedence over line-count reduction.

Ask `review-change` to check a scoped change for over-engineering when needed.
It reports evidence-backed simplification suggestions separately from defects
and does not replace correctness review or modify code.

Performance investigations should set a baseline, acceptance criteria, and a
bounded experiment budget before measuring. PR and release work must follow the
destination's submission procedure and preserve signing, hooks, and checks.
See `rules/task-scope-control.md`, `rules/test-and-validation.md`, and
`rules/pr-discipline.md` for details. Generated entrypoints carry the essential
rules even without `--skills` or access to the shared repository.

Simple answers and progress updates need no fixed headings. Completed
implementation/review reports retain the structured report; PR descriptions use
the destination template. These instruction changes require fresh behavioral
evaluation; structural tests alone do not establish model compliance.

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

The repository includes shared `investigate-bug`, `review-change`,
`validate-change`, and `prepare-commit` skills whose behavioral contracts are
usable by Codex and Claude. Install them together with an entrypoint:

```bash
python scripts/adopt.py /path/to/repo --profile codex --skills --visibility tracked
python scripts/adopt.py /path/to/repo --profile claude --skills --visibility tracked
```

List the shared skills and what each is for without touching a repository:

```bash
python scripts/adopt.py --list-skills
```

Use `--visibility local` (the default) for personal files, or
`--visibility tracked` when the target repository should share generated
entrypoints and skills with the team.

Skills currently support the Codex and Claude profiles only. `--profile gemini`
installs the `GEMINI.md` entrypoint but no skills — there is no shared-skill
path for Gemini yet, so `--skills` with that profile installs nothing and
reports that no Gemini skill path exists.

`--skills` also injects a `## Shared Skills` trigger section into the
generated `AGENTS.md` and `CLAUDE.md` so the appropriate installed skill is
invoked reliably for bug investigations, change reviews, focused
validation, and commit preparation. See
`docs/cross-agent-validation.md` for why the entrypoint is the trigger lever
that works when requests compete for attention.

The adoption helper records generated baselines under `.agent-rules/bases/`.
Later `--sync` runs use them for 3-way merges, preserving non-conflicting edits
to generated entrypoints and skills and stopping before unresolved conflicts
are written. Baseline records also retain the installed skill selection when
all skill files have been deleted, so `--check` detects the loss and `--sync`
restores the files without requiring `--skills` again.

Skill removal requires a per-file baseline as installation evidence. A known
skill name alone does not establish ownership; missing or untrustworthy
baselines block the entire removal plan, including with `--force`. Entrypoints
still require their generated metadata. Removal backs up owned files, including
local edits, before deleting them. Keep the baseline records until removal is
complete; installations without these records require manual ownership review.

See `docs/cross-agent-validation.md` for the cross-agent behavioral evaluations
of `investigate-bug` and `review-change` and their remaining
environment-specific validation gaps. The targeted `review-change` mitigations
were revalidated with both agents, including a successful Codex local-execution
comparison of defective and clean branch reviews.

### Validate Change

`validate-change` focuses on selecting and running the narrowest relevant checks
for the current change, reporting commands that ran or were skipped, and
confirming whether validation left unexpected worktree changes. It complements
`review-change`, whose primary purpose is finding defects and validation gaps.

The skill's structural and adoption tests run in this repository. Live
forward-testing in both Codex and Claude confirmed the automatic trigger and
behavioral contract, including Codex actually running the failing check and
declining to delete the artifacts it created without authorization. See
`docs/cross-agent-validation.md`'s Shared-Skill Forward Test for details and
known harness gaps.

### Prepare Commit

`prepare-commit` turns the current changes into one well-scoped, Conventional
Commits-formatted commit: it reviews the diff, keeps unrelated work out, runs
lightweight pre-commit checks such as `git diff --check`, and writes the message
without rewriting history or reformatting code. It applies the same commit
discipline as `rules/commit-guidelines.md`, invoked automatically when a commit
is requested.

The skill's structural and adoption tests run in this repository. Live
forward-testing confirmed the automatic trigger in both Codex and Claude;
Codex's read-only sandbox did not block it from actually committing (correctly
scoped and worded), while Claude's plan mode stopped before executing but
still named the correct skill and scope in its draft plan. See
`docs/cross-agent-validation.md`'s Shared-Skill Forward Test for details.
