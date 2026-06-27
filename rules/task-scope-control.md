# Task Scope Control

Use these rules to keep work focused and reviewable.

- Stay within the requested task.
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
