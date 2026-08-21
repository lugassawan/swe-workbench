# Plugin platform decisions

Rulings made while migrating skills, commands, and agents to invoke plugin scripts as bare PATH
commands instead of resolving them through `$CLAUDE_PLUGIN_ROOT`, and while collapsing the
resulting `runtime/`/`bin/` wrapper split back into a single `bin/` directory and retiring the
`CLAUDE_PLUGIN_ROOT` injector hook. Recorded here so they don't have to be re-litigated.

## 1. `${CLAUDE_PLUGIN_DATA}` — considered, not adopted

Some plugin runtimes expose a `CLAUDE_PLUGIN_DATA` directory for a plugin's own persistent
state. swe-workbench's workflow-state feature doesn't use it.

State lives at `<git-toplevel>/.claude/cache/workflow-state/<branch>.json` (see
`docs/workflow-state.md`) — per-repo and per-branch by construction, because the path is
derived from `git rev-parse --show-toplevel` and the current branch name. `CLAUDE_PLUGIN_DATA`
is global-per-plugin: adopting it would require hashing the repo path (and branch) into the
filename to avoid collisions across repos and branches — added complexity for no win over the
git-toplevel-relative path already in use.

## 2. No `claude plugin validate` in CI, and no frontmatter allowlist validator

CI's `scripts/validate.py` gate is deliberately **open-world**: `check_agents()` and friends
assert *positive, closed-form* invariants this repo owns and controls (frontmatter fields
present, references resolve, line caps respected) rather than validating against an external
schema.

Two things were considered and rejected for the same reason:

- **Running `claude plugin validate` (or equivalent) in CI** — this validates against a schema
  the CLI ships, not one this repo version-controls. An upstream schema change would turn any
  unrelated PR into a red build, with no maintainer able to fix it locally (the fix lives in a
  different repository entirely).
- **A frontmatter-key allowlist validator** — same failure mode: a new frontmatter key the
  platform adds would fail closed-world validation here until this repo's allowlist catches up,
  even though the key is valid and harmless.

Prefer assertions the repo can always satisfy by editing its own files.

**Sanctioned open-world alternative:** when a coupling genuinely needs a closed-form contract
(e.g. the Pi frontmatter boundary), express it as a golden inventory ratchet — a
module-level dict/set literal asserted equal to what's on disk — not a schema. It fails only
when *this repo* writes a new value into a file, never on an upstream addition it hasn't
adopted yet. `tests/test_agent_model_tiers.py` is the reference implementation;
`tests/test_pi_contract.py`'s `FRONTMATTER_KEYS`/`TOOL_TOKENS`/`SKILL_IDS` follow the same
shape.

## 3. Dev-loop caveat: `bin/` changes cannot be dogfooded in-repo

`<plugin>/bin` is appended to the Bash tool's `PATH` for the **installed plugin cache**
(`…/cache/swe-workbench/swe-workbench/<version>/bin`), not for a local dev checkout. This has
two consequences:

- A bare `swe-workbench-*` command typed inside this repo's own working tree resolves to the
  **released** wrapper, not the one just edited in the checkout. Testing a `bin/` change
  requires invoking the wrapper by path (`bash bin/swe-workbench-doctor`) or reinstalling the
  plugin from the branch under test — bare-command invocation alone will not pick up local
  edits.
- Plugin `bin/` directories are appended to the **end** of `PATH` (after `/usr/bin`, Homebrew,
  etc.), not prepended. A wrapper without the `swe-workbench-` prefix would therefore be
  *shadowed by* a same-named binary already on the user's PATH, not the other way around. The
  prefix requirement stands regardless of this ordering — PATH placement is not something this
  repo controls or should rely on — but it's worth recording that the shadowing direction is the
  opposite of what might be assumed.

## 4. Hook `if` conditions — considered, not adopted

`.claude-plugin/schemas/plugin.schema.json` defines the command-hook object as `{type, command,
if, shell, timeout, statusMessage, once, async, asyncRewake}`. `if` is documented as *"Permission
rule syntax to filter when this hook runs (e.g. `Bash(git *)`). Only runs if the tool call matches
the pattern."* — it filters a tool-call payload against a pattern; it is not a general-purpose
guard.

Applied to every entry in `hooks/hooks.json`, no `if` buys anything:

| Hook | Event | Why `if` buys nothing |
|---|---|---|
| `bash_guard.sh` | `PreToolUse` / `Bash` | `Bash(*)` is exactly redundant with `matcher` |
| `skill_usage_record.sh` | `PreToolUse` / `Skill` | `Skill(*)` is exactly redundant with `matcher` |
| `worktree_permission_grant.sh` | `PreToolUse` / `Read\|Edit\|Write` | Worktree root is runtime-resolved, not a static path rule |
| `secret_guard.py` | `PreToolUse` / `Write\|Edit` | Same as `worktree_permission_grant.sh` — no static pattern captures "contains a credential" |
| `skill_autoload_hint.sh` | `PostToolUse` / `Read\|Edit\|Write` | Would need every extension enumerated; a miss silently loses the hint |
| `skill_usage_flush.sh` | `SubagentStop` | No tool call to match against — inert at best, disabling at worst |
| `workflow_resume_hint.sh` ×3 | `SessionStart` | Same — lifecycle events carry no tool call |

**Ruling: no `hooks.json` entry may carry an `if` key**, enforced by
`scripts/validate.py:check_hooks_json()`. This is strictly stronger than the two security
controls (`bash_guard.sh`, `secret_guard.py`) that originally motivated the question — every entry
in the table above hits the same failure mode: `if` is one more predicate that can silently
disable a hook (a miss reads as "hook chose not to fire," not as an error) for zero filtering
benefit over what `matcher` already provides or what the script can check for itself at runtime.

## 5. `swe-workbench-skill-script` dispatcher replaces the doctor-anchor `_RT=` derivation

**(a) Why the doctor-anchor derivation was replaced.** Once `runtime/` collapsed into `bin/` and
the `CLAUDE_PLUGIN_ROOT` injector hook was retired, skills with their own `scripts/` helpers
(`swe-workbench:workflow-cleanup-merged`, `swe-workbench:workflow-branch-sync`) still needed to resolve a skill-local path, so
a stand-in root derivation —
`_RT="$(cd "$(dirname "$(command -v swe-workbench-doctor)")/.." && pwd)"` — was introduced at every
call site. That traded one copy-pasted preamble for another: 10 occurrences across 2 files, and
still path construction living in skill prose rather than in a script — the same shape of
duplication `bin/README.md`'s "Reference pattern" exists to prevent for every other `bin/` script.
`bin/swe-workbench-skill-script <skill> <script> [args...]` owns that resolution once, as a
dispatcher: skill prose invokes it as a bare command, with no `_RT`/`_SCRIPTS` variables anywhere.

**(b) Why the `command -v swe-workbench-<name>` guard itself is not extractable.** A PATH-
availability guard cannot live inside a PATH-resolved helper. If `bin/` is off `PATH`, the helper
(dispatcher or otherwise) is unreachable too — the caller gets the shell's bare
`command not found` (exit 127) instead of the guard's actionable message ("reinstall or update the
swe-workbench plugin"). The guard has to run *before* anything that depends on `bin/` being on
`PATH`, which rules out delegating it to a script that is itself only reachable via `PATH`. It
stays exactly where it is today: one `command -v` line at the top of each skill's first executable
block, per `bin/README.md`'s "Reference pattern".

## 6. `worktree_permission_grant.sh` has no Pi equivalent — documented N/A, not deferred

`pi/extensions/guards.ts` reproduces `bash_guard.sh`, `secret_guard.py`,
`workflow_resume_hint.sh`, and `skill_autoload_hint.sh` on Pi, each exec'ing the unchanged
Claude Code script. `worktree_permission_grant.sh` is left out deliberately and permanently.

The hook emits `permissionDecision: "allow"` so Claude Code's permission-prompt system skips
asking about paths inside the active worktree. Pi's README states "No permission popups" — there
is no prompt surface for a `tool_call` handler to target, so a port would have nothing to grant
permission *for*.

Recorded as an explicit `"n/a"` row in `tests/test_pi_contract.py`'s `HOOK_PI_STATUS` inventory
— distinct from `"deferred"` (`skill_usage_record.sh`/`skill_usage_flush.sh`, unwired only until
`Skill`/subagents exist on Pi). `"n/a"` never graduates to `"wired"`.

## 7. `EnterWorktree`/`ExitWorktree` have no Pi equivalent — documented N/A, not deferred

The tool-vocabulary preamble (`pi/extensions/tool-vocab.ts`) maps every Claude Code tool name
this repo's prose uses to a Pi equivalent, except one: there is no Pi primitive that anchors a
session to a different working directory the way `EnterWorktree`/`ExitWorktree` do.

`dist/core/session-cwd.d.ts` only validates that a session's recorded cwd still exists on disk
(`getMissingSessionCwdIssue`, `assertSessionCwdExists`) — it never changes it.
`ExtensionContext.cwd` (`dist/core/extensions/types.d.ts`) is a plain read-only `string`; neither
`ExtensionContext` nor `ExtensionCommandContext` exposes a `setCwd`. There is nothing for a
worktree-anchoring tool to call.

A `cd`-shelling tool named `EnterWorktree` would be worse than none: `skills/workflow-worktree-session/SKILL.md`
teaches a specific cd-vs-`EnterWorktree` distinction — `cd` only anchors the Bash subprocess's
cwd, while `EnterWorktree` re-anchors session-level caches (plans dir, memory dir) that `cd`
cannot touch. A tool that shells out to `cd` under the `EnterWorktree` name would claim the
stronger guarantee while delivering only the weaker one, silently breaking that diagnostic for
every Pi session.

No prose edit and no new tool. `tool-vocab.ts`'s worktree note tells the model the `cd
<absolute-path>` fallback documented in `skills/workflow-worktree-session/SKILL.md` (lines 30 and
87 as of this writing) is *the* mechanism on Pi, not a last resort. Recorded as an explicit
`"n/a"`-shaped decision here — mirroring §6 — rather than left implicit.

## 8. `LSP` has no Pi tool registration — the capability lives in `bin/`, not the adapter

This phase's scope originally sketched `pi/extensions/lsp.ts`: a repo-marker → server-binary map,
PATH lookup, and a `vscode-jsonrpc` client exposing a Pi-registered `LSP` tool. That premise was
overtaken by a prior change that moved the whole capability out of the harness layer before this
phase started.

The harness-native `LSP` tool is main-loop-only on Claude Code 2.1.237 — absent from every
subagent's tool registry, even at the maximum grant a subagent can hold
(`docs/dependencies.md`'s "Language servers" section). None of the four consumers
(`swe-workbench:reviewer`, `swe-workbench:auditor`, `swe-workbench:debugger`,
`swe-workbench:refactorer`) grant `LSP` in their `tools:` frontmatter; all four grant `Bash`
instead (pinned by `tests/test_lsp_literacy.py`'s `test_agent_does_not_grant_native_lsp_tool`).
The real capability is `bin/swe-workbench-lsp`, a stdlib-only script that speaks LSP JSON-RPC to a
locally installed language server directly — reachable via `Bash` on any harness, with no
dependency on a harness-provided `LSP` tool ever being wired up.

Phase 1 already did the only port work this capability needs: `pi/extensions/index.ts`
appends `<root>/bin` to `process.env.PATH`, so `swe-workbench-lsp` is already a bare command in a
Pi session, and it splices `bin/README.md`'s `## Current scripts` body into the Tier-1 preamble,
so a Pi session is already told the capability exists. A Pi-registered `LSP` tool would fork the
886-line script plus `tests/test_lsp_script.py`'s suite into a second implementation, teach the
two harnesses different vocabularies for one capability — the opposite of what
`pi/extensions/tool-vocab.ts` exists to do — and gain zero callers, since the four consumers
already reach the capability through `Bash`.

Recorded as an explicit `"n/a"` decision — mirroring §6 and §7 — rather than left implicit.
Unlike §6, this is not a `HOOK_PI_STATUS` row: that inventory is keyed to `hooks/*.sh|py` and
asserted exhaustive against that directory; `swe-workbench-lsp` lives in `bin/`, so this section is
the record. `"n/a"` never graduates to `"wired"`.

## 9. `task` — a first-party subagent dispatcher, not a fork of `pi-subagents`

This plugin needed a way to dispatch any of its `agents/*.md` definitions (`swe-workbench:reviewer`,
etc.) as a nested Pi session, preserving each agent's declared `tools`, preloaded `skills:` content,
and (when declared) a model matched to its `model:` tier. `pi/extensions/subagent.ts` registers a
`task` tool that does exactly this, composing an agent's body plus its preloaded skills into a
system prompt and running it as a real child `pi -p` process via `pi.exec()`.

**swe-workbench does not own a general subagent runtime.** The `pi-subagents` package is the
supported route for generic delegation on Pi — chains, parallel fan-out, async runs, forked
context, resume/status. `task` is not a competitor to that package or a wrapper around it; it
exists for one narrower, structural reason: `pi-subagents`' `skills:` field only makes a skill
*available* to a dispatched agent (an XML manifest the agent can `read` on demand), it never
preloads a skill's body into the child's context — verified directly against that package's
published source (`src/agents/skills.ts`'s `buildSkillInjection`, used by every real dispatch path
in it). This repo's `agents/*.md` convention requires preload (`docs/skill-preload.md`) — every
one of the 22 agents carries a `skills:` block, several with a dozen or more entries a dispatched
agent is expected to already have in context on turn one, not fetch on demand. `pi-subagents`
being installed alongside `task` is expected and fine; the two solve different problems.

**Recursion guard: `--exclude-tools task,subagent` on the child's argv, not a depth env var.**
Verified against the installed SDK's `agent-session.js`: an excluded tool is never added to the
child's tool registry at construction time, so nothing running inside that child session can
resurrect it — an out-of-band, unforgeable control, unlike an env var the child's own `bash` tool
could unset. `subagent` (that package's own tool name) is excluded defensively alongside `task`
in case both are installed together. This was confirmed live, not just read from source: a
zero-model-call probe (a `session_start` handler calling `getActiveTools()` then `shutdown()`
before any prompt is sent, run through the real `pi` binary) showed a registered tool present in
the active set with no `--exclude-tools` and absent with it — see
`tests/test_pi_contract.py::test_exclude_tools_structurally_prevents_task_tool_activation`.

**`ask_user_question` is granted to every dispatched agent, deliberately, even though it always
fails.** Every child runs in `-p`/`--no-session` print mode, where `ctx.hasUI` is `false` — so a
call to `ask_user_question` always throws `"...requires an interactive UI..."`
(`pi/extensions/ask-user.ts`). Granting it anyway is intentional: the thrown message is the point.
It gives a dispatched agent a named way to signal "I hit a decision only a human can make" and get
a clear, actionable rejection back — steering it to stop and report the blocker in its final
response — instead of either silently guessing (no signal at all) or the tool being simply absent
from its vocabulary. Costs nothing beyond one line in the `--tools` allowlist.

**Accepted gap, not closed here — tracked as issue #632.** `--exclude-tools task,subagent` blocks
recursion only through the `task`/`subagent` tool-call surface. An agent granted `Bash` (20 of the
22 `agents/*.md` definitions — the large majority of real dispatches, not an edge case) can still
shell out to `pi -p ...` directly inside a dispatched child, which spawns a fresh child session
with `task` re-registered and no `--exclude-tools` at all — no argv flag on that child prevents a
further, unbounded level of recursion this way. Closing it belongs in `hooks/bash_guard.sh`,
pattern-matching a `pi ... -p`/`--print` invocation, since that reuses an already-audited boundary
instead of adding a new one. Not built as part of this dispatcher — see #632 for the concrete
tracked follow-up.

**Model-tier mapping: an agent's `model: haiku|sonnet|opus` frontmatter picks a real model, by
name, from a table hardcoded in `pi/extensions/model-tier.ts`.** An earlier iteration of this
decision cut model-tier mapping entirely, on the grounds that a project-committed `.pi/settings.json`
reading a `modelTiers` block would be a real exfiltration primitive — redirecting subagent traffic
to an attacker-chosen provider/endpoint via a config surface outside normal code review. That
concern is real, but it is a property of *where the mapping lives and what it can point at*, not
of model-tier mapping itself, and the actual implementation avoids it entirely:

- The table (`MODEL_TIER_TABLE`) is code shipped in this plugin's own reviewed source tree
  (`pi/extensions/`) — the same trust boundary as every guard script path and tool-token mapping
  already hardcoded elsewhere in this file group, not an independently-editable runtime settings
  file.
- Resolution is scoped to `ctx.model.provider` — whichever provider the parent session is already
  on — and only ever selects among `ctx.scopedModels` (when the session is scoped via
  `--models`/`enabledModels`) or, when unscoped, `ctx.modelRegistry.getAvailable()` results
  (models the user has already configured credentials for). It never introduces a new provider,
  baseUrl, or apiKey; a stale or missing table entry degrades to the parent's own current model
  unchanged, never to something else.
- Matching is by substring against `Model.id` (e.g. `"opus"` matches `claude-opus-5`, `"sol"`
  matches `gpt-5.6-sol`), not exact-version pinning, so a provider's routine model-id version bumps
  don't silently break the mapping. Substring matching alone is ambiguous, though: the bundled
  Anthropic catalog carries dated/versioned siblings of a bare flagship id (`claude-opus-4-5`,
  `claude-opus-4-5-20251101`, `claude-opus-4-6`... alongside `claude-opus-5`, all containing
  `"opus"`), in catalog order rather than recency order — a plain first-match would silently
  resolve to a stale snapshot. Resolution picks the *shortest* matching id instead: a
  dated/versioned sibling is always the bare id plus extra suffix characters, so it can never be
  shorter, making this a reliable, provider-catalog-agnostic tiebreak rather than a
  version-pinning hack. `tests/test_pi_extension.py`'s anthropic fixture reproduces the real
  bundled catalog's ambiguity verbatim to lock this in.

`tests/test_pi_contract.py::test_model_tiers_are_inventoried` and
`test_model_tier_table_is_exhaustive_over_known_tiers` ratchet the tier vocabulary and each
provider row against the live `agents/*.md` inventory, the same pattern §2 already uses for tool
tokens and skill ids.

**Preloaded skills state their own resolvable directory.** A skill's body sometimes points at its
own `examples/` subdirectory ("see `examples/` for a worked implementation..." —
`swe-workbench:principle-solid`, `swe-workbench:principle-ddd`, etc.) without stating a path a
reader could actually resolve. `composeSystemPrompt` now prepends each preloaded skill's absolute
on-disk directory to its section header — not inlining `examples/` content (that stays on-demand,
fetched by the dispatched agent's own `read` tool if it decides the pointer is relevant), just
making the pointer resolvable instead of dead.
