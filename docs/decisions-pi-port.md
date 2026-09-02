# Plugin platform decisions — the Pi Coding Agent port

Rulings from porting the plugin to the Pi Coding Agent — a runtime adapter
(`pi/extensions/`) that loads this plugin's existing `skills/`, `commands/`, and
`agents/` trees unchanged. §1–§3 record what has no Pi equivalent and why; §4 records
the framing decisions and rejected alternatives behind the whole port. Recorded here so
they don't have to be re-litigated. The `task` dispatcher's rulings live next door in
`docs/decisions-task-dispatch.md`; sibling rulings are indexed in `docs/README.md`.

## 1. `worktree_permission_grant.sh` has no Pi equivalent — documented N/A, not deferred

`pi/extensions/guards.ts` reproduces `bash_guard.sh`, `secret_guard.py`,
`workflow_resume_hint.sh`, and `skill_autoload_hint.sh` on Pi, each exec'ing the unchanged
Claude Code script. `worktree_permission_grant.sh` is left out deliberately and permanently.

The hook emits `permissionDecision: "allow"` so Claude Code's permission-prompt system skips
asking about paths inside the active worktree. Pi's README states "No permission popups" — there
is no prompt surface for a `tool_call` handler to target, so a port would have nothing to grant
permission *for*.

Recorded as an explicit `"n/a"` row in `tests/test_pi_contract.py`'s `HOOK_PI_STATUS` inventory
— as are `skill_usage_record.sh`/`skill_usage_flush.sh` (§4 records why their concept, runtime
Skill invocation by a dispatched subagent, has no Pi counterpart either). `"n/a"` never
graduates to `"wired"`.

## 2. `EnterWorktree`/`ExitWorktree` have no Pi equivalent — documented N/A, not deferred

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
`"n/a"`-shaped decision here — mirroring §1 — rather than left implicit.

## 3. `LSP` has no Pi tool registration — the capability lives in `bin/`, not the adapter

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

Recorded as an explicit `"n/a"` decision — mirroring §1 and §2 — rather than left implicit.
Unlike §1, this is not a `HOOK_PI_STATUS` row: that inventory is keyed to `hooks/*.sh|py` and
asserted exhaustive against that directory; `swe-workbench-lsp` lives in `bin/`, so this section is
the record. `"n/a"` never graduates to `"wired"`.

## 4. Framing decisions and rejected alternatives for the whole Pi port

§1–§3 above and `docs/decisions-task-dispatch.md` record decisions made as each phase of the Pi port needed them. This section records
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
(see `docs/decisions-ci-validation.md` §1).

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
  `.pi/settings.json` `modelTiers` block; `docs/decisions-task-dispatch.md` records why that was reversed in favor of a
  hardcoded `MODEL_POLICY` table in reviewed source (`pi/extensions/model-policy.ts`) — a real
  exfiltration primitive avoided, not the design that originally shipped. That table itself later
  moved from substring/shortest-match resolution to exact-id resolution, and gained a portable
  `effort:` -> effective-thinking-level axis — `docs/decisions-task-dispatch.md` has the current design.
- **Tier-2 tool set landed as 2 of 5 originally promised.** Only `ask_user_question`
  (`ask-user.ts`) and `task` (`subagent.ts`) are registered Pi tools today. A Pi-registered `LSP`
  tool was one of the tools scoped and then dropped — §3 above records why (the capability moved
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
