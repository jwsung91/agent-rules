# Investigation Before Fix

Use an investigation-first workflow for debugging and behavior changes.

1. Reproduce or understand the issue before editing.
2. Identify expected behavior and actual behavior.
3. Separate possible causes:
   - Application logic
   - Library or core behavior
   - Configuration
   - Environment
   - Test design
   - Documentation mismatch
4. Avoid broad fixes before the root cause is understood.
5. Prefer regression tests or focused validation when behavior changes.
6. Document the root cause, validation performed, and follow-up items.

When the issue cannot be reproduced, state what was checked and what evidence is still missing.

## Investigation Report Format

Use this format when reporting investigation findings:

```text
Investigation:
- Issue: [what was reported or observed]
- Expected: [what should happen]
- Actual: [what is happening]
- Root cause: [identified cause, or "unknown — see below"]
- Affected area: [files, components, or behaviors involved]
- Fix approach: [what was changed and why]
- Validation: [how the fix was verified]
- Follow-up: [deferred items or remaining unknowns]
```

If the root cause cannot be determined, document what was ruled out and what evidence is still missing.
