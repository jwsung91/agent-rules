# agent-rules

Shared working rules, agent entrypoints, and task templates for AI coding agents used across `jwsung91` repositories.

## Purpose

This repository defines common working rules for AI coding agents. It is intended to keep agent behavior consistent across repositories, especially for engineering judgment, task scope control, validation, documentation, and pull request discipline.

Supported agents:

- Codex
- Claude
- Gemini

## Directory Overview

- `AGENTS.md`: Codex and generic coding agent entrypoint.
- `CLAUDE.md`: Claude-specific entrypoint.
- `GEMINI.md`: Gemini-specific entrypoint.
- `rules/`: Shared rules that apply across agents.
- `templates/`: Reusable task and review instruction forms.

## Recommended Usage

Copy or reference the relevant entrypoint file from a target repository, then have the agent follow the shared rules in `rules/`. Use the templates in `templates/` when preparing task instructions or pull request review requests.

This initial version focuses on rules and templates only. It does not define full agent skills, scripts, CI, package metadata, or automation.
