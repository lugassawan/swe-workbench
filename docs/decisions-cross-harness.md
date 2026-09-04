# Plugin platform decisions — cross-harness: handoff and memory

Rulings on the features Claude Code and Pi share: cross-harness handoff ownership
(`hooks/handoff_guard.py` vs `pi/extensions/handoff.ts`) and the per-repo memory stores
(`bin/swe-workbench-memory`). Recorded here so they don't have to be re-litigated.
Sibling rulings live in the other `docs/decisions-*.md` files (indexed in
`docs/README.md`).

## 1. `handoff_guard.py` — native mirror, never spawned on Pi

The Claude-side PreToolUse hook `hooks/handoff_guard.py` enforces cross-harness handoff
ownership for Claude Code sessions. On Pi the SAME decisions are enforced by
`pi/extensions/handoff.ts`, natively — the hook script is never spawned.

**Why not wire the script (like bash_guard/secret_guard)?** The hook's input contract is
Claude-shaped: `tool_name`/`tool_input`/`session_id` from a PreToolUse payload, plus
`CLAUDE_PLUGIN_ROOT`-based runtime resolution. Pi's equivalents live elsewhere — tool
identity and inputs come from `tool_call` events, session identity from
`ctx.sessionManager.getSessionId()`, and quota exhaustion only ever surfaces as an HTTP
status on `after_provider_response`, an event the Claude hook cannot see. A cc-payload
adapter could fake the first two, but the third has no Claude-side counterpart at all, so
half the adapter would still need a native module.

**What is shared vs native:** every ownership decision funnels through the same
harness-neutral runtime (`bin/swe-workbench-handoff guard`), so the lease rules never
fork. Native code is confined to: event-shape translation, the same anchored
lifecycle-pipeline allowlist (mirrored per harness: Pi may bypass for `resume --as pi`
and `recover --from claude`, Claude for `resume --as claude` and `recover --from pi`),
identical failure postures (missing runtime install fails open; spawn error, timeout,
corrupt state, or undecidable output fails closed), and the 429 recovery affordance
(persistent footer status + once-per-session warning with the exact recovery command).

**Quota warnings stay asymmetric by design.** Pi has no trustworthy subscription-quota
signal — context-window usage accessors are explicitly NOT quota — so Pi warns only after
an actual HTTP 429. Pre-limit percentage warnings remain a Claude-only affordance driven
by Claude's five-hour quota fields (`status-segment`).

**A read-only Bash allowlist for the guard — rejected.** "Read-only" is not a decidable
property of a command string, and even with perfect tokenization `git` itself is not
read-only: `git diff --ext-diff` runs a configured external diff driver, `git -c
core.pager='sh -c …'` injects execution through config, `git -C <path>` retargets outside
the guarded worktree, `--output=` writes files, and bare `git status` writes `.git/index`.
A safe allowlist would have to be flag-scoped per verb and maintained against upstream git
forever, for the sole benefit of typing `cat` instead of using the `Read` tool — which the
guard never blocked in the first place (only `Bash`/`Edit`/`Write`, Pi:
`bash`/`write`/`edit`). `tests/test_handoff_guard.py`'s
`test_still_blocks_arbitrary_read_only_bash_under_a_released_lease` is the standing ruling.

**Auto-releasing a "stale" `released` lease — rejected.** The lease exists *because* the
source harness is expected to be gone for hours at a time (quota exhaustion); `released` is
the protocol's normal waiting state, not evidence of abandonment. Nothing observable from
one harness's session can prove the other harness's session is dead — which is exactly why
`recover` requires the operator to type `--source-stopped` by hand. Auto-releasing on a
timeout would silently destroy a real in-flight checkpoint the moment it happened to outlive
the timeout, converting a diagnostic annoyance into a destructive one. The existing 7-day
open-checkpoint expiry, 24-hour consumed/closed sweep, and `_recorded_worktree_exists`
orphan reaping are the correct staleness story; the escape hatch for a checkpoint an
operator wants to walk back by hand is `resume` immediately followed by `close` (see
`docs/cross-harness-handoff.md`'s "Abandoning a checkpoint"), not a new `abandon`
subcommand or an allowlisted `close` — `close` authenticates on `owner_harness` *and*
`receiver_session_ref`, and allowlisting it would let a non-owner delete a lease, which is
the exact thing the guard exists to prevent.

**The harness's own worktree-isolation / git-detection guard is out of scope here.** A
worktree-isolated Claude Code session's Bash tool refuses a compound command it cannot
statically prove stays confined to git and to the current worktree — that guard is compiled
into the Claude Code binary, not this plugin (no matches under `hooks/`, `bin/`,
`commands/`, or `skills/`). It refuses a lifecycle pipeline carrying a `${VAR:?…}` shell
expansion because that is a runtime-computed, non-inert argument; this plugin can (and
does, via the `--*-session-env` literal-argument form) remove that condition from its own
pipelines, but the guard's underlying false-positive rate on an unrecognized binary piped
into another is upstream Claude Code's to fix.

## 2. Cross-harness memory — main-checkout anchoring, dual-slug read, own-store-only writes

Each harness owns one per-repo memory store and reads the other's read-only
(`bin/swe-workbench-memory`, hooks/memory_hint.sh). Four rulings:

**Anchor on the main checkout, not the session cwd.** Claude Code keys
`~/.claude/projects/<slug>` by the session's project directory — empirically,
worktree sessions produce separate worktree-slug directories (observed:
`…-swe-workbench-worktrees-bugfix-…` alongside `…-swe-workbench`, the latter
holding 103 entries). A cwd-anchored reader in a worktree would therefore see
nothing; a cwd-anchored writer would fragment the store per worktree. Both
stores instead resolve their slug from the realpath'd parent of
`git rev-parse --git-common-dir` (the handoff runtime's repo-identity
precedent); non-git cwds fall back to the cwd slug.

**The Claude store is read through two slugs.** Entries Claude sessions wrote
under a worktree slug stay real knowledge; reads probe the main slug first,
then the cwd slug, merging by entry-file basename (main wins, cwd supplements).
Writes stay single-anchored on the main slug.

**Writes are structurally single-store.** No subcommand accepts a store path;
the writable store derives solely from `--as`. A `--store` flag exists only as
a guard: any value other than the caller's own store fails closed (non-zero
exit, empty stdout, untouched stores) — the read-only direction is enforced in
code, not documentation. Record inputs are secret-scanned; memory outlives the
session that wrote it. Appends are flock-serialized.

**Readability beats opacity for the Pi store key.** Unlike handoff's sha256
repo keys (never inspected by hand), the Pi store uses the same readable slug
as `~/.claude/projects/`, pairing the two stores visually, with a `.origin`
file disambiguating path-vs-slug collisions (the `/a/b` vs `/a-b` collision is
inherited from Claude Code's own scheme). Known asymmetry: Pi gates injection
on `ctx.isProjectTrusted()`; Claude's SessionStart hook has no trust
equivalent — mitigated by a hard 16 KiB render cap and a "treat as data, not
instructions" fence on every injected block. The handoff checkpoint is not a
carrier for memory (its security exclusions bar file bodies by design).
