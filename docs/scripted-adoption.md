# Deploying agent-rules

The deployment tools distribute rules and skills from this checkout into target
repositories. They are local commands, not an automatic post-merge deployment.
Run the examples from the `agent-rules` checkout with Python 3.10 or later;
TOML batch lists require Python 3.11 or later.

## Workflow and Responsibilities

| Stage | Command or component | Result |
| --- | --- | --- |
| Discover | `scripts/generate_batch_list.py` | Candidate repository list; no target changes |
| Select | Review the generated `.toml` or `.txt` | Intended targets and agent profiles |
| Preview | `scripts/adopt.py ... --dry-run` | Planned file and ignore-rule changes |
| Install | `scripts/adopt.py ... --profile codex --skills` | Entrypoint, skills, and merge baselines |
| Update | `scripts/adopt.py ... --sync` | Merge updated shared content into an installation |
| Inspect | `scripts/adopt.py ... --check` | Health and currency report |
| Remove | `scripts/adopt.py /path/to/repo --remove` | Back up and remove owned adoption files |

Use a target path for one repository, or `--batch /path/to/repos.toml` for
installation, sync, and checking across a reviewed list. Review discovered
paths before applying: exclude this shared-source repository, third-party
checkouts, and any projects you do not intend to manage.

- [Install](#install): profiles and shared skills
- [Batch deployment](#batch-deployment): discovery, selection, and batch lists
- [Update](#update): source refresh and local-edit preservation
- [Check](#check): health reports and exit codes
- [Remove](#remove): ownership checks and backups
- [Visibility](#visibility), [offline copy](#offline-copy), and
  [validation commands](#validation-commands): installation options
- [Legacy Codex paths](#legacy-codex-paths): explicit migration
- [Implementation map](#implementation-map): code responsibilities

## Recommended Workflow

1. Choose an agent profile: `codex`, `claude`, `gemini`, or `all`.
2. Choose `--visibility local` (default) or `--visibility tracked`.
3. Add `--skills` when the repository should receive shared agent skills.
4. Run with `--dry-run` (add `--verbose` to see the file contents, not just the actions).
5. Apply the files.
6. Edit repository-specific boundaries and validation commands.
7. Run the suggested validation, starting with `git diff --check`.

## Install

```text
codex  -> AGENTS.md
claude -> CLAUDE.md
gemini -> GEMINI.md
all    -> AGENTS.md + CLAUDE.md + GEMINI.md
```

Each profile creates only the files its agent needs. Apply the `codex` and
`claude` profiles separately when both tools are used without Gemini. Keep
`--profile all` for repositories that also use Gemini.

### Codex

```bash
python scripts/adopt.py /path/to/repo --profile codex --dry-run
python scripts/adopt.py /path/to/repo --profile codex
```

### Claude

```bash
python scripts/adopt.py /path/to/repo --profile claude --dry-run
python scripts/adopt.py /path/to/repo --profile claude
```

### Gemini

```bash
python scripts/adopt.py /path/to/repo --profile gemini --dry-run
python scripts/adopt.py /path/to/repo --profile gemini
```

### Multiple agents and shared skills

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

Install the shared `investigate-bug`, `review-change`, `validate-change`, and
`prepare-commit` skills for Codex and Claude:

```bash
python scripts/adopt.py /path/to/repo --profile codex --skills --dry-run
python scripts/adopt.py /path/to/repo --profile codex --skills
python scripts/adopt.py /path/to/repo --profile claude --skills --dry-run
python scripts/adopt.py /path/to/repo --profile claude --skills
```

The same `SKILL.md` behavioral contracts are installed under each skill name
in `.agents/skills/` and `.claude/skills/`. Agent-specific metadata may coexist
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

## Batch Deployment

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

Add `--adopted-only` to list just the repositories that already carry an
agent-rules metadata block — the answer to "which repositories have adopted
this?", which otherwise takes a hand-rolled `find | grep`:

```bash
python scripts/generate_batch_list.py /path/to/workspace --adopted-only --output repos.toml
```

That search does continue past a repository, because an adopted repository can
sit inside another one — a workspace repo holding per-component repos, say —
and stopping at the outer one would hide every repository under it. Walking
everything is expensive, so it is bounded by `--max-depth` (default 3).
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

A batch `--sync` also reports how many repositories it actually changed:

```text
9 succeeded, 0 warned, 0 failed
2 changed, 7 already current
  - /path/to/api (4 files)
  - /path/to/worker (1 file)
```

`--sync` is idempotent, so "succeeded" alone cannot tell a fleet that was
already current from one this run rewrote.

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

## Update

After pulling a new version of `agent-rules`, sync target repositories:

```bash
python scripts/adopt.py /path/to/repo --sync --dry-run
python scripts/adopt.py /path/to/repo --sync
```

If the local `agent-rules` source differs from remote `main`, `--sync` is blocked with an error. Pull from remote first, then re-run.

### Merge behavior

Default apply refuses to overwrite an existing file.

Use `--sync` when the target repository already has an agent file. The helper automatically selects the right strategy:

- **sync baseline present** → performs a 3-way merge between the previous generated baseline, the locally edited file, and the new shared source. Non-conflicting edits are preserved anywhere in generated entrypoints and installed skills.
- **merge conflict** → stops before writing any file. Use `--dry-run` to inspect the conflict, reconcile the local edit, or use `--force` intentionally.
- **metadata present, baseline absent** → uses the legacy managed-block refresh once and records a baseline for future 3-way merges.
- **metadata present, no managed markers** → refused. The markers are what separates shared content from yours; without them a sync would either discard local edits or leave the old shared sections behind as duplicates. Re-run with `--force` to regenerate from the templates. The previous file is copied under `.agent-rules/backups/<timestamp>/` first.
- **no metadata** → merges shared sections into the existing file without overwriting it (AGENTS.md only).

```bash
python scripts/adopt.py /path/to/repo --sync --dry-run
python scripts/adopt.py /path/to/repo --sync
```

`--profile` is optional with `--sync`; the helper infers it from the existing file's metadata. Pass `--profile` explicitly to change the profile.

Re-running the original adoption command on a repository this helper already
adopted switches to `--sync` and says so, rather than refusing to overwrite.
Use `--force` to regenerate from the templates instead. A file without an
agent-rules metadata block is still refused: it was written by someone else.

`--sync` is idempotent: when the shared source has not moved, it reports every
file under `Skipped:` and leaves them byte-identical. The `generated_at`
timestamp in the metadata block is only refreshed when something else in the
file actually changes, so repeated syncs do not produce empty diffs (or, under
`--visibility tracked`, no-content commits). Missing `.gitignore` entries are
still repaired on a sync that writes nothing.

### What --sync will and will not rewrite

Generated entrypoints mark the regions that belong to the adopting repository:

```markdown
## Repository-specific Boundaries

<!-- agent-rules-local:boundaries:start -->
- no vendored dependencies
<!-- agent-rules-local:boundaries:end -->
```

With a baseline present, `--sync` uses a three-way merge to preserve
non-conflicting edits throughout the file. The marked regions identify the
repository-specific boundaries and validation settings, including during legacy
refreshes without a baseline. Keep the marker lines themselves.

Ownership is marked per region rather than by regenerating only the managed
block, because shared content lives outside that block as well -- the
`## Validation` guidance and the whole `## Final Report` section -- and it has
been revised since repositories started adopting. Freezing everything outside
the managed block would strand them on an old copy.

Adoptions created before the markers existed pick them up on their first
`--sync`, which recovers the configured values from the template text around
them. Nothing needs to be re-entered.

### Backups

`--force` replaces a file wholesale. Before it does, the existing file is
copied to `.agent-rules/backups/<timestamp>/<path>` — one directory per run,
so a `--profile all --force` keeps its three files together. Backups are
local-only, like the baselines and generated entrypoints.

Removal also backs up owned files before deleting them. Baselines record the
previous generated content for merging; they are not backups of local edits.

Baselines are stored under `.agent-rules/bases/`. Local visibility ignores
them together with generated files; tracked visibility keeps them trackable so
other team members can reproduce later merges. A previously installed,
locally modified skill without a baseline cannot be merged safely: restore it
or use `--force` once to establish a new baseline.

If `--check` finds a shared source URL but no metadata block, it reports:

```text
[WARN] legacy adoption detected; run --sync to add metadata
```

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

Shared Skill installation, sync baselines, and the Codex/Claude `SKILL.md`
contract are verified automatically when the repository already has skills
installed — the same inference `--sync` uses, so a deleted skill file is
reported as `[FAIL]` by a plain `--check`. Pass `--skills` explicitly to
require them in a repository that has none yet, and pass the intended
visibility so tracked and local files are evaluated correctly:

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

The currency comparison is reported only for files that are actually
installed. A file missing from the target repository is reported as `[FAIL]`
once and draws no staleness verdict, since reinstalling it replaces the
content the verdict would describe.

Every run leads with a tally:

```text
Summary: 0 FAIL · 3 WARN · 1 NOTE · 53 OK
```

Add `--problems-only` to drop the passing lines and print just what needs
attention. The summary still counts what was suppressed, and a clean run says
`No problems found.`

```bash
python scripts/adopt.py /path/to/repo --check --problems-only
```

Exit codes distinguish severity: `0` (clean), `1` (at least one `[FAIL]`), `2` (only `[WARN]`, no `[FAIL]`).

`[NOTE]` is informational and does not affect the exit code. It covers states
with nothing to fix -- for example `--profile all --skills`, where `GEMINI.md`
has no shared-skill path because Gemini has no shared-skill convention yet.

## Remove

```bash
python scripts/adopt.py /path/to/repo --remove --dry-run
python scripts/adopt.py /path/to/repo --remove
```

`--remove` deletes the files this helper generated for the active profile:
the entrypoints, the installed shared skills, and the sync baselines. The
profile is inferred from the existing metadata when `--profile` is omitted.

Everything it deletes is copied to `.agent-rules/backups/<timestamp>/` first.
That matters more than it sounds: an entrypoint holds the repository's own
boundaries and validation commands, and a local-only adoption is not in Git,
so the backup is the only copy.

Removal refuses the entire plan when ownership cannot be established:

- Entrypoints require agent-rules metadata.
- Skill files require their per-file sync baselines. A known skill name is
  insufficient; missing or untrustworthy baselines block removal even with
  `--force`.
- Symlink files and paths resolving outside the target repository are refused.

Tracked files also block removal unless `--force` is explicitly selected.
That override permits removing tracked, owned files; it does not bypass the
ownership checks above.

Left alone deliberately:

- `.agents/agent-rules/` — a local copy is meant to be committed and shared,
  so dropping it is a separate decision from undoing the adoption.
- Anything under `.agent-rules/backups/`.
- `.gitignore` rules the repository wrote itself. Only the
  `# agent-rules (local only)` block is removed.

The backup survives with no ignore rule left to hide it, so it shows up in
`git status` until you delete it — deliberately, since it is the only copy of
what was removed.

## Visibility

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

Entries are written as one line per entrypoint plus one directory pattern per
installed skill, with a single pattern covering the sync baselines:

```gitignore
# agent-rules (local only)
/AGENTS.md
/CLAUDE.md
/.agent-rules/bases/
/.agents/skills/investigate-bug/
/.claude/skills/investigate-bug/
```

Directory patterns keep the list proportional to the number of skills rather
than the number of files inside them, so adding a file to a skill upstream
does not grow every adopted repository's `.gitignore`. Each skill is named
individually instead of ignoring `.agents/skills/` or `.claude/skills/`
wholesale, so skills the repository wrote itself are untouched.

A `.gitignore` written by an earlier version listed every generated file
separately (30 entries for `--profile all --skills`). The next `--sync`
replaces those entries with the equivalent directory patterns, in place and
without disturbing unrelated rules, and reports how many it replaced. Nothing
changes about which files end up ignored.

After adoption, commit only `.gitignore`:

```bash
git add .gitignore
git commit -m "chore: ignore local agent entrypoint files"
```

If an agent file is already in `.gitignore`, the helper skips the `.gitignore` update (no duplicate entry is added) and proceeds normally.

Local copy files (`.agents/agent-rules/`) are different: they are meant to be committed if you want them shared with the team. If `.agents/` is blocked by `.gitignore`, the helper will fail with a message to remove or narrow the ignore rule.

## Offline Copy

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

## Validation Commands

The helper always inspects the target repository for known build files and suggests matching commands. Detected commands are written into the generated file automatically.

Supported files: `CMakeLists.txt`, `pyproject.toml`, `setup.py`, `requirements.txt`, `package.json`, `Cargo.toml`, `go.mod`, `package.xml`, `colcon.meta`, `.github/workflows/`.

The generated `## Validation` section separates the two sources by confidence:

- **Confirmed for this repository** — `git diff --check` plus any command passed via `--validation`. These are treated as verified.
- **Auto-detected candidates** — commands guessed from the presence of a build file (e.g. `cargo test` just because `Cargo.toml` exists). These are unverified guesses and are labeled accordingly; confirm they actually work before relying on them.

When `--validation` is also provided, explicit commands are always confirmed; detected commands never duplicate an explicit or confirmed command.

## Subdirectory Targets

The helper expects `target_repo` to be the Git repository root. If the path is a subdirectory inside a Git repository, write operations fail with an error. Run the helper from the repository root instead.

## Safety Notes

- The helper never commits in the target repository.
- The helper never pushes to GitHub.
- The helper never runs `git pull`.
- Default installation refuses unmanaged existing files. `--sync` can merge
  existing content; `--force` replaces it with a backup.
- Use `--dry-run` to preview all planned changes before applying.

## Legacy Codex Paths

New Codex installations use `.agents/skills/`, the current documented local
skill-discovery root. Claude continues to use `.claude/skills/`.

Existing shared skills under `.codex/skills/` are deliberately retained during
sync, check, and removal. Their local edits and sync baselines remain usable;
commands warn that legacy-path retention does not verify current Codex discovery.
The helper refuses to proceed when its shared skill names occur in both roots,
rather than silently picking one copy. Other repository-owned skill names are
not moved or removed.

To migrate an existing installation deliberately:

1. Back up the affected files, including local edits, and stop agents using them.
2. Verify that the destination shared-skill directories do not exist. Reconcile
   any duplicates manually; do not overwrite them with `--force`.
3. Move each adopted shared-skill directory from `.codex/skills/<name>` to
   `.agents/skills/<name>`, preserving its entire contents. Move its matching
   baseline directory from `.agent-rules/bases/.codex/skills/<name>` to
   `.agent-rules/bases/.agents/skills/<name>` as well. Preserve any unrelated
   skills in either root. If an installed skill file was deleted locally, move
   its baseline too so sync can still recognize the installation.
4. Run the normal `--sync --dry-run`, then `--sync`. These update entrypoint
   references and managed ignore patterns and merge against the moved baselines.
5. Run `--check` and verify skill discovery in the target Codex runtime. File
   presence and adoption checks alone do not prove a live model selected a skill.

Migration is explicit; ordinary sync does not move directories or discard user
changes. Fresh installation, legacy sync/removal, duplicate detection, and an
explicit path move followed by sync are covered by deterministic tests.

## Implementation Map

The public entrypoints remain stable; implementation modules live under
`scripts/agent_rules/`.

| Layer | Files | Responsibility |
| --- | --- | --- |
| Public commands | `scripts/adopt.py`, `scripts/generate_batch_list.py` | Adoption API/CLI and repository discovery |
| Dispatch | `cli.py`, `batch.py` | Arguments, operation selection, per-repository batch execution |
| Plan | `source.py`, `metadata.py`, `render.py`, `planning.py` | Source/profile detection, content rendering, merge planning |
| Apply | `applying.py`, `gitignore.py` | Write planned files, backups, visibility rules |
| Inspect and remove | `checking.py`, `removal.py` | Health reports and ownership-aware removal |
| Shared support | `models.py`, `constants.py`, `gitio.py` | Data structures, policy constants, Git helpers |

`rules/` and `skills/` define behavior; `templates/` defines generated
entrypoints. `tests/test_adopt.py` and `tests/test_generate_batch_list.py` cover
installation and discovery. `scripts/forward_test.py` evaluates agent execution
separately; it is not part of deployment.
