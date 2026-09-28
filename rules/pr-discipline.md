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

- Confirm the destination repository and comparison base; inspect its contribution and release instructions, including required submission tools. A manually equivalent result does not establish that the required procedure was followed.
- Before writing the PR, look for a repository PR template — for example `.github/PULL_REQUEST_TEMPLATE.md`, `.github/pull_request_template.md`, a `.github/PULL_REQUEST_TEMPLATE/` directory, or a `docs/` equivalent (`gh pr create` without `--body` also loads it automatically).
- When a template is available, treat it as the source of truth for both PR structure and language: match its sections and the language it is written in.
- When no template is available, use English for PR titles, descriptions, summaries, and review requests unless the task explicitly requires another language.
- Use a PR title that represents the primary feature, fix, or documentation change.
- Match the PR type or category to the Conventional Commit type used for the primary commit, such as `feat`, `fix`, or `docs`.
- Preserve the template structure unless there is a clear reason to omit a section.
- If a template section does not apply, write `N/A` or a short explanation instead of deleting it silently.

Completed implementation and review reports should include the items below. Simple answers and progress updates need no fixed headings. PR descriptions follow the destination template:

- Summary
- Changes
- Validation
- Not Included
- Follow-up

## Merge and Release Completion

- Confirm that publication or merge is authorized for the intended target.
- Refresh the relevant remote state before preparing the final change. Preserve
  other work; reconcile conflicts without silently changing the approved scope.
- Honor signing, hooks, and required checks. If credentials, signing, or a
  required tool blocks the action, report the exact blocker rather than bypass it.
- Verify checks and reviews for the exact head to be merged. Do not merge after
  the head changes without checking the new revision.
- Verify the server-side merge or release result. Distinguish PR creation,
  CI success, merge, release publication, and downstream availability.
- Synchronize the local branch only when safe for its current worktree and
  report remaining external steps without claiming they have completed.
