# Batch-list Generation

`scripts/generate_batch_list.py` discovers Git repositories and writes a
candidate deployment list. It does not install rules or change repositories.
It uses Python's standard library; Python 3.10+ and Git are sufficient.

## Generate and review a list

```bash
python scripts/generate_batch_list.py /path/to/workspace --output /path/to/repos.toml
```

Use an output location outside the shared checkout for machine-specific lists.
The extension selects TOML or plain text. TOML preserves detected adoption
profiles and requires Python 3.11+ when consumed by `adopt.py`. Use `.txt` for
Python 3.10:

```bash
python scripts/generate_batch_list.py /path/to/workspace --output /path/to/repos.txt
```

Review the generated file before deployment. Remove `agent-rules` itself and any
unintended targets. Repositories without adoption metadata have no recorded
profile; the deployment command supplies one.

## Discovery options

| Option | Behavior |
| --- | --- |
| `ROOT` | Directory to scan recursively |
| `--output FILE` | Required output path ending in `.toml` or `.txt` |
| `--adopted-only` | Include only repositories carrying agent-rules adoption metadata |
| `--max-depth N` | Search depth with `--adopted-only`; defaults to 3 |
| `--force` | Overwrite an existing output file |

Ordinary discovery stops descending when it finds a repository. Adopted-only
discovery continues through repository directories so nested adopted repositories
can be found, within the depth limit. Symlink child directories are not followed.

```bash
python scripts/generate_batch_list.py /path/to/workspace \
  --adopted-only --max-depth 4 --output /path/to/adopted.toml
```

The command refuses an existing output file unless `--force` is supplied. A
missing root, unsupported extension, or empty result causes a nonzero exit.

## Deploy the reviewed list

```bash
python scripts/adopt.py --batch /path/to/repos.toml --profile codex --skills --dry-run
python scripts/adopt.py --batch /path/to/repos.toml --profile codex --skills
python scripts/adopt.py --batch /path/to/repos.toml --check --problems-only
```

Per-repository profiles in TOML override the command-line profile. See
[scripted adoption](scripted-adoption.md) for sync, visibility, and conflict
handling, or the [usage index](README.md) for other tools.
