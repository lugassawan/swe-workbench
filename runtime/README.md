# runtime/

Scripts in this directory are **runtime scripts**: they ship to end-user machines as part of
the swe-workbench plugin and are invoked at runtime by skills, commands, and agents via
`$CLAUDE_PLUGIN_ROOT/runtime/<name>.sh`.

## Convention

| Directory | Purpose | Who runs it |
|-----------|---------|-------------|
| `runtime/` | Plugin-runtime scripts executed on end-user machines | Skills / commands / agents at runtime |
| `scripts/` | Repo-dev / CI tooling: release, setup, validation | Developers from a checkout; CI pipelines |

## Current runtime scripts

| Script | Purpose |
|--------|---------|
| `clean-ephemeral.sh` | Safe `rm -rf` for ephemeral git worktrees (sanity-checked before removal) |
| `clean-state-files.sh` | Safe `rm -f` for per-invocation `/tmp` state files |
| `doctor.sh` | Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude) |
| `fetch-pr.sh` | Fetch a PR's metadata JSON via `gh pr view`; exits 1 if the PR is inaccessible |
| `reply-and-resolve.sh` | Post a PR review thread reply (REST) and optionally resolve it (GraphQL) |

## Reference pattern

Skills and commands invoke these scripts with:

```bash
bash "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/runtime/<name>.sh" [args...]
```

`CLAUDE_PLUGIN_ROOT` is set by the Claude Code plugin runtime to the repo root. The
`$(git rev-parse --show-toplevel)` fallback supports local development from a checkout.
