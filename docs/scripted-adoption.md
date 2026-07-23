# Scripted Repository Adoption

Use `scripts/adopt.py` when applying `agent-rules` to multiple repositories or when you want repeatable checking and update behavior.

The script creates root-level agent entrypoints and does not copy root-level `rules/` or `templates/` into the target repository. Full local copies, when requested, are written only under `.agents/agent-rules/`.

## Recommended Workflow

1. Choose an agent profile: `codex`, `claude`, `gemini`, or `all`.
2. Choose `--visibility local` (default) or `--visibility tracked`.
3. Add `--skills` when the repository should receive shared agent skills.
4. Run with `--dry-run`.
5. Apply the files.
6. Edit repository-specific boundaries and validation commands.
7. Run the suggested validation, starting with `git diff --check`.

## Profiles

```text
codex  -> AGENTS.md
claude -> CLAUDE.md
gemini -> GEMINI.md
all    -> AGENTS.md + CLAUDE.md + GEMINI.md
```

Each profile creates only the files its agent needs. Apply the `codex` and
`claude` profiles separately when both tools are used without Gemini. Keep
`--profile all` for repositories that also use Gemini.

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
python scripts/adopt.py /path/to/repo --profile codex --dry-run
python scripts/adopt.py /path/to/repo --profile codex
python scripts/adopt.py /path/to/repo --profile claude --dry-run
python scripts/adopt.py /path/to/repo --profile claude
```

Preview which shared skills `--skills` installs and what each is for (no target
repository, git, or profile required):

```bash
python scripts/adopt.py --list-skills
```

Install the shared `investigate-bug`, `review-change`, and `validate-change`
skills for Codex and Claude:

```bash
python scripts/adopt.py /path/to/repo --profile codex --skills --dry-run
python scripts/adopt.py /path/to/repo --profile codex --skills
python scripts/adopt.py /path/to/repo --profile claude --skills --dry-run
python scripts/adopt.py /path/to/repo --profile claude --skills
```

The same `SKILL.md` behavioral contracts are installed under each skill name
in `.codex/skills/` and `.claude/skills/`. Agent-specific metadata may coexist
with those shared contracts.

`--skills` also injects a `## Shared Skills` section into the generated
`AGENTS.md` and `CLAUDE.md` (inside the managed block), directing the agent to
invoke the appropriate installed skill. The always-loaded entrypoint proved
necessary when a bug report bundled unrelated work; it also carries the
explicit review trigger. See `docs/cross-agent-validation.md` for the tested
bug-investigation and change-review behavior, targeted mitigation results, and
remaining environment-specific execution gaps.
`GEMINI.md` is not changed because no shared skills are installed for Gemini.
Existing adoptions gain the section via `--sync --skills`; a plain `--sync`
also detects already-installed shared skills automatically, so the section is
not stripped when the flag is omitted.

Claude Code watches an already-known `.claude/skills/` directory for file
changes, so a later `--skills --sync` update is picked up by an already-running
Claude Code session without restarting it. The **first** `--skills` install in a
repository creates the `.claude/skills/` directory itself; if a Claude Code
session was already running in that repository before the install, restart the
session so it starts watching the new directory.

## 5. Existing File: Sync

Default apply refuses to overwrite an existing file.

Use `--sync` when the target repository already has an agent file. The helper automatically selects the right strategy:

- **sync baseline present** → performs a 3-way merge between the previous generated baseline, the locally edited file, and the new shared source. Non-conflicting edits are preserved anywhere in generated entrypoints and installed skills.
- **merge conflict** → stops before writing any file. Use `--dry-run` to inspect the conflict, reconcile the local edit, or use `--force` intentionally.
- **metadata present, baseline absent** → uses the legacy managed-block refresh once and records a baseline for future 3-way merges.
- **metadata present, no managed markers** → the file was generated before markers were added to CLAUDE.md/GEMINI.md templates; it is fully regenerated once (manual edits in that file are replaced — keep local content outside the managed block afterwards).
- **no metadata** → merges shared sections into the existing file without overwriting it (AGENTS.md only).

```bash
python scripts/adopt.py /path/to/repo --sync --dry-run
python scripts/adopt.py /path/to/repo --sync
```

`--profile` is optional with `--sync`; the helper infers it from the existing file's metadata. Pass `--profile` explicitly to change the profile.

Baselines are stored under `.agent-rules/bases/`. Local visibility ignores
them together with generated files; tracked visibility keeps them trackable so
other team members can reproduce later merges. A previously installed,
locally modified skill without a baseline cannot be merged safely: restore it
or use `--force` once to establish a new baseline.

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

### Generating the batch file

`scripts/generate_batch_list.py` builds a `repos.toml`/`repos.txt` by scanning a
root folder for Git repositories:

```bash
python scripts/generate_batch_list.py /path/to/workspace --output repos.toml
```

It walks the root recursively looking for a `.git` entry; once a directory is
identified as a repo, it does not search inside it further, so a submodule or
vendored repo nested inside a found repo isn't picked up as a separate entry.
For every repo found, it checks for existing agent-rules metadata (via the same
lookup `--sync`/`--check` use) and fills in `profile` when found; otherwise the
entry is left without a `profile` (same fallback behavior as a hand-written
entry: `--batch --profile` on the command line applies, or it's inferred at
`--check`/`--sync` time). Output format is chosen by the `--output` extension
(`.toml` or `.txt`); `--force` overwrites an existing output file. It's an error
if the root doesn't exist or no repositories are found under it.

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

`repos.toml` is a user-maintained file — write it by hand or with `scripts/generate_batch_list.py` (above). Keep it wherever makes sense for your workflow:

- **Outside any repository**: e.g. `~/workspace/repos.toml`. Never committed, purely local.
- **Inside agent-rules**: convenient if the list is shared across a team. Add it to `.gitignore` if paths are machine-specific:

  ```gitignore
  repos.toml
  repos.txt
  ```

  Or track it if the paths are stable and shared (e.g. CI server paths).

## 9. Generated File Visibility

The default, `--visibility local`, adds generated entrypoints and installed
skill files to the target repository's `.gitignore`.

Use `--visibility tracked` to make the generated files team-visible:

```bash
python scripts/adopt.py /path/to/repo --profile codex --skills --visibility tracked
```

Tracked mode refuses to proceed when a generated output is ignored and
untracked. Remove or narrow the matching ignore rule first.

### Local-only files

Local visibility ignores only the entrypoints and skills selected by the active
profile. It does not add unused agent entrypoint names.

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

Add `--skills` to verify shared Skill installation, sync baselines, and the
Codex/Claude `SKILL.md` contract. Pass the intended visibility so tracked and
local files are evaluated correctly:

```bash
python scripts/adopt.py /path/to/repo --check --skills --visibility tracked
```

`--check --skills` also compares each installed skill file's sync baseline
against the **local shared source** — the literal file on disk in the
`agent-rules` checkout the helper is running from, not a Git commit. An
uncommitted edit to a local skill file already counts as a change to sync,
consistent with every other read the helper does from that checkout. `[WARN]
... is behind the local shared source; run --sync to update` means the target
repository's installed skill predates that local change and needs `--sync`,
even if both its Codex and Claude copies still match each other.

Exit codes distinguish severity: `0` (clean), `1` (at least one `[FAIL]`), `2` (only `[WARN]`, no `[FAIL]`).

## Subdirectory Targets

The helper expects `target_repo` to be the Git repository root. If the path is a subdirectory inside a Git repository, write operations fail with an error. Run the helper from the repository root instead.

## Safety Notes

- The helper never commits in the target repository.
- The helper never pushes to GitHub.
- The helper never runs `git pull`.
- Existing files are not overwritten unless `--force` is passed.
- Use `--dry-run` to preview all planned changes before applying.
