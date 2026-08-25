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
| `swe-workbench-address-feedback-fetch` | Fetch + eligibility projection for `swe-workbench:workflow-address-feedback` Phase 1 (`--pr <N>`) — wraps `swe-workbench-preflight-pr`, short-circuits on a non-OPEN PR before any paginated fetch, otherwise paginates `reviewThreads` (per-thread `eligible`/`skip_reason` projection) and REST PR comments (bot/owner-exclusion + handled-marker/manual-reply eligibility) and atomically writes the three snapshot files `swe-workbench-sweep-residuals` hardcodes. Manifest of paths/counts only — thread and comment records stay in the snapshot files. Envelope schema `swb.address-feedback-fetch/1` |
| `swe-workbench-address-feedback-worktree` | Worktree acquire/reconcile/release lifecycle for `swe-workbench:workflow-address-feedback` Phase 2/Phase 7 (`acquire --pr <N> --branch <PR_BRANCH>`, `release --pr <N> --path <abs-path> --branch <PR_BRANCH> --created <true\|false>`) — reuse-current/reuse-existing/create-via-rimba/create-via-git, fast-forward or diverged-warn reconcile, deps install; release is path-keyed only (never branch-keyed) and gated by an ownership receipt so it can never remove a worktree it did not itself create, or delete the PR's real head branch. Two envelopes: `swb.address-feedback-worktree-acquire/1`, `swb.address-feedback-worktree-release/1` |
| `swe-workbench-apply-conflict-resolution` | Apply a keep-mine/keep-main conflict resolution to one file — validates a merge/rebase is in progress, the declared `--operation` matches it, and the path is unmerged, then translates intent to git's `--ours`/`--theirs` (inverted under rebase vs merge) and stages the result |
| `swe-workbench-clean-ephemeral` | Safe `rm -rf` for ephemeral git worktrees (sanity-checked before removal) |
| `swe-workbench-clean-state-files` | Safe `rm -f` for per-invocation `/tmp` state files |
| `swe-workbench-comment-scan` | Advisory comment-quality scanner — reads a unified diff on stdin, prints findings + a footer; never exits non-zero |
| `swe-workbench-diff-line-lookup` | Resolve the post-diff line number for a literal code snippet (`path:line`) from a git diff or piped unified diff; refuses to guess on ambiguous matches. Default (no flag) mode is invisible to brand-new untracked files — `git add` (or pass `--staged`) first |
| `swe-workbench-doctor` | Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude, python3) |
| `swe-workbench-fetch-pr` | Fetch a PR's metadata JSON via `gh pr view`; exits 1 if the PR is inaccessible |
| `swe-workbench-gh-timeout` | Run a `gh` call under a per-call deadline (default 60s, override via `GH_TIMEOUT_SECS`); degrades to unbounded `gh` when neither `timeout` nor `gtimeout` is on PATH |
| `swe-workbench-lsp` | Stdlib-only LSP JSON-RPC client — semantic code navigation (`refs`/`def`/`impl`/`callers`/`callees`/`hover`/`symbols`/`wsymbols`/`check`) reachable via `Bash` regardless of whether the harness's own `LSP` tool is wired up for subagents |
| `swe-workbench-new-run-dir` | Allocate a mode-0700 run-scoped scratch dir under `/tmp/swe-workbench-run/` (`mktemp -d`, explicit template); also runs the age-gated (24h) orphan sweep at allocation time |
| `swe-workbench-pr-review-submit` | Posting mechanism for workflow-pr-review-post's `## Post` section: fetch review threads (paginated), Jaccard dedup + 👍 reactions, diff-line pre-validate, pr-level batching, self-review/diff-scoping decision flip, atomic Reviews-API submit with a bounded 422 retry and a per-comment fallback. `--findings-json <path\|->` in; one JSON envelope out (schema `swb.pr-review-submit/1` — see [Result contract](#result-contract)) |
| `swe-workbench-preflight-commit` | Read-only preflight over the staged file set for `swe-workbench:workflow-commit-and-pr`: one JSON envelope (schema `swb.preflight-commit/1`) classifying secret-shaped filenames (`suspicious`) and whether every staged path is documentation-only (`docs_only`); fails closed — a non-zero exit never means "clean" |
| `swe-workbench-reap-run-dir` | Safe `rm -rf` for a single run-scoped scratch dir allocated by `swe-workbench-new-run-dir` (depth-exactly-one, name-shape, ownership, and `.git`-absence checks) |
| `swe-workbench-reap-session-scratch` | Platform-neutral content-clear (directory preserved) for a verified current-session scratch target, authorized by exactly one packaged session scratch adapter; ambiguous or unsafe resolution is a zero-count no-op |
| `swe-workbench-session-scratch-adapter-claude` | Claude Code session scratch adapter |
| `swe-workbench-session-scratch-adapter-pi` | Pi Coding Agent session scratch adapter |
| `swe-workbench-reply-and-resolve` | Post a PR review thread reply (REST) and optionally resolve it (GraphQL) |
| `swe-workbench-result-check` | Validate a producer's JSON result envelope against a schema registry and pass it through unchanged (`swe-workbench-result-check <schema>`) — the standard consumption mechanism for the envelope contract, replacing `eval` for a migrated producer; see [Result contract](#result-contract) |
| `swe-workbench-skill-script` | Invoke a skill-local `scripts/<name>.sh` helper (`swe-workbench-skill-script <skill> <script> [args...]`) — rejects traversal, resolves the plugin root itself so no skill has to |
| `swe-workbench-sweep-residuals` | PR-scoped residual-artifact backstop for `swe-workbench:workflow-cleanup-merged` Step 5 — force-removes leftover worktrees, state files, run dirs, and session-scratch entries for a merged PR number; emits one JSON envelope (schema `swb.sweep-residuals/1`) with retained/failed worktrees as `[{path, reason}]`, not just a count |
| `swe-workbench-sync-pr-metadata` | Apply a revised title and/or body to an existing PR (address-feedback Phase 6 drift sync) |

`swe-workbench-address-feedback-fetch`, `swe-workbench-comment-scan`, `swe-workbench-lsp`,
`swe-workbench-pr-review-submit`, `swe-workbench-preflight-commit`, and `swe-workbench-result-check`
are the six scripts in this directory with a `#!/usr/bin/env python3` shebang instead of
`#!/usr/bin/env bash`. `comment-scan`
is a pure diff-in/findings-out function (no git calls of its own; see
`shared/agents/comment-scan.md` for the canonical diff command); `pr-review-submit` does call
`git`/`gh` but needed Python's JSON and multi-call state-machine handling (422 retry,
read-your-write confirmation) more than bash's process-spawning idioms; `lsp` speaks JSON-RPC
framing to a spawned language server subprocess, which needs a real threaded reader loop bash
can't give it; `preflight-commit` classifies NUL-delimited raw staged paths and emits JSON — bash
would need `jq` for escaping arbitrary path bytes and a second regex dialect (Oniguruma) for
matching, a second engine to audit in a security gate that should have exactly one;
`result-check` needs the same JSON-object type/shape validation `preflight-commit` does, for the
same reason; `address-feedback-fetch` needed the same paginated-cursor state machine as
`pr-review-submit` (a `reviewThreads(first:100, after:$after)` / `pageInfo{endCursor hasNextPage}`
loop) plus JSON emission over arbitrary-byte review-comment text, where bash would again mean a
second escaping engine (`jq`) layered under the same shell process-spawning idioms `pr-review-submit`
already rejected for the identical reason. Unlike `comment-scan` (advisory, correctly fails open), `preflight-commit`,
`result-check`, and `address-feedback-fetch` fail closed: an error is a hard non-zero exit with
nothing on stdout, never a silent "clean". Same bare-command convention applies; only the
interpreter differs.

## Result contract

A script whose result has real structure to lose — a list of records, per-item failure detail, or
genuine partial-success semantics — emits one JSON envelope on stdout instead of `KEY=VALUE` lines
for `eval`:

```json
{
  "schema": "swb.<command>/<major>",
  "status": "ok" | "partial" | "failed",
  "data": { "...": "command-specific typed fields" },
  "warnings": [ { "code": "...", "message": "...", "subject": "optional" } ]
}
```

A consuming skill pipes it through `swe-workbench-result-check <schema>` in place of `eval`:

```bash
RESULT=$(swe-workbench-sweep-residuals "$PR" | swe-workbench-result-check swb.sweep-residuals/1) || exit 1
```

This is **not** a mandate for every script — a producer whose output is a handful of trusted
scalars (`swe-workbench-preflight-pr`'s 6 `printf %q`-quoted fields, `swe-workbench-new-run-dir`'s
bare path) has nothing to gain from it and stays exactly as it is. See
[`shared/docs/runtime-result-contract.md`](../shared/docs/runtime-result-contract.md) for the full
spec: the envelope shape, the exact-match versioning rule, the S/Q/J decision test for whether a
given script should migrate, and the two-tier field-handling recipe for a consuming `SKILL.md`.

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
every skill-local `scripts/*.sh` helper is assumed to be bash. A `bin/` script itself reaches a
skill-local helper the same way — `swe-workbench-sweep-residuals` resolves
`swe-workbench:workflow-cleanup-merged`'s `resolve-rimba.sh` via `"$SCRIPT_DIR/swe-workbench-skill-script"
workflow-cleanup-merged resolve-rimba.sh`, since that helper has another consumer inside the skill
itself and stays skill-local rather than being promoted alongside its caller.
