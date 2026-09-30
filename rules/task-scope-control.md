# Task Scope Control

Use these rules to keep work focused and reviewable.

- Stay within the requested task, including all explicitly requested parts. Separate independent changes without dropping authorized work.
- Prefer the smallest meaningful change that solves the problem.
- Do not mix unrelated refactoring, formatting, feature work, and documentation changes.
- Do not rename public APIs, files, directories, or user-facing concepts unless requested.
- Avoid broad cleanup while implementing a narrow fix.
- Document follow-up findings instead of expanding the task scope.
- Preserve existing behavior unless the requested change requires otherwise.
- Clearly state what was intentionally not changed.

## When to Checkpoint

Pause and report before continuing when:

- A destructive operation (delete, overwrite, force push) is required but not explicitly authorized.
- Investigation reveals the task is substantially larger than described.
- Multiple valid implementation approaches exist with meaningfully different trade-offs.
- The task as stated conflicts with an existing rule, convention, or constraint in the repository.
- A required dependency or environment is missing and cannot be resolved automatically.

When pausing, report:

- What was found that triggered the pause.
- What options exist, with trade-offs.
- What decision or clarification is needed to continue.

## Continuing Work

- Interpret short follow-ups such as "continue" or "진행해" using the last agreed
  next step. Do not infer authorization for a release, merge, or broader scope
  from an ambiguous continuation.
- Treat status questions as requests for an answer while preserving the task.
  Stop or replace work only when the user cancels or changes the objective.
- Preserve accepted constraints and decisions; do not repeatedly ask for the
  same authorization. Ask only when the next action is materially ambiguous.
- For work spanning sessions, agents, or experiments, use the existing task
  record or `templates/task-checkpoint-template.md`. Keep short tasks in chat.
- Record the exact repository, branch/base, host/shell, relevant environment,
  goal, authorized actions, constraints, evidence, remaining steps, and stop
  conditions. Distinguish decisions from hypotheses and preserve later user
  corrections. Do not store credentials or unrelated personal information.
- On resumption, verify the checkpoint against the live worktree and remote
  state where relevant. A checkpoint is context, not new authorization.

## Progress Against the Plan

- For multi-step work, retain a short list of meaningful stages and their
  completion criteria within the agreed scope. Do not require a separate plan
  file or an approval round for routine work.
- Track stages as completed, in progress, pending, or blocked. Completion needs
  evidence appropriate to the stage; starting a command is not passing a check.
- At meaningful milestones and in result reports, state completed stages out of
  the agreed total, the current stage, remaining requested work, and blockers.
  Counts measure completed scope, not time or effort; avoid unsupported percentages.
- Preserve the original objective across follow-ups. When the user adds, removes,
  or defers requested work, explain the plan change and update the denominator.
  Do not mark deferred or blocked work complete or subdivide stages to inflate progress.
- Distinguish implementation completion from the requested outcome. Track PR,
  CI, merge, or deployment stages when requested; optional recommendations are
  not unfinished requested work and must not inflate the plan.
- Keep small-task reporting to one sentence. A progress report is not a pause or
  a request for permission; continue already-authorized work.
