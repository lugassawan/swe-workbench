# bin/

Scripts in this directory are **plugin-runtime scripts**: they ship to end-user machines as part
of the swe-workbench plugin. Skills, commands, and agents invoke them as bare commands
(`<plugin>/bin` is on `PATH` while the plugin is enabled) — see "Reference pattern" below for the
calling convention. There is no separate wrapper/implementation split — each script here is the
full implementation, invocable directly by its bare `swe-workbench-<name>` command name.

## Convention

| Directory | Purpose | Who runs it |
|-----------|---------|-------------|
| `bin/` | Plugin-runtime scripts executed on end-user machines | Skills / commands / agents at runtime |
| `scripts/` | Repo-dev / CI tooling: release, setup, validation | Developers from a checkout; CI pipelines |

## Current scripts

| Script | Purpose |
|--------|---------|
| `swe-workbench-clean-ephemeral` | Safe `rm -rf` for ephemeral git worktrees (sanity-checked before removal) |
| `swe-workbench-clean-state-files` | Safe `rm -f` for per-invocation `/tmp` state files |
| `swe-workbench-comment-scan` | Advisory comment-quality scanner — reads a unified diff on stdin, prints findings + a footer; never exits non-zero |
| `swe-workbench-diff-line-lookup` | Resolve the post-diff line number for a literal code snippet (`path:line`) from a git diff or piped unified diff; refuses to guess on ambiguous matches. Default (no flag) mode is invisible to brand-new untracked files — `git add` (or pass `--staged`) first |
| `swe-workbench-doctor` | Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude, python3) |
| `swe-workbench-fetch-pr` | Fetch a PR's metadata JSON via `gh pr view`; exits 1 if the PR is inaccessible |
| `swe-workbench-gh-timeout` | Run a `gh` call under a per-call deadline (default 60s, override via `GH_TIMEOUT_SECS`); degrades to unbounded `gh` when neither `timeout` nor `gtimeout` is on PATH |
| `swe-workbench-lsp` | Stdlib-only LSP JSON-RPC client — semantic code navigation (`refs`/`def`/`impl`/`callers`/`callees`/`hover`/`symbols`/`wsymbols`/`check`) reachable via `Bash` regardless of whether the harness's own `LSP` tool is wired up for subagents |
| `swe-workbench-new-run-dir` | Allocate a mode-0700 run-scoped scratch dir under `/tmp/swe-workbench-run/` (`mktemp -d`, explicit template); also runs the age-gated (24h) orphan sweep at allocation time |
| `swe-workbench-pr-review-submit` | Posting mechanism for workflow-pr-review-post's `## Post` section: fetch review threads (paginated), Jaccard dedup + 👍 reactions, diff-line pre-validate, pr-level batching, self-review/diff-scoping decision flip, atomic Reviews-API submit with a bounded 422 retry and a per-comment fallback. `--findings-json <path\|->` in; `printf %q`-quoted `KEY=VALUE` lines out |
| `swe-workbench-reap-run-dir` | Safe `rm -rf` for a single run-scoped scratch dir allocated by `swe-workbench-new-run-dir` (depth-exactly-one, name-shape, ownership, and `.git`-absence checks) |
| `swe-workbench-reap-session-scratch` | Safe content-clear (directory preserved) for the current harness session's scratchpad, resolved via `$CLAUDE_CODE_SESSION_ID` and a filesystem glob — no path argument; any guard failure is a silent no-op |
| `swe-workbench-reply-and-resolve` | Post a PR review thread reply (REST) and optionally resolve it (GraphQL) |
| `swe-workbench-skill-script` | Invoke a skill-local `scripts/<name>.sh` helper (`swe-workbench-skill-script <skill> <script> [args...]`) — rejects traversal, resolves the plugin root itself so no skill has to |
| `swe-workbench-sync-pr-metadata` | Apply a revised title and/or body to an existing PR (address-feedback Phase 6 drift sync) |

`swe-workbench-comment-scan`, `swe-workbench-lsp`, and `swe-workbench-pr-review-submit` are the
three scripts in this directory with a `#!/usr/bin/env python3` shebang instead of
`#!/usr/bin/env bash`. `comment-scan` is a pure diff-in/findings-out function (no git calls of its
own; see `shared/agents/comment-scan.md` for the canonical diff command); `pr-review-submit` does
call `git`/`gh` but needed Python's JSON and multi-call state-machine handling (422 retry,
read-your-write confirmation) more than bash's process-spawning idioms; `lsp` speaks JSON-RPC
framing to a spawned language server subprocess, which needs a real threaded reader loop bash
can't give it. Same bare-command convention applies; only the interpreter differs.

## Reference pattern

Skills confirm the plugin's runtime commands are reachable **once** at the top of their first
executable block (before any worktree is entered), then invoke every script as a bare
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
abort ("reinstall or update the swe-workbench plugin") — see [docs/plugin-platform-decisions.md](https://github.com/lugassawan/swe-workbench/blob/main/docs/plugin-platform-decisions.md) for
why this replaced the old `$CLAUDE_PLUGIN_ROOT`-existence guard rather than simply dropping it. A
script that calls a sibling script (e.g. `swe-workbench-preflight-pr` calling
`swe-workbench-fetch-pr`) resolves it via `dirname "$0"`/`dirname "${BASH_SOURCE[0]}"`, never a bare
PATH lookup and never `CLAUDE_PLUGIN_ROOT` — see any script with a sibling call in `bin/` for the
exact form.

A skill with its own `scripts/` helpers (e.g. `swe-workbench:workflow-cleanup-merged`, `swe-workbench:workflow-branch-sync`)
never constructs a path to them either. It invokes `swe-workbench-skill-script <skill> <script>
[args...]`, which resolves the plugin root itself and execs the target — see
[docs/plugin-platform-decisions.md](https://github.com/lugassawan/swe-workbench/blob/main/docs/plugin-platform-decisions.md) for why this replaced the doctor-anchor `_RT=` derivation that
briefly stood in for it. The dispatcher always execs the target via `bash` (mirroring
`swe-workbench-fetch-pr`'s sibling-call form) rather than relying on the target's own shebang, so
every skill-local `scripts/*.sh` helper is assumed to be bash.
