# Claude + Codex Workflow

## Purpose

Use this guide when a target repository uses Codex and Claude together. The goal is to keep one shared repository instruction source while giving each agent a clear operating role.

Codex and Claude should not compete over the same task. In most workflows, one agent performs the primary implementation work and the other reviews the plan, risks, or diff.

## Recommended Profile

For repositories that use Codex and Claude, the recommended setup is usually `--profile claude`:

```bash
python scripts/adopt-agent-rules.py /path/to/repo --plan
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --detect --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --detect
```

This creates:

```text
AGENTS.md
CLAUDE.md
```

Codex uses `AGENTS.md` as the shared repository entrypoint. Claude uses `CLAUDE.md`, which delegates to `AGENTS.md` as the primary repository instruction file. This keeps policy concentrated in `AGENTS.md` and keeps `CLAUDE.md` as a thin tool-specific entrypoint.

## Basic Setup

1. Run `--plan` first.
2. Use `--profile claude` for Codex + Claude repositories.
3. Add `--detect` when you want detected validation commands written into `AGENTS.md`.
4. Review the generated files before committing in the target repository.
5. Fill in repository-specific boundaries and validation commands.

Do not copy root-level `rules/` or `templates/` into the target repository. If offline or pinned access is needed, use `--local-copy`, which writes under `.agents/agent-rules/`.

## Role Model

Codex:

- Best suited to Primary Mode.
- Handles implementation, refactoring, test additions, and documentation edits.
- Uses `AGENTS.md` for scope control, repository conventions, and validation expectations.

Claude:

- Best suited to Review Mode.
- Handles design review, risk analysis, compatibility review, and validation gap checks.
- Uses `CLAUDE.md` and `AGENTS.md` for review expectations.

For some tasks, Claude can produce a plan or risk review first, then Codex can implement the approved plan.

## Workflow 1: Codex Primary, Claude Review

Use Codex to make the scoped change. Then ask Claude to review the resulting diff for correctness, regressions, missing validation, and documentation impact.

This workflow fits most implementation tasks because it separates write authority from review judgment.

## Workflow 2: Codex Implementation, Claude Risk Review

Use Codex for the implementation and ask Claude specifically for risk review when the change touches compatibility, public behavior, package metadata, CI, validation, or cross-agent instruction files.

Claude should separate blocking issues from non-blocking suggestions. Codex should only make follow-up changes that are in scope for the original task or explicitly approved.

## Workflow 3: Claude Planning, Codex Implementation

Use Claude first when the task needs careful planning, tradeoff analysis, or compatibility review before files are modified. Claude should not edit files in this phase.

After the plan is accepted, use Codex to implement it in Primary Mode and validate with the narrowest relevant checks.

## Prompt Examples

Codex Primary Mode:

```text
Use Primary Mode.

Follow AGENTS.md.

Implement the requested change.
Keep the change scoped.
Do not refactor unrelated files.
Do not rename public APIs unless explicitly requested.
Validate with the narrowest relevant checks.
Report what changed, what was not changed, and what validation was run.
```

Claude Review Mode:

```text
Use Review Mode.

Follow CLAUDE.md and AGENTS.md.

Review the current changes for:
- correctness
- scope control
- compatibility
- validation gaps
- documentation impact

Separate blocking issues from non-blocking suggestions.
Do not rewrite the implementation unless explicitly requested.
```

Claude Planning to Codex Implementation:

```text
Claude planning request:

Use Review Mode.

Follow CLAUDE.md and AGENTS.md.
Review the requested change and produce an implementation plan.
Focus on scope, risks, compatibility, and validation.
Do not modify files.

Codex implementation request:

Use Primary Mode.

Follow AGENTS.md.
Implement the approved plan.
Keep the change scoped.
Validate with the narrowest relevant checks.
Report changes and validation honestly.
```

Codex Implementation to Claude Review:

```text
Codex request:

Use Primary Mode.

Follow AGENTS.md.
Implement the requested change.
Keep the diff small and focused.
Run relevant validation if practical.

Claude request:

Use Review Mode.

Follow CLAUDE.md and AGENTS.md.
Review the Codex changes.
Check for correctness, regression risk, scope creep, and missing validation.
Do not rewrite unless requested.
```

## Validation and Reporting

Keep validation commands in `AGENTS.md` specific to the target repository. `--detect` can suggest commands, but detected commands are written only when `--detect` is used on the apply command.

Agents must report validation honestly. If a command was not run, the final report should say that it was not run and explain why.

## When to Use Multi Profile

Use `--profile multi` when the repository actively uses Codex, Claude, and Gemini:

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile multi --detect --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile multi --detect
```

For Codex + Claude only, prefer `--profile claude`. Adding `GEMINI.md` without using Gemini adds another entrypoint to maintain without improving the Codex + Claude workflow.

## Anti-patterns

- Asking Codex and Claude to edit the same files at the same time.
- Expanding Claude review feedback into a large unrelated refactor.
- Asking a Review Mode agent to implement changes during the review pass.
- Duplicating conflicting policy in `AGENTS.md` and `CLAUDE.md`.
- Leaving target repository validation commands empty.
- Letting an agent report validation that it did not run.
