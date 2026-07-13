# Skill Authoring Convention

Use this when adding or updating a shared skill under `skills/<name>/`.

## SKILL.md

- YAML frontmatter with exactly `name` (must match the directory name, lowercase with hyphens) and `description` (non-empty, states when to use the skill).
- If the skill defines its own final-report or output format (a heading literally named `## Report` — no other heading name is recognized, and the section runs until the next `## ` heading or end of file), it must state that a host repository's required report structure takes precedence and must not be replaced — only extended with the skill's own fields — **and include the literal marker comment `<!-- skill-report-policy: honor-repository-format -->` inside that section.** See `skills/investigate-bug/SKILL.md`'s `## Report` section for the reference wording and marker placement.

  The marker exists because natural-language regex matching on the prose ("does this sentence mean the skill honors the repository's format?") doesn't work: a sentence can contain all the expected words while negating or contradicting their meaning (e.g. "Never honor the repository format"), and no amount of additional pattern-tweaking closes that off in general. The marker is a plain, unambiguous substring check instead — the same style as this repo's own `MANAGED_START`/`MANAGED_END` markers in `scripts/adopt.py`. This is enforced by `tests/test_skills.py`'s `test_skills_with_report_sections_honor_repository_format`.

This guidance exists because a repository that installs the skill typically already has its own required report structure (for example this repository's own `CLAUDE.md` has a `## Final Report` section with required fields) — a skill that always emits its own fixed format regardless of the host repository's requirements will conflict with it.

## agents/openai.yaml (Codex-only)

Optional per-skill file under `skills/<name>/agents/openai.yaml`, excluded from Claude installs (`scripts/adopt.py`'s `CODEX_ONLY_SKILL_FILES`). Schema per Codex's own authoritative reference, `~/.codex/skills/.system/skill-creator/references/openai_yaml.md` (a local file installed by the Codex CLI itself — re-check it directly if this drifts, don't treat this doc as the source of truth):

```yaml
interface:
  display_name: "Human-Readable Name"
  short_description: "One-line summary shown in Codex's skill picker"
  default_prompt: "Use $<skill-name> to <do the thing>."
```

- `default_prompt` "must explicitly mention the skill as `$skill-name`" (quoted directly from the reference doc above), matching the pattern used by Codex's built-in `imagegen` (`"Use $imagegen to make or edit an image for this project."`) and `plugin-creator` (`"Use $plugin-creator to scaffold a valid plugin..."`) skills.
- `short_description` must be **25-64 characters** — an explicit constraint in the reference doc ("Human-facing short UI blurb (25-64 chars) for quick scanning"), enforced by `tests/test_skills.py`. Note some of Codex's own built-in skills (e.g. `openai-docs` at 73 characters, `skill-creator` at 24) don't actually satisfy this range in practice — don't treat those as evidence the constraint is optional; follow the documented range for skills authored in this repository regardless.
- `display_name` is free text, no documented length constraint.
- `icon_small`/`icon_large`/`brand_color` are optional and not currently used by any skill in this repository.
