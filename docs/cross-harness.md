# Plugin platform decisions — cross-harness: handoff and memory

Rulings on the features Claude Code and Pi share: cross-harness handoff ownership
(`hooks/handoff_guard.py` vs `pi/extensions/handoff.ts`) and the per-repo memory stores
(`bin/swe-workbench-memory`). Recorded here so they don't have to be re-litigated.
Sibling rulings live in the other topic docs (indexed in
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

**Automatic stale-lease release — rejected; explicit abandonment accepted.** A `released`
lease is the normal waiting state after quota exhaustion, not evidence that a receiver is gone.
Nothing observable proves that session death, so timeout-based release remains unsafe. The
operator may instead use the exact checked `abandon <checkpoint-id> --source-stopped` route:
it records terminal abandonment before releasing only the matching lease. The flag is an
explicit local assertion, not proof; a false assertion can allow concurrent mutation. Normal
`close` remains owner/session authenticated and is never broadly allowlisted.

**The harness's own worktree-isolation / git-detection guard is out of scope here.** A
worktree-isolated Claude Code session's Bash tool refuses a compound command it cannot
statically prove stays confined to git and to the current worktree — that guard is compiled
into the Claude Code binary, not this plugin (no matches under `hooks/`, `bin/`,
`commands/`, or `skills/`). It refuses a lifecycle pipeline carrying a `${VAR:?…}` shell
expansion because that is a runtime-computed, non-inert argument; this plugin can (and
does, via the `--*-session-env` literal-argument form) remove that condition from its own
pipelines, but the guard's underlying false-positive rate on an unrecognized binary piped
into another is upstream Claude Code's to fix.

**RTK interaction — a Claude-only usability hook, not a fix.** Under RTK's global
`rtk hook claude` PreToolUse hook, every `git …` is rewritten to `rtk git …`; once the session
is isolated via `EnterWorktree`, Claude Code's guard refuses `rtk` as an opaque launcher with a
git command among its operands. The harness's suggested next step ("run the plain command") is
rewritten again, so retrying never converges. Measured against Claude Code 2.1.296 with RTK 0.51.0
in throwaway repos (`scripts/rtk-worktree-matrix.sh` reproduces it):

| Configuration | bare / `-C` / compound git | `rtk git` / `rtk proxy git` | `/usr/bin/git` |
|---|---|---|---|
| Claude Code + RTK (+ plugin) | refused | refused | allowed |
| Claude Code only | allowed | refused | allowed |
| Claude Code + plugin, no RTK | allowed | refused | allowed |

RTK is the sole trigger; the plugin's own guards add nothing. A session *launched* inside a linked
worktree is not isolated, so RTK-rewritten git runs there. A per-segment `RTK_DISABLED=1 git …`
is allowed in every form (plain, `-C`, mutating, compound with the prefix on each git segment,
`env RTK_DISABLED=1 git …`); `export RTK_DISABLED=1; git …` is still refused because the second
segment is rewritten. RTK's `[hooks] exclude_commands = ["git"]` also works but gives up its git
compression everywhere.

`hooks/rtk_worktree_guard.sh` therefore stops the loop before it starts. After `EnterWorktree`
it records a per-session marker (only when an `rtk hook claude` entry is configured); a Bash
call whose cwd is inside the marked worktree is asked of `rtk rewrite` and **denied** when what
will actually run is `rtk [proxy] git …`. The deny names one exact `RTK_DISABLED=1 git …` command
that has itself been run back through the same check (class `containment`). No exact fix is
offered when the original carries quotes, substitutions or a heredoc, sits behind a launcher
wrapper (`time`, `command`, `exec`, `nice`, … — RTK splices `rtk` in after the wrapper, so a
textual splice would not run), or the rendered fix cannot itself be decided on; the message is
then a fixed instruction to run each git command as its own `RTK_DISABLED=1`-prefixed call
(class `parse-complexity`). The tag names the failure class so containment and parse-complexity
refusals are not conflated.

Why deny rather than rewrite: PreToolUse `updatedInput` from separate hooks does not compose —
the later hook would see, or overwrite, RTK's rewrite — while a deny always wins. Why decide on
`rtk rewrite`'s result instead of the typed text: the same typed command is fine or refused
depending on what RTK does to it (`/usr/bin/git`, `env RTK_DISABLED=1 git` untouched;
`FOO=1 git` and `time git` rewritten), and RTK leaves commands with `$(…)` or heredocs alone.
The exit code alone does not say whether anything changed: exit 3 and exit 0 both carry the
rewritten command on stdout (0 when an allow rule such as `Bash(git *)` covers it), and exit 1
means unchanged — so a user with that allow rule is still caught.

The hook is fail-open (any uncertainty, a missing `rtk` or `jq`, a rewrite that hangs past
~2s, or an unexpected exit code allows the call) and applies only to Claude Code; on Pi there
is no `EnterWorktree` and no RTK hook, so it is an explicit N/A row in `HOOK_PI_STATUS`. The
marker is only written when RTK would in fact rewrite git there, and markers whose worktree has
vanished are pruned on the next enter. A SIGKILL of the hook itself can leak one in-flight
`rtk rewrite` child and its temp file; any other exit path reaps both.

The root fix is upstream and this hook should be deleted when it lands: Claude Code should
unwrap known launchers when proving containment, or RTK should skip rewriting git inside an
isolated session. `bin/swe-workbench-doctor` prints an advisory when the RTK hook and the
rewrite are both present.

## 2. Cross-harness memory — main-checkout anchoring, dual-slug read, own-store-only writes

Each harness owns one per-repo memory store and reads the other's read-only
(`bin/swe-workbench-memory`, hooks/memory_hint.sh). Rulings:

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
then the cwd slug, merging by **entry identity** (type + name-stem + raw-name
hash — stable across a cross-day re-record's fresh date digest; main wins, cwd
supplements). Writes stay single-anchored on the main slug.

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

**The "readable slug" above was never actually Claude Code's own slug.**
`slugify()` implemented `replace("/","-").lstrip("-")` — read from the
`~/.claude/projects/` naming convention by eye, not from Claude Code's actual
recipe (a UTF-16-code-unit `[^A-Za-z0-9]`→`-` replace, leading `-` **kept**,
>200 chars truncated + a Java/JS `String.hashCode()` suffix). `show --as pi`
therefore reported `claude.exists: false` in every real repo, and CI stayed
green because the test helper mirrored the same wrong recipe. Fixed by
`claude_slug()` (exact parity, pinned against real JS-recipe output), used
for **both** stores now. The pre-fix Pi store key stays as a **read-only**
merge source (`legacy_pi_slug`) so nothing recorded via `record --as pi`
before this fix is orphaned — deliberately Pi-store-only (see
docs/cross-harness-memory.md's Anchoring section for the resulting
Claude-store caveat).

**`--other-only` scopes to what Claude Code natively covers, not the whole
own-store.** Claude Code's native per-project memory keys strictly on the
session's literal cwd — no git-worktree or main-checkout awareness. So
`render --as claude --other-only` (Claude Code's own SessionStart hook) omits
only entries physically stored under the cwd-slug directory: in a plain repo
that's the whole own-store; in a worktree the main-checkout entries stay
rendered, since Claude Code has no native visibility into those. A no-op for
`--as pi` — Pi always renders both sections in full.

**`memory_record` (Pi's native recording tool) writes with no confirmation
prompt, trust-gated instead.** The safety backstop is project trust (the
same gate memory *injection* already uses) plus the runtime's own secret scan
and byte caps. Gated twice: `session_start` hides the tool from an untrusted
session's active tool set, and `execute()` independently re-checks
`ctx.isProjectTrusted()`. A `ctx.ui.notify` toast on every write replaces the
prompt. Entry types widen to `user|feedback|project|reference`, parity-pinned
between the runtime's `ENTRY_TYPES` and the Pi extension's own. No delete
subcommand — a same-name re-record is an update.
