# PR Discipline

Use these rules for pull requests and final change reports.

- One PR should have one clear purpose.
- Avoid mixing unrelated changes.
- Include a summary and validation.
- Call out breaking changes.
- Call out limitations and known gaps.
- Use follow-up issues or notes for related work outside the current scope.
- Keep review scope understandable from the title, description, and changed files.

When opening or updating a PR:

- Follow the repository's PR template when one is available.
- Treat repository-local PR templates as the source of truth for PR structure.
- Use English for PR titles, descriptions, summaries, and review requests unless the task explicitly requires another language.
- Use a PR title that represents the primary feature, fix, or documentation change.
- Match the PR type or category to the Conventional Commit type used for the primary commit, such as `feat`, `fix`, or `docs`.
- Preserve the template structure unless there is a clear reason to omit a section.
- If a template section does not apply, write `N/A` or a short explanation instead of deleting it silently.

Final responses and PR summaries should include:

- Summary
- Changes
- Validation
- Not Included
- Follow-up
