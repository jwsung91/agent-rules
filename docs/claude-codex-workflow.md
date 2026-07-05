# Claude + Codex Workflow

## Purpose

Use this guide when a target repository uses Codex and Claude together. The goal is to keep one shared repository instruction source while giving each agent a clear operating role **for the current task** — not a fixed role per tool.

Per `rules/agent-collaboration.md`: agent roles are execution modes, not fixed tool identities. Either tool can act as the primary implementation agent or as the review/cross-check agent, depending on the task, the repository, and which tool the user is actively driving. Whichever tool is primary for a given task should not be assumed from a prior task.

Codex and Claude should not compete over the same task. In most workflows, one agent performs the primary implementation work and the other reviews the plan, risks, or diff.

## Basic Setup

Adopt both entrypoints in the target repository:

```bash
python scripts/adopt.py /path/to/repo --profile codex --dry-run
python scripts/adopt.py /path/to/repo --profile codex
python scripts/adopt.py /path/to/repo --profile claude --dry-run
python scripts/adopt.py /path/to/repo --profile claude
```

This creates `AGENTS.md` and `CLAUDE.md`. Each profile only touches its own file, so the two commands are independent and order does not matter. (`--profile all` also works if the repository may add Gemini later — it additionally creates `GEMINI.md`, which is harmless to leave unused.)

Codex uses `AGENTS.md` as its entrypoint; Claude uses `CLAUDE.md`. Both are generated from the same shared Core Rules, Commit Messages, Validation, and Final Report content, so neither tool gets materially different guidance from the other — the difference is only in tool-specific phrasing.

1. Run `--dry-run` first.
2. Adopt both `--profile codex` and `--profile claude` (see above) for Codex + Claude repositories.
3. Pass `--validation "<command>"` (repeatable) for commands you already know are correct; the helper also auto-detects likely commands from build files and labels them separately as unverified candidates.
4. Both `AGENTS.md` and `CLAUDE.md` are local-only (gitignored automatically) — review them, but there's nothing to commit for the entrypoints themselves.
5. Fill in repository-specific boundaries and validation commands.

Do not copy root-level `rules/` or `templates/` into the target repository. If offline or pinned access is needed, use `--local-copy`, which writes under `.agents/agent-rules/`.

## Role Model

Assign Primary Mode and Review Mode per task, not per tool. A repository might use Claude as primary for most work and bring in Codex only for a second opinion on a specific change — or the reverse. Whichever tool the user is actively directing for a task is Primary by default unless the user says otherwise.

- **Primary Mode**: implementation, refactoring, test additions, and documentation edits. Uses its entrypoint (`AGENTS.md` or `CLAUDE.md`) for scope control, repository conventions, and validation expectations.
- **Review Mode**: design review, risk analysis, compatibility review, and validation gap checks. Uses both entrypoints (its own and the other tool's, if relevant) for review expectations.

For some tasks, one tool can produce a plan or risk review first, then the other implements the approved plan — see `rules/agent-collaboration.md` for the general Primary/Review Mode rules and the tie-breaking order when the two disagree.

## Workflow 1: One Agent Primary, the Other Reviews

Use one agent to make the scoped change. Then ask the other to review the resulting diff for correctness, regressions, missing validation, and documentation impact.

This workflow fits most implementation tasks because it separates write authority from review judgment.

## Workflow 2: Implementation Plus Targeted Risk Review

Use one agent for the implementation and ask the other specifically for risk review when the change touches compatibility, public behavior, package metadata, CI, validation, or cross-agent instruction files.

The reviewing agent should separate blocking issues from non-blocking suggestions. The implementing agent should only make follow-up changes that are in scope for the original task or explicitly approved.

## Workflow 3: Planning First, Then Implementation

Use one agent first when the task needs careful planning, tradeoff analysis, or compatibility review before files are modified. That agent should not edit files during this phase.

After the plan is accepted, use the other agent (or the same one) to implement it in Primary Mode and validate with the narrowest relevant checks.

## Prompt Examples

Primary Mode:

```text
Use Primary Mode.

Follow this repository's entrypoint file (AGENTS.md or CLAUDE.md).

Implement the requested change.
Keep the change scoped.
Do not refactor unrelated files.
Do not rename public APIs unless explicitly requested.
Validate with the narrowest relevant checks.
Report what changed, what was not changed, and what validation was run.
```

Review Mode:

```text
Use Review Mode.

Follow this repository's entrypoint files (AGENTS.md and/or CLAUDE.md).

Review the current changes for:
- correctness
- scope control
- compatibility
- validation gaps
- documentation impact

Separate blocking issues from non-blocking suggestions.
Do not rewrite the implementation unless explicitly requested.
```

Planning handoff to implementation:

```text
Planning request:

Use Review Mode.

Follow this repository's entrypoint files.
Review the requested change and produce an implementation plan.
Focus on scope, risks, compatibility, and validation.
Do not modify files.

Implementation request:

Use Primary Mode.

Follow this repository's entrypoint file.
Implement the approved plan.
Keep the change scoped.
Validate with the narrowest relevant checks.
Report changes and validation honestly.
```

Implementation handoff to review:

```text
Implementation request:

Use Primary Mode.

Follow this repository's entrypoint file.
Implement the requested change.
Keep the diff small and focused.
Run relevant validation if practical.

Review request:

Use Review Mode.

Follow this repository's entrypoint files.
Review the changes.
Check for correctness, regression risk, scope creep, and missing validation.
Do not rewrite unless requested.
```

## Validation and Reporting

Keep validation commands in the repository's entrypoint file(s) specific to the target repository. Auto-detected commands are suggested from build files present in the repository, but are labeled as unverified candidates — confirm them with `--validation` (or by hand) once you know they work.

Agents must report validation honestly. If a command was not run, the final report should say that it was not run and explain why.

## Adding a Third Tool (Gemini)

If the repository later starts using Gemini too, adopt `--profile gemini` the same way as the other two:

```bash
python scripts/adopt.py /path/to/repo --profile gemini --dry-run
python scripts/adopt.py /path/to/repo --profile gemini
```

Don't add `GEMINI.md` speculatively — an unused entrypoint is another file that must be kept in sync (see `rules/agent-collaboration.md`) without improving the actual workflow.

## Anti-patterns

- Asking Codex and Claude to edit the same files at the same time.
- Expanding a Review Mode agent's feedback into a large unrelated refactor.
- Asking a Review Mode agent to implement changes during the review pass.
- Duplicating conflicting policy in `AGENTS.md` and `CLAUDE.md` (both should carry the same shared Core Rules).
- Leaving target repository validation commands empty.
- Letting an agent report validation that it did not run.
- Assuming one tool is always primary and the other always reviews — reassign per task.
