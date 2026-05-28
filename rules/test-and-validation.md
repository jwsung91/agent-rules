# Test and Validation

Use validation that is appropriate to the size and risk of the change.

- Run the narrowest relevant checks first.
- Add or update tests when behavior changes.
- Prefer deterministic tests.
- Avoid hardware-specific, environment-specific, or timing-sensitive assumptions unless the task requires them.
- Do not claim tests, checks, builds, or manual validation were run if they were not.
- If validation cannot be run, explain why and provide the commands that should be run.
- Report failures clearly, including whether they are related to the change.

Use this summary format:

```text
Validation:
- [x] Ran: ...
- [ ] Not run: ... because ...
```
