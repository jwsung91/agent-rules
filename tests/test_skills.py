from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
QUOTED_INTERFACE_VALUE_RE = re.compile(
    r'^  (?P<key>[a-z_]+): "(?P<value>.*)"$', re.MULTILINE
)


def skill_directories() -> list[Path]:
    return sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    content = skill_md.read_text(encoding="utf-8")
    assert content.startswith("---\n"), f"{skill_md} has no YAML frontmatter"
    _, frontmatter, _body = content.split("---", 2)
    fields: dict[str, str] = {}
    for line in frontmatter.strip().splitlines():
        key, separator, value = line.partition(":")
        assert separator, f"{skill_md} contains an invalid frontmatter line: {line}"
        fields[key.strip()] = value.strip()
    return fields


def parse_openai_interface(openai_yaml: Path) -> dict[str, str]:
    content = openai_yaml.read_text(encoding="utf-8")
    assert content.startswith("interface:\n"), f"{openai_yaml} has no interface mapping"
    interface_lines: list[str] = []
    for line in content.splitlines()[1:]:
        if line and not line.startswith("  "):
            break
        if line:
            interface_lines.append(line)
    for line in interface_lines:
        assert QUOTED_INTERFACE_VALUE_RE.fullmatch(line), (
            f"{openai_yaml} contains an unquoted or invalid interface value: {line}"
        )
    values = {
        match.group("key"): match.group("value")
        for line in interface_lines
        if (match := QUOTED_INTERFACE_VALUE_RE.fullmatch(line))
    }
    return values


def test_shared_skill_frontmatter() -> None:
    skills = skill_directories()
    assert skills, "no shared skills found"

    for skill_dir in skills:
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), f"{skill_dir} is missing SKILL.md"
        fields = parse_frontmatter(skill_md)
        assert set(fields) == {"name", "description"}
        assert fields["name"] == skill_dir.name
        assert SKILL_NAME_RE.fullmatch(fields["name"])
        assert fields["description"]


def test_codex_skill_interface_metadata() -> None:
    for skill_dir in skill_directories():
        openai_yaml = skill_dir / "agents" / "openai.yaml"
        if not openai_yaml.exists():
            continue

        values = parse_openai_interface(openai_yaml)
        assert {
            "display_name",
            "short_description",
            "default_prompt",
        } <= set(values)
        assert values["display_name"]
        # 25-64 chars is Codex's own documented constraint, not a guess:
        # ~/.codex/skills/.system/skill-creator/references/openai_yaml.md
        # states "interface.short_description: Human-facing short UI blurb
        # (25-64 chars) for quick scanning." (docs/skill-authoring.md)
        assert 25 <= len(values["short_description"]) <= 64
        # Codex's `$<skill-name>` mention syntax, matching Codex's own
        # documented default_prompt convention (docs/skill-authoring.md):
        # "It must explicitly mention the skill as $skill-name".
        assert f"${skill_dir.name}" in values["default_prompt"]


NEXT_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)
# Natural-language regex matching for this ("does the prose mean the skill
# honors the repository's format?") does not work: it's easy to construct a
# sentence that contains the required words but negates or contradicts their
# meaning ("Never honor the repository format", "Do not preserve..."), and no
# amount of additional regex tweaking closes that off in general. Require an
# explicit, unambiguous marker instead — the same style as this repo's own
# MANAGED_START/MANAGED_END markers in scripts/adopt.py — so the check is a
# plain substring match with no natural-language ambiguity to get wrong.
REPORT_POLICY_MARKER = "<!-- skill-report-policy: honor-repository-format -->"
INVESTIGATE_SCOPE_POLICY_MARKER = (
    "<!-- investigate-scope-policy: exclude-unrelated-work-from-fix-plan -->"
)
REVIEW_SCOPE_POLICY_MARKER = (
    "<!-- review-scope-policy: do-not-substitute-unverified-target -->"
)
REVIEW_SEVERITY_POLICY_MARKER = (
    "<!-- review-severity-policy: require-repository-evidence -->"
)
VALIDATE_SCOPE_POLICY_MARKER = (
    "<!-- validate-scope-policy: execute-checks-without-review-substitution -->"
)


def extract_section(content: str, heading: str) -> str | None:
    heading_re = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = heading_re.search(content)
    if not match:
        return None
    next_heading = NEXT_HEADING_RE.search(content, match.end())
    end = next_heading.start() if next_heading else len(content)
    return content[match.start() : end]


def extract_report_section(content: str) -> str | None:
    return extract_section(content, "Report")


def test_extract_report_section_stops_at_next_heading() -> None:
    # Regression: extract_report_section() used to run to the end of the
    # file instead of stopping at the next "## " heading, so an unrelated
    # later section's content (here, "## Repository Notes") could satisfy a
    # policy check meant to apply only within the Report section itself.
    content = (
        "## Report\n\nUse this exact format.\n\n"
        "## Repository Notes\n\nPreserve repository configuration files.\n"
    )
    section = extract_report_section(content)
    assert section is not None
    assert "Repository Notes" not in section
    assert REPORT_POLICY_MARKER not in section


def test_skills_with_report_sections_honor_repository_format() -> None:
    # Generalizes across every skill (see docs/skill-authoring.md): a skill
    # that defines its own final-report format must carry the
    # REPORT_POLICY_MARKER, not pin exact prose for one skill the way this
    # test used to for investigate-bug specifically. Only a heading literally
    # named "## Report" is recognized (not "equivalent" headings — there is
    # no reliable way to enumerate those, so this test and
    # docs/skill-authoring.md both describe exactly this behavior).
    for skill_dir in skill_directories():
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        report_section = extract_report_section(content)
        if report_section is None:
            continue
        assert REPORT_POLICY_MARKER in report_section, (
            f"{skill_dir.name}/SKILL.md has a '## Report' section but is "
            f"missing the marker comment ({REPORT_POLICY_MARKER}) that "
            "states a host repository's required report format takes "
            "precedence (see docs/skill-authoring.md)"
        )


def test_review_change_guards_scope_and_severity() -> None:
    content = (SKILLS_ROOT / "review-change" / "SKILL.md").read_text(encoding="utf-8")
    guardrails_section = extract_section(content, "Guardrails")
    severity_section = extract_section(content, "Severity")
    assert guardrails_section is not None
    assert severity_section is not None
    assert REVIEW_SCOPE_POLICY_MARKER in guardrails_section
    assert REVIEW_SEVERITY_POLICY_MARKER in severity_section


def test_investigate_bug_excludes_unrelated_work_from_fix_plan() -> None:
    content = (SKILLS_ROOT / "investigate-bug" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    guardrails_section = extract_section(content, "Guardrails")
    assert guardrails_section is not None
    assert INVESTIGATE_SCOPE_POLICY_MARKER in guardrails_section


def test_validate_change_preserves_scope_and_validation_integrity() -> None:
    content = (SKILLS_ROOT / "validate-change" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    guardrails_section = extract_section(content, "Guardrails")
    workflow_section = extract_section(content, "Workflow")
    assert guardrails_section is not None
    assert workflow_section is not None
    assert VALIDATE_SCOPE_POLICY_MARKER in guardrails_section
    assert "initial worktree state" in workflow_section
    assert "revert unexpected artifacts without authorization" in workflow_section
    assert "Do not weaken, skip, or rewrite failing tests" in guardrails_section
