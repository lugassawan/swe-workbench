# Plugin platform decisions — the task subagent dispatcher

Rulings on `task`, the first-party subagent dispatcher (`pi/extensions/subagent.ts`):
why it exists alongside the `pi-subagents` package, its recursion guards, and the
model-dispatch policy it enforces. Recorded here so they don't have to be re-litigated.
Sibling rulings live in the other `docs/decisions-*.md` files (indexed in
`docs/README.md`).

## 1. `task` — a first-party subagent dispatcher, not a fork of `pi-subagents`

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
effort vocabulary against the live `agents/*.md` inventory, the same pattern `docs/decisions-ci-validation.md` §1 already uses for
tool tokens and skill ids — plus a pinned-catalog test asserting every cell's exact model id
actually exists in the bundled Pi SDK's provider data.

**Preloaded skills state their own resolvable directory.** A skill's body sometimes points at its
own `examples/` subdirectory ("see `examples/` for a worked implementation..." —
`swe-workbench:principle-solid`, `swe-workbench:principle-ddd`, etc.) without stating a path a
reader could actually resolve. `composeSystemPrompt` now prepends each preloaded skill's absolute
on-disk directory to its section header — not inlining `examples/` content (that stays on-demand,
fetched by the dispatched agent's own `read` tool if it decides the pointer is relevant), just
making the pointer resolvable instead of dead.
