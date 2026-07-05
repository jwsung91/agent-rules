# Scripted Repository Adoption

Use `scripts/adopt.py` when applying `agent-rules` to multiple repositories or when you want repeatable checking and update behavior.

The script creates root-level agent entrypoints and does not copy root-level `rules/` or `templates/` into the target repository. Full local copies, when requested, are written only under `.agents/agent-rules/`.

## Recommended Workflow

1. Choose an agent profile: `codex`, `claude`, `gemini`, or `all`.
2. Run with `--dry-run`.
3. Apply the files.
4. Edit repository-specific boundaries and validation commands.
5. Run the suggested validation, starting with `git diff --check`.
6. Commit only `.gitignore` in the target repository — agent files are local-only.

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
python scripts/adopt.py /path/to/repo --profile codex --dry-run
python scripts/adopt.py /path/to/repo --profile codex
```

## 2. New Repository: Claude

```bash
python scripts/adopt.py /path/to/repo --profile claude --dry-run
python scripts/adopt.py /path/to/repo --profile claude
```

## 3. New Repository: Gemini

```bash
python scripts/adopt.py /path/to/repo --profile gemini --dry-run
python scripts/adopt.py /path/to/repo --profile gemini
```

## 4. Multi-Agent Repository

```bash
python scripts/adopt.py /path/to/repo --profile all --dry-run
python scripts/adopt.py /path/to/repo --profile all
```

## 5. Existing File: Sync

Default apply refuses to overwrite an existing file.

Use `--sync` when the target repository already has an agent file. The helper automatically selects the right strategy:

- **metadata present** → refreshes the metadata block and managed shared-rule block, preserving repository-specific sections. All three entrypoints (AGENTS.md, CLAUDE.md, GEMINI.md) carry `<!-- agent-rules-managed:start/end -->` markers; content outside the markers is never touched by sync.
- **metadata present, no managed markers** → the file was generated before markers were added to CLAUDE.md/GEMINI.md templates; it is fully regenerated once (manual edits in that file are replaced — keep local content outside the managed block afterwards).
- **no metadata** → merges shared sections into the existing file without overwriting it (AGENTS.md only).

```bash
python scripts/adopt.py /path/to/repo --sync --dry-run
python scripts/adopt.py /path/to/repo --sync
```

`--profile` is optional with `--sync`; the helper infers it from the existing file's metadata. Pass `--profile` explicitly to change the profile.

If `--check` finds a shared source URL but no metadata block, it reports:

```text
[WARN] legacy adoption detected; run --sync to add metadata
```

## 6. Sync From Updated Source

After pulling a new version of `agent-rules`, sync target repositories:

```bash
python scripts/adopt.py /path/to/repo --sync --dry-run
python scripts/adopt.py /path/to/repo --sync
```

If the local `agent-rules` source differs from remote `main`, `--sync` is blocked with an error. Pull from remote first, then re-run.

## 7. Local Copy

```bash
python scripts/adopt.py /path/to/repo --profile claude --local-copy --dry-run
python scripts/adopt.py /path/to/repo --profile claude --local-copy
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
python scripts/adopt.py /path/to/repo --profile claude --local-copy --sync --dry-run
python scripts/adopt.py /path/to/repo --profile claude --local-copy --sync
python scripts/adopt.py /path/to/repo --profile claude --local-copy --force
```

## 8. Multiple Repositories: Batch

Use `--batch` to apply an operation to many repositories at once. The batch file can be TOML (`.toml`) or plain text (`.txt`).

### TOML format

```toml
# repos.toml

[[repos]]
path = "/path/to/api"
profile = "claude"

[[repos]]
path = "/path/to/worker"
profile = "codex"

[[repos]]
path = "/path/to/frontend"
# profile omitted: inferred from existing file metadata
```

Per-repo `profile` overrides the `--profile` flag on the command line.

### Plain text format

```text
# repos.txt
/path/to/api
/path/to/worker
/path/to/frontend
```

### Usage

```bash
# Apply to all repos (dry-run first)
python scripts/adopt.py --batch repos.toml --profile claude --dry-run
python scripts/adopt.py --batch repos.toml --profile claude

# Sync all repos after updating agent-rules
python scripts/adopt.py --batch repos.toml --sync

# Check all repos
python scripts/adopt.py --batch repos.toml --check
```

The helper continues on failure and prints a per-repo summary at the end:

```text
────────────────────────────────────────────────────────────
  /path/to/api
────────────────────────────────────────────────────────────
...
════════════════════════════════════════════════════════════
3 succeeded, 0 warned, 1 failed

Failed:
  - /path/to/broken-repo
```

Exit code is 1 if any repository failed, 2 if none failed but at least one reported only warnings (from `--check`), and 0 otherwise.

### Where to keep the batch file

`repos.toml` is not generated by the script — it is a user-maintained file. Keep it wherever makes sense for your workflow:

- **Outside any repository**: e.g. `~/workspace/repos.toml`. Never committed, purely local.
- **Inside agent-rules**: convenient if the list is shared across a team. Add it to `.gitignore` if paths are machine-specific:

  ```gitignore
  repos.toml
  repos.txt
  ```

  Or track it if the paths are stable and shared (e.g. CI server paths).

## 9. Local-Only Agent Files

Agent entrypoint files (AGENTS.md, CLAUDE.md, GEMINI.md) are **local-only**. The helper automatically adds them to the target repository's `.gitignore` after creating or updating them. They will not be committed to the repository.

This is intentional: agent instruction files are personal workflow tools, not project artifacts.

After adoption, commit only `.gitignore`:

```bash
git add .gitignore
git commit -m "chore: ignore local agent entrypoint files"
```

If an agent file is already in `.gitignore`, the helper skips the `.gitignore` update (no duplicate entry is added) and proceeds normally.

Local copy files (`.agents/agent-rules/`) are different: they are meant to be committed if you want them shared with the team. If `.agents/` is blocked by `.gitignore`, the helper will fail with a message to remove or narrow the ignore rule.

## 10. Validation Command Detection

The helper always inspects the target repository for known build files and suggests matching commands. Detected commands are written into the generated file automatically.

Supported files: `CMakeLists.txt`, `pyproject.toml`, `setup.py`, `requirements.txt`, `package.json`, `Cargo.toml`, `go.mod`, `package.xml`, `colcon.meta`, `.github/workflows/`.

The generated `## Validation` section separates the two sources by confidence:

- **Confirmed for this repository** — `git diff --check` plus any command passed via `--validation`. These are treated as verified.
- **Auto-detected candidates** — commands guessed from the presence of a build file (e.g. `cargo test` just because `Cargo.toml` exists). These are unverified guesses and are labeled accordingly; confirm they actually work before relying on them.

When `--validation` is also provided, explicit commands are always confirmed; detected commands never duplicate an explicit or confirmed command.

## Check

```bash
python scripts/adopt.py /path/to/repo --check
```

`--check` reports `[OK]`, `[WARN]`, and `[FAIL]` items for:

- presence of agent instruction files
- metadata block existence and validity
- required files for the active profile
- source URL and commit traceability
- `.gitignore` visibility
- version status (local source HEAD vs. remote main HEAD)

Exit codes distinguish severity: `0` (clean), `1` (at least one `[FAIL]`), `2` (only `[WARN]`, no `[FAIL]`).

## Subdirectory Targets

The helper expects `target_repo` to be the Git repository root. If the path is a subdirectory inside a Git repository, write operations fail with an error. Run the helper from the repository root instead.

## Safety Notes

- The helper never commits in the target repository.
- The helper never pushes to GitHub.
- The helper never runs `git pull`.
- Existing files are not overwritten unless `--force` is passed.
- Use `--dry-run` to preview all planned changes before applying.
