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

Every script documents itself: run `swe-workbench-<name> --help` for usage, arguments, and
behavior — there is no separate script-by-script table here to keep in sync with the code as
scripts change. The scripts in this directory that carry a `#!/usr/bin/env python3`
shebang instead of `#!/usr/bin/env bash` are `swe-workbench-address-feedback-fetch`,
`swe-workbench-comment-scan`, `swe-workbench-handoff`, `swe-workbench-lsp`,
`swe-workbench-memory`, `swe-workbench-pr-review-submit`, `swe-workbench-preflight-commit`,
and `swe-workbench-result-check`. `comment-scan` is a pure diff-in/findings-out function
(no git calls of its own; see `shared/agents/comment-scan.md` for the canonical diff command);
`pr-review-submit` does call `git`/`gh` but needed Python's JSON and multi-call state-machine
handling (422 retry, read-your-write confirmation) more than bash's process-spawning idioms; `lsp`
speaks JSON-RPC framing to a spawned language server subprocess, which needs a real threaded
reader loop bash can't give it; `preflight-commit` classifies NUL-delimited raw staged paths and
emits JSON — bash would need `jq` for escaping arbitrary path bytes and a second regex dialect
(Oniguruma) for matching, a second engine to audit in a security gate that should have exactly
one; `result-check` needs the same JSON-object type/shape validation `preflight-commit` does, for
the same reason; `address-feedback-fetch` needed the same paginated-cursor state machine as
`pr-review-submit` (a `reviewThreads(first:100, after:$after)` / `pageInfo{endCursor hasNextPage}`
loop) plus JSON emission over arbitrary-byte review-comment text, where bash would again mean a
second escaping engine (`jq`) layered under the same shell process-spawning idioms `pr-review-submit`
already rejected for the identical reason. `memory` resolves both harnesses' store paths,
scans record input for secrets, and flock-serializes concurrent appends — that dual-store path
resolution, JSON envelope emission, secret scan, and lock handling need Python's
`json`/`re`/`fcntl`, where bash would need `jq` as a second escaping engine. Unlike `comment-scan`
(advisory, correctly fails open),
`preflight-commit`, `result-check`, and `address-feedback-fetch` fail closed: an error is a hard
non-zero exit with nothing on stdout, never a silent "clean". Same bare-command convention
applies; only the interpreter differs.

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
