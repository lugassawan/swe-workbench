# Pi plan mode — plan on Sol, execute on Terra

Rulings on the plan/execute phase split for the Pi adapter (`pi/extensions/phase-policy.ts`,
`pi/extensions/phase.ts`). Sibling rulings live in the `docs/decisions-*.md` files.

## 1. The problem

A `/swe-workbench:implement` run spends a few high-judgment planning turns and many execution
turns, all billed at Sol's rate; planning needs Sol, execution is Terra work. Claude Code's
plan mode (plan → approval → execute) is the reference UX — Pi has none; built as an extension.

## 2. Ruling

- **Entry** — each plan-armed `commands/*.md` carries one marker line, `<!-- swb-phase: plan -->`,
  after its frontmatter; the adapter arms the gate on it in the expanded prompt at
  `before_agent_start`. Content-keyed, never filename-keyed; inventory ratchet-tested.
- **Plan-armed set** — `architect`, `audit-codebase`, `capture`, `debug`, `design`, <!-- validate: prose-ref -->
  `document`, `extend`, `hotfix`, `implement`, `migrate`, `refactor`.
- **Neutral by design** — `address-feedback`, `cleanup-merged`, `codebase-knowledge`, <!-- validate: prose-ref -->
  `converge`, `doctor`, `handoff`, `memory`, `report-issue`, `review`, `security-review`, <!-- validate: prose-ref -->
  `sync`, `test` carry no marker: execution cost is delegated or short-lived, so no auto-flip.
- **Arming — latest explicit plan command wins** — a marker arms plan phase from ANY state
  and best-effort flips to the plan model; re-invocation re-arms idempotently.
- **Approval (`submit_plan`)** — Claude Code's `ExitPlanMode` transposed: Approve flips to
  the sonnet-tier execution model and disarms atomically; Revise returns feedback, stays armed.
- **Read-only steering** — plan phase blocks `edit`/`write` with `terminate: true`, steering
  the model to `submit_plan`, except inside `~/.pi/agent/plans/`: the drafted plan persists as
  it goes, so a broken session never discards the work (durability over gate purity — the
  user-global dir is writable from any repo or worktree). Steering, not containment: bash and
  dispatched subagents stay ungated; the adversary is a cooperative model.
- **User override wins** — a manual model change (`model_select` source `set`/`cycle`) disarms
  the gate; `restore` (session resume) does not.

## 3. Layering

`phase-policy.ts` is domain — pure data and functions, no Pi SDK import; phase→model resolution
reuses `MODEL_POLICY`'s tier rows (plan = opus, execute = sonnet). `phase.ts` is the adapter
owning every SDK touch, wired from `index.ts` after `registerGuards` so security verdicts win;
its handler bodies self-wrap per the runner's no-try/catch contract.

## 4. Accepted degradations and known gaps

- Resume mid-plan restores the model but not the gate; `pi.appendEntry` is the slot if it bites.
- Direct `/skill:workflow-development` bypasses command markers; extendable to skills later.
- Plans live in the user-global `~/.pi/agent/plans` — a deliberate fork of superpowers'
  repo-local `docs/superpowers/plans` convention: Claude Code parity, one canonical dir,
  survives worktree switches; cost: flat cross-project mixing, per-machine.
- Execute persists the plan if needed, then runs the 5-phase workflow (post-approval only).
- One full-context re-bill at the flip; the stable section invalidates at most twice per run.
- Thinking-level split and `defaultModel` flip: follow-up tunings, not v1.
- Headless: no arming, gate, flip, or section; `submit_plan` throws actionable text without a UI.

## 5. Explicitly rejected

- `registerCommand` shadowing — replaces the prompt-template entry point; a hijack, not a hook.
- Input-event string matching on `/<command>` — duplicates filename knowledge, misses expansion
  paths, false-positives on prose quoting command names.
- Interactive relay subagents — a ~400–700-line subsystem duplicating one `setModel()` call
  (`docs/decisions-task-dispatch.md`).
