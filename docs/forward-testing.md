# Live Forward Testing

`scripts/forward_test.py` creates a fixture repository, installs shared skills,
runs Codex or Claude Code, and saves execution evidence. It records mechanical
outcomes; a person judges whether the agent response follows the intended skill.

## Prerequisites and first run

Use Python 3.10+, Git, and an installed, authenticated agent CLI. No GUI
dependencies are required. Live runs use the agent account and can incur usage;
they are separate from the deterministic unit-test suite.

```bash
python scripts/forward_test.py --agent codex --out-dir /path/to/results --runs 2
python scripts/forward_test.py --agent claude --out-dir /path/to/results --runs 2
```

Keep results outside the shared checkout. Each invocation creates its own output
directory containing one fixture and evidence set per run. The shared source
defaults to this checkout; `--shared-url` can select another source.

## Cases and options

| Case | Intended skill contract |
| --- | --- |
| `percentage-discount-bug` | Bug investigation with bundled additional work; default case |
| `percentage-discount-review` | Read-only review |
| `percentage-discount-validate` | Validation without implementation changes |
| `percentage-discount-commit` | Preparation and execution of a scoped commit |

```bash
python scripts/forward_test.py --agent codex \
  --case percentage-discount-review --out-dir /path/to/results --runs 2 --strict
```

| Option | Behavior |
| --- | --- |
| `--agent codex\|claude` | Required agent selection |
| `--out-dir DIR` | Required fixture and evidence destination |
| `--case NAME` | Select the fixture and prompt |
| `--runs N` | Positive repeat count; defaults to 1 |
| `--timeout SECONDS` | Positive agent invocation timeout; defaults to 240 |
| `--model MODEL` | Request an explicit model; omission keeps the CLI default |
| `--profile PROFILE` | Override the adoption profile; otherwise matches the agent |
| `--shared-url SOURCE` | Override the shared rules source |
| `--codex-bin`, `--claude-bin` | Override CLI commands |
| `--strict` | Return nonzero for process failures or mutations in non-commit cases |

Strict mode does not grade response quality. Commit cases can change the fixture's
Git state; inspect the saved evidence rather than assuming sandbox flags prevent
a commit.

## Read the results

Each `run-N/` contains `summary.json`, `transcript.jsonl`, `final_report.txt`,
and a fixture repository. Summary evidence includes process status, source/CLI
provenance, changed file paths, and Git HEAD/index comparisons. Setup failures
preserve partial summaries; agent timeouts record exit code 124.

Read the final report and transcript to assess skill selection, scope handling,
validation, and reporting. A successful process or clean fixture does not prove
the response is behaviorally correct. The recorded requested model does not
establish the effective model chosen by the CLI.

See [cross-agent validation](cross-agent-validation.md) for evaluation criteria,
historical findings, and evidence limitations, and the [usage index](README.md)
for deployment tools.
