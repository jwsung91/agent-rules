# Scripted Repository Adoption

Use `scripts/adopt-agent-rules.py` when applying `agent-rules` to multiple repositories or when you want a repeatable adoption check.

The script creates a repository-local `AGENTS.md` and, optionally, thin tool-specific entrypoints such as `CLAUDE.md` and `GEMINI.md`. It does not copy the full `rules/` or `templates/` directories by default.

## Basic Usage

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --dry-run
python scripts/adopt-agent-rules.py /path/to/target-repo
python scripts/adopt-agent-rules.py /path/to/target-repo --entrypoints claude,gemini
python scripts/adopt-agent-rules.py /path/to/target-repo --check
```

## Custom Values

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo \
  --boundary "Do not rename public APIs unless explicitly requested" \
  --validation "git diff --check"
```

## Safety Options

By default, the script refuses to overwrite existing target files.

```bash
python scripts/adopt-agent-rules.py /path/to/target-repo --dry-run
python scripts/adopt-agent-rules.py /path/to/target-repo --force
python scripts/adopt-agent-rules.py /path/to/target-repo --force --backup
```

## Recommended Workflow

1. Run with `--dry-run` first.
2. Apply without `--dry-run` after checking the generated content.
3. Edit `AGENTS.md` for repository-specific boundaries and validation commands.
4. Run `git diff --check` in the target repository.
5. Commit with `docs(agent): adopt shared agent rules`.

## Design Intent

This helper exists to make lightweight adoption consistent across repositories. It is not an enforcement mechanism and does not replace repository-local checks or human review.
