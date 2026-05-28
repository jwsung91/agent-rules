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
- `docs/lightweight-adoption.md`: Guide for applying these rules to target repositories using a lightweight local `AGENTS.md`.
- `rules/agent-collaboration.md`: Primary/Review mode and multi-agent collaboration rules.
- `rules/commit-guidelines.md`: Conventional Commits-style commit message rules.
- `rules/`: Shared rules that apply across agents.
- `templates/`: Reusable task and review instruction forms.

## Agent Usage Model

Agent roles are execution modes, not fixed tool identities.

Any supported agent may be used in either:

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Actual agent assignment should be decided per task. This repository intentionally avoids environment-specific assumptions.

## Recommended Usage

Copy or reference the relevant entrypoint file from a target repository, then have the agent follow the shared rules in `rules/`. For target repositories, see `docs/lightweight-adoption.md` for the lightweight local `AGENTS.md` approach. Use the templates in `templates/` when preparing task instructions or pull request review requests. Use `rules/commit-guidelines.md` when preparing commits or instructing agents to commit changes.

This initial version focuses on rules and templates only. It does not define full agent skills, scripts, CI, package metadata, or automation.
