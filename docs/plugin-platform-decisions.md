# Plugin platform decisions

Rulings made while migrating skills, commands, and agents to invoke plugin scripts as bare PATH
commands instead of resolving them through `$CLAUDE_PLUGIN_ROOT`, while collapsing the resulting
`runtime/`/`bin/` wrapper split back into a single `bin/` directory and retiring the
`CLAUDE_PLUGIN_ROOT` injector hook, and while porting the plugin to run on the Pi Coding Agent
(§6 onward) — a runtime adapter (`pi/extensions/`) that loads this plugin's existing `skills/`,
`commands/`, and `agents/` trees unchanged. Recorded here so they don't have to be re-litigated.

## 1. `${CLAUDE_PLUGIN_DATA}` — considered, not adopted

Some plugin runtimes expose a `CLAUDE_PLUGIN_DATA` directory for a plugin's own persistent
state. swe-workbench's workflow-state feature doesn't use it.

State lives at `<git-toplevel>/.claude/cache/workflow-state/<branch>.json` (see
`shared/docs/workflow-state.md`) — per-repo and per-branch by construction, because the path is
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
— as are `skill_usage_record.sh`/`skill_usage_flush.sh` (§10 records why their concept, runtime
Skill invocation by a dispatched subagent, has no Pi counterpart either). `"n/a"` never
graduates to `"wired"`.

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
Pi session, and `pi/extensions/bin-scripts.ts` generates a bare-id inventory of `bin/` (plus a
one-entry capability row naming `swe-workbench-lsp`'s subcommands) into the Tier-1 preamble, so a
Pi session is already told the capability exists. A Pi-registered `LSP` tool would fork the
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

**Bash-escape-hatch recursion gap: closed via `hooks/bash_guard.sh`, not this dispatcher.**
`--exclude-tools task,subagent` blocks recursion only through the `task`/`subagent` tool-call
surface. An agent granted `Bash` (20 of the 22 `agents/*.md` definitions — the large majority of
real dispatches, not an edge case) could still shell out to `pi -p ...` directly inside a dispatched
child, which spawns a fresh child session with `task` re-registered and no `--exclude-tools` at
all — no argv flag on that child prevented a further, unbounded level of recursion this way.
Closed in `hooks/bash_guard.sh`, which now blocks a segment-scoped `pi ... -p`/`--print` invocation
(one command segment must carry both a `pi` command token and a `-p`/`--print` flag, so everyday
commands like `git log -p && pi list` stay allowed) — reusing this already-audited boundary instead
of adding a new one, since every dispatched agent's `bash` tool call already routes through it
(`pi/extensions/guards.ts` registers it as a Pi `tool_call` guard unconditionally, and
`hooks/hooks.json` wires the same script as `PreToolUse:Bash` in Claude Code). `pi.exec()` inside
this dispatcher is unaffected — it is not a `bash` tool call, so the real dispatch path never
touches this guard. Non-recursive `pi` subcommands (`pi --version`, `pi list`, `pi auth check`)
stay allowed.

**Model-dispatch policy: an agent's `model: haiku|sonnet|opus` tier plus its `effort:
low|medium|high|xhigh|max` frontmatter resolve to an exact model id and effective thinking level,
from a table hardcoded in `pi/extensions/model-policy.ts`.** An earlier iteration of this decision
cut model-tier mapping entirely, on the grounds that a project-committed `.pi/settings.json`
reading a `modelTiers` block would be a real exfiltration primitive — redirecting subagent traffic
to an attacker-chosen provider/endpoint via a config surface outside normal code review. That
concern is real, but it is a property of *where the mapping lives and what it can point at*, not
of model-dispatch mapping itself, and the actual implementation avoids it entirely:

- The table (`MODEL_POLICY`) is code shipped in this plugin's own reviewed source tree
  (`pi/extensions/`) — the same trust boundary as every guard script path and tool-token mapping
  already hardcoded elsewhere in this file group, not an independently-editable runtime settings
  file. There is no runtime, user-global, or project-local override surface for it.
- Resolution is scoped to `ctx.model.provider` — whichever provider the parent session is already
  on — and only ever selects among `ctx.scopedModels` (when the session is scoped via
  `--models`/`enabledModels`) or, when unscoped, `ctx.modelRegistry.getAvailable()` results
  (models the user has already configured credentials for). It never introduces a new provider,
  baseUrl, or apiKey; a stale or missing table entry, or a tier/effort the table has no row for,
  degrades to the parent's own current model and thinking level unchanged, never to something
  else.
- Matching is **exact id equality** against the candidate pool, not a substring or shortest-match
  heuristic. An earlier version of this design matched by substring against `Model.id` (e.g.
  `"opus"` matches `claude-opus-5`) to survive routine model-id version bumps without an edit here
  — but substring matching alone is ambiguous: the bundled Anthropic catalog carries dated/versioned
  siblings of a bare flagship id (`claude-opus-4-5`, `claude-opus-4-5-20251101`, `claude-opus-4-6`...
  alongside `claude-opus-5`, all containing `"opus"`), in catalog order rather than recency order,
  so a plain first-match would silently resolve to a stale snapshot. A shortest-match tiebreak
  patched that specific ambiguity, but it was still a heuristic riding on the assumption that the
  intended id is always the shortest match — a catalog reshuffle, a new sibling id, or a provider
  shipping a shorter-named model could silently re-point a tier at the wrong model, with no
  signal. Exact id equality removes the heuristic entirely: `MODEL_POLICY` names precisely which id
  each (provider, tier) cell resolves to, and a name no longer present in the candidate pool is a
  `model-unavailable` fallback — loud (a structured reason, a UI warning when available, and a
  `[swe-workbench] …` line in the tool result content even headless) rather than a silent
  wrong-model resolution. This strengthens the trust boundary above rather than weakening it: the
  set of models `task` can ever dispatch to is now a fixed, reviewable list of exact ids, not
  whatever a substring happens to match in the parent's authenticated catalog at run time.
- Reasoning depth is resolved the same way, not left to the parent session's own `--thinking`
  setting: each (provider, tier) cell also carries an exhaustive portable-effort ->
  effective-thinking-level map. For `anthropic` and `openai-codex` this is the identity (portable
  effort passes straight through); for `zai`, `glm-5.3` serves both the `opus` and `sonnet` tier,
  so the map shifts effort toward `max` for `opus` and toward `low` for `sonnet`, clamped at each
  end, to keep the two tiers distinguishable on the one axis left once the model id itself can't
  disambiguate them. See `docs/cost-tiers.md`'s "On the Pi Coding Agent" section for the full
  matrix, the Z.AI clamp caveat (as of the `@earendil-works/pi-coding-agent` 0.84.3 bump, the
  installed SDK's bundled catalog ships a real `thinkingLevelMap` for `glm-5.3`, so the opus/sonnet
  split is real, dispatch-visible behavior — not merely nominal; verified, not reimplemented, in
  `tests/test_pi_contract.py`'s pinned-catalog test, which fails loudly if a future catalog bump
  drops that map again), and the four fallback reasons.

`tests/test_pi_contract.py::test_model_tiers_are_inventoried`, its `EFFORTS` counterpart, and an
exhaustiveness check over `MODEL_POLICY`'s 3 providers x 3 tiers x 5 efforts ratchet the tier and
effort vocabulary against the live `agents/*.md` inventory, the same pattern §2 already uses for
tool tokens and skill ids — plus a pinned-catalog test asserting every cell's exact model id
actually exists in the bundled Pi SDK's provider data.

**Preloaded skills state their own resolvable directory.** A skill's body sometimes points at its
own `examples/` subdirectory ("see `examples/` for a worked implementation..." —
`swe-workbench:principle-solid`, `swe-workbench:principle-ddd`, etc.) without stating a path a
reader could actually resolve. `composeSystemPrompt` now prepends each preloaded skill's absolute
on-disk directory to its section header — not inlining `examples/` content (that stays on-demand,
fetched by the dispatched agent's own `read` tool if it decides the pointer is relevant), just
making the pointer resolvable instead of dead.

## 10. Framing decisions and rejected alternatives for the whole Pi port

§6–§9 above record decisions made as each phase of the Pi port needed them. This section records
the two decisions that framed the whole effort before any phase started, and the alternatives
considered and rejected before choosing them.

**Framing decision 1: event-translation over reimplementation.** `pi/extensions/guards.ts`
translates Pi's `tool_call`/`tool_result`/`session_start`/`session_compact` events into the exact
payload shape `hooks/bash_guard.sh`, `hooks/secret_guard.py`, `hooks/workflow_resume_hint.sh`, and
`hooks/skill_autoload_hint.sh` already expect, then execs the unchanged script (`guard-runner.ts`).
Every guard and hint stays a single source of truth on disk; Pi gets a thin translation layer, not
a second implementation of the same logic that could drift from Claude Code's.

**Framing decision 2: runtime parsing over generation.** The adapter reads `agents/*.md`,
`skills/*/SKILL.md`, and `commands/*.md` frontmatter and bodies at Pi session start
(`resources_discover`, `composeSystemPrompt`) rather than generating a separate Pi-native artifact
tree from those sources at build/release time. There is nothing to keep in sync, nothing to
regenerate, and no generator to maintain — the tradeoff is `tests/test_pi_contract.py`'s
golden-inventory ratchet standing in for the type safety a generation step would otherwise buy
(see §2).

**Rejected alternatives:**

- **Generate + drift-check** — emit a Pi-native copy of `agents/`/`skills/`/`commands/` at release
  time, with a CI check asserting the generated tree matches source. Rejected: doubles the
  maintenance surface (source + generated artifact) for a benefit runtime parsing already gets for
  free once a contract test exists.
- **Neutralize prose** — rewrite every skill/agent/command body to strip Claude-Code-specific tool
  names and replace them with harness-neutral placeholders. Rejected: would require touching every
  one of the 60 skills and 22 agents for a single consumer, and would still need a translation
  layer at read time for the tool names that remain — which `tool-vocab.ts`'s preamble already
  provides without any body-text rewrite.
- **Fork the repo** — maintain a separate repo or branch with its own copies of
  `skills/`/`agents/`/`commands/` for Pi. Rejected: guarantees drift from day one; every future
  skill or agent change would need a second, manual port.

**Where this has drifted from what shipped:**

- **Model-tier settings design reversed.** An earlier iteration planned a project-committed
  `.pi/settings.json` `modelTiers` block; §9 above records why that was reversed in favor of a
  hardcoded `MODEL_POLICY` table in reviewed source (`pi/extensions/model-policy.ts`) — a real
  exfiltration primitive avoided, not the design that originally shipped. That table itself later
  moved from substring/shortest-match resolution to exact-id resolution, and gained a portable
  `effort:` -> effective-thinking-level axis — §9 above has the current design.
- **Tier-2 tool set landed as 2 of 5 originally promised.** Only `ask_user_question`
  (`ask-user.ts`) and `task` (`subagent.ts`) are registered Pi tools today. A Pi-registered `LSP`
  tool was one of the tools scoped and then dropped — §8 above records why (the capability moved
  to `bin/swe-workbench-lsp`, reachable via `Bash` on any harness, before this phase started). The
  Tier-1 vocabulary prose (`tool-vocab.ts`) stays unconditional regardless of which Tier-2 tools
  actually register.

**`skill_usage_record.sh`/`skill_usage_flush.sh`: `"deferred"` → `"n/a"`.** The original
deferral rationale ("not wired yet because the Pi capability it needs (subagents) doesn't exist
yet") went half-stale when the `task` subagent-dispatch tool shipped (`pi/extensions/subagent.ts`)
— and re-examination showed the remaining gap is architectural, not a capability arrival away.
The hooks measure *runtime Skill invocations inside a dispatched subagent*; on Pi there is no
`Skill` tool in any process, dispatched children receive skill bodies preloaded into their system
prompt (`pi/extensions/agent-spec.ts`, per `docs/skill-preload.md`), and children run as separate
`pi.exec` processes whose events never reach the parent's extension instance. The observable is
structurally zero, so wiring would register handlers that can never carry real data: `record` has
no trigger event carrying `tool_input.skill`, and `flush` — whose trigger *is* synthesizable after
`pi.exec` resolves — would read input buffers that are never written, emitting a permanent `{}`
no-op while implying telemetry exists. Graduation to `"wired"` would require Pi to gain a runtime
Skill-invocation observable — a model-invocable tool whose call event carries the skill id,
which Pi's on-demand `read`-based skill loading does not provide — plus cross-process event
visibility into dispatched children, or this repo reversing the preload convention with a
child-side telemetry subsystem. None is a capability tick-box. The one genuine Pi-native
skill-usage signal — a top-level `read` of `skills/*/SKILL.md`, visible as a `tool_call` — sits
outside these hooks' measured population (they deliberately ignore the top-level orchestrator)
and would be a different feature. Neither branch of the wire-or-defer enumeration that framed
this re-examination was taken: the deferral premise had fired without enabling wiring.

## 11. Runtime result envelope — rejected alternatives

A `bin/` script with a genuinely structured result (a list of records, per-item failure
detail, real partial-success semantics) emits one standard JSON envelope
(`shared/docs/runtime-result-contract.md`) instead of `KEY=VALUE` lines for `eval`.
Several designs were considered and rejected while shaping that contract.

**Semver-range compatibility — considered, not adopted.** `schema` looked at first like
a natural home for a `major.minor.patch` version, with a consumer accepting any
compatible minor/patch bump. Rejected: `bin/` and every `skills/`/`commands/` consumer
of it ship together as one plugin release — there is no supported skew window where an
older consumer talks to a newer producer, or vice versa. A range check would silently
accept a `data` shape the consumer was never written against, deferring a real
incompatibility to a `jq` field-miss at read time instead of a loud failure at the
checker. `schema` compatibility is exact string equality instead — a mismatch is a
corrupted or partially-updated install, not a negotiable version difference.

**Dual-emit (old shape + new envelope, one flag apart) — considered, not adopted.**
Dual-emit exists to solve exactly the skew scenario the previous paragraph rejected: two
independently-versioned artifacts that need to interoperate during a rollout window.
That scenario cannot occur here, so a dual-emit flag would be permanent complexity
(two code paths to keep in sync, forever) bought to solve a problem this plugin's own
release model doesn't have. Every producer migration replaces its old output shape
outright, in the same PR as every consumer that reads it.

**A KEY=VALUE-emitting reader (translate the envelope back to `eval`-able shell
variables) — considered, not adopted.** This would have let existing `eval "$(...)"`
call sites keep their shape unchanged, touching only the producer. Rejected for the
same reason the envelope exists in the first place: a `[{path, reason}]` array (the
actual capability gain a migration like `swe-workbench-sweep-residuals`'s unlocks) has
no faithful `KEY=VALUE` representation — flattening it back into shell variables would
either lose the per-item detail again or require inventing an ad hoc shell-array
encoding, reintroducing the exact quoting/injection risk the envelope replaces. The
checker (`swe-workbench-result-check`) validates and passes the envelope through
unchanged instead; a consuming `SKILL.md` reads it with `jq`, never `eval`.

**Grandfathering an already-JSON producer's pre-envelope shape — considered, not
adopted.** `swe-workbench-preflight-commit` already emitted a flat JSON object before
the standard envelope existed, and no consumer depended on the flat shape surviving
(verified — its one consumer reads three named fields, cheap to update). Leaving it
un-wrapped "since it's already JSON" would have made the "standard" envelope contract
self-contradicting on day one — a producer visibly not following its own contract,
with no compatibility cost to justify the exception. Wrapped under `data` like every
other migrated producer instead.

**Fully migrating a Tier-Q producer to the envelope "for consistency" — considered,
not adopted.** `swe-workbench-preflight-pr` emits several `printf %q`-quoted scalars,
already safe for `eval`, with its one free-text channel (title/body) already routed
around `eval` entirely through a side-channel JSON file. Migrating it would have cost
real lines at every call site for zero capability gain — nothing about its result
needs a list, nested records, or a partial-status distinction a bare exit code can't
already express. Hardened with a golden-literal ratchet test pinning its exact 6-field
contract instead of migrating it — the S/Q/J decision test in
`shared/docs/runtime-result-contract.md` generalizes this call for any future producer.

## 12. `handoff_guard.py` — native mirror, never spawned on Pi

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

## 13. Cross-harness memory — main-checkout anchoring, dual-slug read, own-store-only writes

Each harness owns one per-repo memory store and reads the other's read-only
(`bin/swe-workbench-memory`, hooks/memory_hint.sh, issue #697). Four rulings:

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
