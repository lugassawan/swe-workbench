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
| `gh-timeout.sh` | Run a `gh` call under a per-call deadline (default 60s, override via `GH_TIMEOUT_SECS`); degrades to unbounded `gh` when neither `timeout` nor `gtimeout` is on PATH |
| `preflight-pr.sh` | Consolidated pre-flight for PR-review skills: `gh auth` gate → `fetch-pr.sh` → emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as `printf %q`-quoted eval-able `KEY=VALUE` lines |
| `reply-and-resolve.sh` | Post a PR review thread reply (REST) and optionally resolve it (GraphQL) |

## Reference pattern

Skills bind the plugin root **once** at the top of their first executable block (before any worktree
is entered) and then reference all runtime scripts through `$_RT`:

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
[ -f "$_RT/runtime/clean-state-files.sh" ] || {
  echo "swe-workbench runtime scripts not found under $_RT/runtime — set CLAUDE_PLUGIN_ROOT and retry." >&2
  exit 1
}
# … later …
bash "$_RT/runtime/<name>.sh" [args...]
```

`CLAUDE_PLUGIN_ROOT` is set by the Claude Code plugin runtime to the plugin's checkout root. The
`$(git rev-parse --show-toplevel)` fallback supports local development. The hard-fail guard converts
"script not found → silent inline fallback" into a loud abort, preventing silent bypass when
`CLAUDE_PLUGIN_ROOT` is unset inside an ephemeral PR worktree.
