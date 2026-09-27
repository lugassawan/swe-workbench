# Plugin platform decisions — Pi plan phase with per-phase models

Rulings on the plan/execute phase split for the Pi adapter (`pi/extensions/phase-policy.ts`,
`pi/extensions/phase.ts`): why it exists, how phase entry and the approval transition work, and
what was deliberately excluded. Recorded so it does not have to be re-litigated. Sibling rulings
live in the other `docs/decisions-*.md` files (indexed in `docs/README.md`).

## 1. The problem: one model for both halves of a run

The user's Pi session defaults to `gpt-5.6-sol` (opus tier) with thinking `high`
(`~/.pi/agent/settings.json`). A typical `/implement` run spends a handful of high-judgment turns
planning and *many* turns executing — all billed at Sol rates. Only the planning minority needs
Sol; execution is sonnet-tier work (`gpt-5.6-terra`). The subagent dispatcher already encodes this
asymmetry — `agents/*.md` frontmatter tiers dispatch `senior-engineer`/`architect` on opus→Sol and
`code-impl` on sonnet→Terra via `MODEL_POLICY` — but the **main thread** had no phase notion: it
runs one model for everything, which is why the usage dashboard shows Sol dominating.

Claude Code's plan mode is the reference UX: plan (read-only) → approval dialog → execute. Pi has
no plan mode; this feature builds the equivalent as an extension, with the model flip as a
first-class part of the transition.

## 2. Ruling: marker-declared phase entry, approval-tool transition

- **Entry** — each phase-armed `commands/*.md` carries one exact marker line,
  `<!-- swb-phase: plan -->`, immediately after its frontmatter. The adapter detects the marker in
  the *expanded* prompt at `before_agent_start` (the event fires after template/skill expansion,
  so `/implement …` and every other invocation path of that template is covered) and arms the gate
  for that run. Detection keys on content, not filenames — renaming a command cannot silently
  detach it. The marker inventory is ratchet-tested in both directions (armed file missing the
  marker fails; neutral file carrying it fails).
- **Phase-armed set (v1)** — `architect`, `capture`, `debug`, `design`, `extend`, `hotfix`,
  `implement`, `migrate`, `refactor`. All other commands are neutral (no marker, no machinery).
  `converge`, `report-issue`, `security-review` defaulted neutral in v1; reclassification is a
  one-line marker edit plus ratchet bump.
- **Transition** — a model-callable `submit_plan` tool is the Claude-Code `ExitPlanMode`
  transposed: the planner calls it with the finished plan; the handler renders an Approve/Revise
  dialog (`ctx.ui.custom`, `ctx.ui.editor` for revision, `ctx.ui.confirm` fallback in non-TUI
  modes). **Approve** flips the session model to the sonnet-tier execution model
  (`pi.setModel`, session-scoped) and disarms the gate atomically inside the tool handler;
  **Revise** returns the user's feedback and stays armed on the plan model. `/implement` therefore
  spans both phases: plan on Sol → approval → execution on Terra in the same session.
- **Read-only steering** — while armed, a `tool_call` handler blocks `edit`/`write` with
  `terminate: true`, steering the model to `submit_plan`, **except for targets inside
  `docs/superpowers/plans/`**: the planner persists the plan file during plan phase so a broken
  session never discards the work (user requirement — durability over gate purity). This is
  steering, not containment: bash is deliberately ungated (the planner needs reads, diagnostics,
  test runs) and dispatched subagents are separate `pi` child processes whose tool calls never
  pass through the parent's `tool_call` handler — so a heredoc-write or an eager `code-impl`
  dispatch can bypass the gate, which is accepted — the adversary is a cooperative model, not a
  malicious actor. Never document this feature as "enforced read-only".
- **User override wins** — a manual model change (`model_select` with source `set` or `cycle`,
  i.e. `/model` or Ctrl+P) disarms the gate. `restore` (session resume) does not.

## 3. Layering (same posture as `model-policy.ts` / `agent-spec.ts`)

`phase-policy.ts` is domain: pure data and functions over strings and tier names, importing
nothing from the Pi SDK — not even as a type. Phase→model resolution *reuses* `MODEL_POLICY`'s
tier rows (plan = opus row, execute = sonnet row) rather than adding a second model table, so the
split is provider-portable for free. `phase.ts` is the adapter owning every SDK touch: events,
dialogs, `modelRegistry.find`, `setModel`. Wired from `index.ts` as `registerPhase(pi, root)`
registered **after** `registerGuards` so security-block reasons always win the short-circuit, and
its `tool_call` handler self-wraps (returns `undefined` on throw) per the runner's
no-try/catch-around-handler-bodies contract.

## 4. Accepted degradations and known gaps (v1)

- **Resume mid-plan**: the transcript restores the model (right model, gate off, no banner).
  Benign; `pi.appendEntry("swb-phase-state", …)` is the ready-made persistence slot if it bites.
- **`/skill:workflow-development` typed directly** bypasses command markers — documented gap;
  the marker grammar extends to skill bodies if it matters later.
- **Plan-file persistence during plan phase**: the planner writes the plan to
  `docs/superpowers/plans/` as it drafts (gate allowlist — durability against session loss), and
  the `submit_plan` payload remains the approval artifact. Post-approval, the execution session
  executes from the on-disk plan (persisting it first if the planner never did) and then runs the
  5-phase workflow (Branch → Implement → Verify → Review → Deliver) — an execution-time
  lifecycle that begins only post-approval, where edit/write is unblocked by construction.
- **Cache cost of the flip**: one full-context re-bill at the flip (different model = cold
  prefix), then Terra owns the long execution tail. The injected phase section is
  stable-within-state so it invalidates at most twice per run.
- **Thinking-level split** (e.g. Terra at a lower effort) and **`defaultModel` flip to Terra**
  are follow-up tunings, not v1.
- **Headless sessions** (`-p`/print mode, dispatched children): behavior-identical, not
  byte-for-byte — no arming, no gate, no flip, no section injection; `submit_plan` remains
  registered (its name/description/promptSnippet are visible to a headless session's model)
  but is unreachable-by-dialog — it throws actionable text without a UI.
- **No execute→plan re-entry**: arming requires `disarmed`, so a second phase-armed command in
  the same session after approval stays in `execute` — intentional, so a follow-up command
  cannot silently re-arm plan-phase steering mid-execution.

## 5. Explicitly rejected

- **`registerCommand` shadowing** of command names — an extension command *replaces* the prompt
  template entry point (prompt-templates.md) with no public API to re-render the template; a
  hijack, not a hook.
- **Input-event string matching on `/<command>`** — duplicates filename knowledge in a parallel
  set, misses expansion-time invocation paths, and false-positives on prose that quotes command
  names (`hotfix.md`, `extend.md` both mention `/swe-workbench:implement` in their bodies).
- **Interactive relay subagents** (RPC dialog bridging so a dispatched child can ask questions
  through the parent's TUI) — feasible per Pi's RPC Extension UI protocol but a ~400–700-line
  subsystem whose payoff duplicates one `setModel()` call. Planning interactivity stays in the
  main thread, where dispatched children are headless by design (see
  `docs/decisions-task-dispatch.md`).
