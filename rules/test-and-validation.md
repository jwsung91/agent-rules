# Test and Validation

Use validation that is appropriate to the size and risk of the change.

- Run the narrowest relevant checks first.
- Add or update tests when behavior changes.
- If behavior changes but tests are not added, explain why.
- Check whether user-facing behavior, public APIs, configuration, commands, or workflows require documentation updates.
- Treat missing or outdated documentation as a validation gap when the change affects how users or maintainers work.
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
- Tests: added, updated, not needed, or not added because ...
- Documentation: updated, not needed, or not updated because ...
```
