# Scripted Repository Adoption

Use `scripts/adopt-agent-rules.py` when applying `agent-rules` to multiple repositories or when you want repeatable checking and update behavior.

The script creates root-level agent entrypoints and does not copy root-level `rules/` or `templates/` into the target repository. Full local copies, when requested, are written only under `.agents/agent-rules/`.

## Recommended Workflow

1. Choose an agent profile: `codex`, `claude`, `gemini`, or `all`.
2. Run with `--dry-run`.
3. Apply the files.
4. Edit repository-specific boundaries and validation commands.
5. Run the suggested validation, starting with `git diff --check`.
6. Commit in the target repository after review.

## Profiles

```text
codex  -> AGENTS.md
claude -> CLAUDE.md
gemini -> GEMINI.md
all    -> AGENTS.md + CLAUDE.md + GEMINI.md
```

Each profile creates only the files its agent needs. Use `--profile all` when the repository is used by multiple agent tools.

## 1. New Repository: Codex

```bash
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
python scripts/adopt-agent-rules.py /path/to/repo --profile all --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile all
```

## 5. Existing File: Sync

Default apply refuses to overwrite an existing file.

Use `--sync` when the target repository already has an agent file. The helper automatically selects the right strategy:

- **metadata present** → refreshes the metadata block and managed shared-rule block, preserving repository-specific sections.
- **no metadata** → merges shared sections into the existing file without overwriting it (AGENTS.md only).

```bash
python scripts/adopt-agent-rules.py /path/to/repo --sync --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --sync
```

`--profile` is optional with `--sync`; the helper infers it from the existing file's metadata. Pass `--profile` explicitly to change the profile.

If `--check` finds a shared source URL but no metadata block, it reports:

```text
[WARN] legacy adoption detected; run --sync to add metadata
```

## 6. Sync From Updated Source

After pulling a new version of `agent-rules`, sync target repositories:

```bash
python scripts/adopt-agent-rules.py /path/to/repo --sync --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --sync
```

If the local `agent-rules` source differs from remote `main`, `--sync` is blocked with an error. Pull from remote first, then re-run.

## 7. Local Copy

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy
```

Local copy mode writes:

```text
.agents/agent-rules/
  SOURCE_COMMIT
  AGENTS.md / CLAUDE.md / GEMINI.md (selected by profile)
  rules/
  templates/
  docs/lightweight-adoption.md
  docs/scripted-adoption.md
```

Do not copy `rules/` or `templates/` to the target repository root.

If `.agents/agent-rules/` already exists, a new `--local-copy` apply fails by default. Use `--sync` or `--force` to refresh:

```bash
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --sync --dry-run
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --sync
python scripts/adopt-agent-rules.py /path/to/repo --profile claude --local-copy --force
```

## 8. `.gitignore` Collisions

Generated entrypoints must be commit-visible. Before writing, the helper checks each generated file with git:

```bash
git -C /path/to/repo ls-files --error-unmatch -- CLAUDE.md
git -C /path/to/repo check-ignore -v -- CLAUDE.md
```

If an untracked generated file is ignored, the helper fails with a recommended fix. Remove or narrow the ignore rule, or add narrow exceptions to `.gitignore`:

```gitignore
!CLAUDE.md
```

For local copies, add exceptions such as:

```gitignore
!.agents/
!.agents/agent-rules/
!.agents/agent-rules/**
```

## 9. Validation Command Detection

The helper always inspects the target repository for known build files and suggests matching commands. Detected commands are written into the generated file automatically.

Supported files: `CMakeLists.txt`, `pyproject.toml`, `setup.py`, `requirements.txt`, `package.json`, `Cargo.toml`, `go.mod`, `package.xml`, `colcon.meta`, `.github/workflows/`.

When `--validation` is also provided, explicit commands come first and detected commands are appended without duplicates.

## Check

```bash
python scripts/adopt-agent-rules.py /path/to/repo --check
```

`--check` reports `[OK]`, `[WARN]`, and `[FAIL]` items for:

- presence of agent instruction files
- metadata block existence and validity
- required files for the active profile
- source URL and commit traceability
- `.gitignore` visibility
- version status (local source HEAD vs. remote main HEAD)

Both warnings and failures return exit code 1.

## Subdirectory Targets

The helper expects `target_repo` to be the Git repository root. If the path is a subdirectory inside a Git repository, write operations fail with an error. Run the helper from the repository root instead.

## Safety Notes

- The helper never commits in the target repository.
- The helper never pushes to GitHub.
- The helper never runs `git pull`.
- Existing files are not overwritten unless `--force` is passed.
- Use `--dry-run` to preview all planned changes before applying.
