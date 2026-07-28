# runtime/

Scripts in this directory are **runtime scripts**: they ship to end-user machines as part of
the swe-workbench plugin. Skills, commands, and agents invoke them as bare `bin/` commands
(`<plugin>/bin` is on `PATH` while the plugin is enabled) — see `bin/` for the wrappers and
"Reference pattern" below for the calling convention. The scripts themselves stay put here;
only the invocation surface moved.

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
| `comment-scan.py` | Advisory comment-quality scanner — reads a unified diff on stdin, prints findings + a footer; never exits non-zero |
| `diff-line-lookup.sh` | Resolve the post-diff line number for a literal code snippet (`path:line`) from a git diff or piped unified diff; refuses to guess on ambiguous matches. Default (no flag) mode is invisible to brand-new untracked files — `git add` (or pass `--staged`) first |
| `doctor.sh` | Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude, python3) |
| `fetch-pr.sh` | Fetch a PR's metadata JSON via `gh pr view`; exits 1 if the PR is inaccessible |
| `gh-timeout.sh` | Run a `gh` call under a per-call deadline (default 60s, override via `GH_TIMEOUT_SECS`); degrades to unbounded `gh` when neither `timeout` nor `gtimeout` is on PATH |
| `new-run-dir.sh` | Allocate a mode-0700 run-scoped scratch dir under `/tmp/swe-workbench-run/` (`mktemp -d`, explicit template); also runs the age-gated (24h) orphan sweep at allocation time |
| `preflight-pr.sh` | Consolidated pre-flight for PR-review skills: `gh auth` gate → `fetch-pr.sh` → emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as `printf %q`-quoted eval-able `KEY=VALUE` lines |
| `reap-run-dir.sh` | Safe `rm -rf` for a single run-scoped scratch dir allocated by `new-run-dir.sh` (depth-exactly-one, name-shape, ownership, and `.git`-absence checks) |
| `reply-and-resolve.sh` | Post a PR review thread reply (REST) and optionally resolve it (GraphQL) |

`comment-scan.py` is the one script in this directory invoked via a wrapper that execs a different
interpreter (`bin/swe-workbench-comment-scan` runs `exec python3 ".../comment-scan.py" "$@"` instead
of `exec bash ".../<name>.sh" "$@"`) — it's a pure diff-in/findings-out function (no git calls of its
own; see `agents/shared/comment-scan.md` for the canonical diff command), and Python's text
processing is a better fit for the per-language comment-syntax analysis than bash. Same `bin/`
wrapper convention applies; only the interpreter differs. `comment-scan.py` itself stays mode 644 —
the wrapper is the executable.

## Reference pattern

Skills confirm the plugin's runtime commands are reachable **once** at the top of their first
executable block (before any worktree is entered), then invoke every runtime script as a bare
`swe-workbench-<name>` command — no path resolution, no `$CLAUDE_PLUGIN_ROOT`:

```bash
command -v swe-workbench-clean-state-files >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
# … later …
swe-workbench-<name> [args...]
```

`<plugin>/bin` is appended to the Bash tool's `PATH` while the plugin is enabled, so
`swe-workbench-<name>` resolves without any path construction. The `command -v` preflight converts
"command not found → exit 127, possibly rationalized away as unavailable" into a loud, actionable
abort ("reinstall or update the swe-workbench plugin") — see `docs/plugin-platform-decisions.md` for
why this replaced the old `$CLAUDE_PLUGIN_ROOT`-existence guard rather than simply dropping it. Each
`bin/` wrapper resolves its sibling `runtime/` script via `dirname "${BASH_SOURCE[0]}"`, never
`CLAUDE_PLUGIN_ROOT` — see any wrapper in `bin/` for the exact form.
