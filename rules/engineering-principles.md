# Engineering Principles

Use these principles when changing code, documentation, or repository structure.

- Prefer simple, explicit, maintainable designs.
- Avoid unnecessary abstraction and speculative extension points.
- Keep public APIs small, stable, and easy to reason about.
- Respect the existing project structure, naming, and conventions.
- Avoid new dependencies unless they have a clear, task-specific justification.
- Optimize for real users, operators, and maintainers.
- Document intent and trade-offs where they affect future decisions.
- Prefer local consistency over introducing a new style.
- Do not overclaim maturity, performance, reliability, or production readiness.
- Make limitations visible when they matter to users or maintainers.

## Choosing an Implementation

After understanding the requested behavior and affected callers, prefer an
existing implementation, then the standard library, native platform features,
already-installed dependencies, and finally new code. Stop searching when an
option meets the actual requirements; this is a decision aid, not an exhaustive
survey. Check semantics, compatibility, and project conventions before reuse.

Simplify the implementation while completing every agreed requirement. Do not
replace an explicitly requested capability with a reduced version, or reopen
settled scope merely because a smaller feature would be easier. Omit speculative
extensions; fix shared root causes rather than duplicating symptom patches.

Choose readable, maintainable code over minimum line or file counts. Preserve
public contracts, trust-boundary validation, data-loss handling, security,
accessibility, and risk-appropriate tests. Existing test frameworks and required
checks still apply; a one-line change can need substantial validation.

When a deliberate simplification has a relevant limit, explain the limit and
the evidence that would justify a more complex approach. Add a comment only
when future maintainers need it; do not create a mandatory debt ledger.
