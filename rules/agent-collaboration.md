# Agent Collaboration

Use agent roles as execution modes, not fixed tool identities.

Any supported agent may be used as a primary implementation agent or as a review/cross-check agent depending on the task, repository, environment, and available tools.

## Primary Mode

When acting as the primary agent:

- Understand the existing code, documentation, and behavior before editing.
- Keep changes scoped to the requested task.
- Preserve existing structure, naming, and conventions.
- Avoid unrelated refactoring or formatting changes.
- Validate changes with the narrowest relevant checks when possible.
- Clearly report what changed, what was intentionally not changed, and how the work was validated.

## Review Mode

When acting as a review or cross-check agent:

- Check correctness, compatibility, regressions, scope control, documentation impact, and validation gaps.
- Separate blocking issues from non-blocking suggestions.
- Do not rewrite the implementation unless explicitly requested.
- Do not expand the task scope.
- Prefer evidence-based feedback over broad style preferences.

## When Agents Disagree

Prefer the option that:

1. Preserves compatibility.
2. Requires the smaller and clearer change.
3. Has stronger validation evidence.
4. Matches existing repository conventions.
5. Reduces long-term maintenance burden.
