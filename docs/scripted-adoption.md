# Scripted Repository Adoption

Use `scripts/adopt-agent-rules.py` when applying `agent-rules` to multiple repositories or when you want repeatable planning, checking, and update behavior.

The script creates root-level agent entrypoints and does not copy root-level `rules/` or `templates/` into the target repository. Full local copies, when requested, are written only under `.agents/agent-rules/`.

## Recommended Workflow

1. Inspect the target repository with `--plan`.
2. Choose an agent profile: `codex`, `claude`, `gemini`, or `multi`.
3. Run with `--dry-run`.
4. Apply the files.
5. Edit repository-specific boundaries and validation commands.
6. Run the suggested validation, starting with `git diff --check`.
7. Commit in the target repository after review.

## Profiles

```text
codex  -> AGENTS.md
claude -> AGENTS.md + CLAUDE.md
gemini -> AGENTS.md + GEMINI.md
multi  -> AGENTS.md + CLAUDE.md + GEMINI.md
```

`--entrypoints` remains available for backward compatibility, but new usage should prefer `--profile`. Do not pass `--profile` and `--entrypoints` together.

## 1. New Repository: Codex

```bash
python scripts/adopt-agent-rules.py /path/to/repo --plan
python scripts/adopt-agent-rules.py /path/to/repo --profile codex --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile codex
```

## 2. New Repository: Claude

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude
```

## 3. New Repository: Gemini

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile gemini --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile gemini
```

## 4. Multi-Agent Repository

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile multi --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile multi
```

## 5. Existing `AGENTS.md`: Merge

Default apply refuses to overwrite an existing `AGENTS.md`.

Use `--merge` when the target repository already has manually written instructions and no `agent-rules` metadata block:

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --merge --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --merge
```

The merge path preserves existing content, adds missing shared sections, and adds metadata used by future checks and updates.

If `--check` finds a shared source URL but no metadata block, it reports:

```text
[WARN] legacy adoption detected; run --merge to add metadata
```

This is a warning in normal checks and a failure with `--strict-check`.

## 6. Latest Status

```bash
python scripts/adopt-agent-rules.py /path/to/repo --check-latest
python scripts/adopt-agent-rules.py /path/to/repo --check-latest --fail-if-outdated
```

This compares:

- local `agent-rules` HEAD
- remote `main` HEAD when reachable
- target `AGENTS.md` metadata `source_commit`
- `.agents/agent-rules/SOURCE_COMMIT` when a local copy exists

Network or git lookup failures are warnings, not fatal errors.

Latest status values:

- `current`: commits match.
- `behind`: the checked commit is an ancestor of the latest source commit.
- `ahead`: the local source commit contains the remote source commit.
- `diverged`: local and remote source commits are both known but neither is an ancestor of the other.
- `different`: commits differ but ancestry could not be proven or the target commit is not an ancestor of the latest source.
- `unknown`: one side of the comparison is missing or could not be determined.

By default, `--check-latest` is informational and exits 0. Use `--fail-if-outdated` or `--strict-check` when automation should fail if:

- local source is `behind`, `different`, or `diverged`
- target `source_commit` is not `current`
- local-copy `SOURCE_COMMIT` is not `current`

## 7. Update From Current Source

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --update --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --update
```

`--update` refreshes the metadata block and managed shared-rule block. Repository-specific sections such as boundaries and validation commands are preserved.

If local `agent-rules` differs from remote `main`, update is blocked by default. Use `--allow-stale-source` only when intentionally updating from the local checkout.

## 8. Local Copy

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy
```

Local copy mode writes:

```text
.agents/agent-rules/
  SOURCE_COMMIT
  AGENTS.md
  CLAUDE.md or GEMINI.md when selected by profile
  rules/
  templates/
  docs/lightweight-adoption.md
  docs/scripted-adoption.md
```

Do not copy `rules/` or `templates/` to the target repository root.

If `.agents/agent-rules/` already exists, a new `--local-copy` apply fails by default. Use one of these explicit modes:

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --update --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --update
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --force
```

During update, each local-copy file is compared with the source file. Unchanged files are reported as `no-op`; changed files are reported as `update`.

## 9. `.gitignore` Collisions

Generated entrypoints must be commit-visible. Before writing, the helper checks each generated file with git:

```bash
git -C /path/to/repo ls-files --error-unmatch -- AGENTS.md
git -C /path/to/repo check-ignore -v -- AGENTS.md
```

If an untracked generated file is ignored, the helper fails. Fix the ignore rule or add narrow exceptions, then re-run with `--dry-run`.

For local copies ignored by `.agents/`, add exceptions such as:

```gitignore
!.agents/
!.agents/agent-rules/
!.agents/agent-rules/**
```

Use `--allow-ignored` only when the ignored state is intentional.

## 10. Detect Validation Commands

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile codex --detect --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile codex --detect
```

`--detect` does not run validation. It suggests commands from repository files such as `CMakeLists.txt`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `package.xml`, `colcon.meta`, and `.github/workflows/`.

When `--validation` is also provided, explicit commands are kept and detected commands are appended without duplicates.

Detected validation commands are written into generated `AGENTS.md` only when `--detect` is included on the apply command, not just the planning command.

## Subdirectory Targets

The helper expects `target_repo` to be the Git repository root. If the path is a subdirectory inside a Git repository:

- `--plan` prints a warning.
- write/apply/update operations fail by default.
- `--allow-subdir-target` must be provided to write under that subdirectory intentionally.

Git tracking and ignore checks always run from the Git root, and generated paths are converted to Git-root-relative paths before calling `git ls-files` or `git check-ignore`.

## Check

```bash
python scripts/adopt-agent-rules.py /path/to/repo --check
python scripts/adopt-agent-rules.py /path/to/repo --check --strict-check
```

`--check` reports `[OK]`, `[WARN]`, and `[FAIL]` items. Failures return exit code 1. Warnings return exit code 0 unless `--strict-check` is used.

## Safety Notes

- The helper never commits in the target repository.
- The helper never pushes to GitHub.
- The helper never runs `git pull`.
- Existing files are not overwritten unless `--force` is passed.
- Use `--force --backup` when intentionally replacing an existing file.
- Submodule mode only prints the recommended command unless a future explicit apply option is implemented.
