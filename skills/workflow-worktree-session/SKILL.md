---
name: workflow-worktree-session
orchestrator: true
description: Use when the user mentions a worktree — to start, switch, resume, continue, or end a worktree session. Routes to `EnterWorktree` / `ExitWorktree` so the running claude moves into the worktree without restart. Covers switching into an existing worktree (`git worktree add` then mid-session entry), resuming or continuing work in an already-created worktree, pivoting current work into a new worktree, and exiting back. Also fires when a user describes the cd-prefix symptom ("I've been cd-ing into the worktree", "I've been cd-prefixing commands"). Does NOT replace `superpowers:using-git-worktrees` for new feature kickoffs (consent, ignore-check, baseline tests).
---

# Workflow: Worktree Session

**Announce at start:** "I'm using the workflow-worktree-session skill to move the session into the worktree."

## Decision tree

Read the user's prompt and pick exactly one mode:

### Mode A — Switch into an existing worktree

Triggers: user named or pointed at a worktree that already exists, or is resuming / continuing work in a worktree already created.

Examples: "open the `feat-login` worktree", "switch to `test-enter`", "move into `.worktrees/auth`", "cd into the worktree I made", "continue work in the worktree I made", "resume in the worktree", "I've been cd-ing into the worktree", "I've been cd-prefixing commands".

1. Discover the path. Resolve rimba using the detection helper in `workflow-development` Phase 1 (`$RIMBA`). If non-empty, run `$RIMBA list --json` to list worktrees. Otherwise use `git worktree list --porcelain`:

   ```bash
   git worktree list --porcelain \
     | awk '/^worktree /{path=substr($0,10); branch=""} /^branch /{branch=substr($0,8)} /^$/{print path, (branch ? branch : "(detached)")}'
   ```

   Match the user's name against branch names or directory basenames. If no match is found, tell the user no worktree matched their description and stop — do not call `EnterWorktree` with an empty path.

2. Enter the worktree. **Try `EnterWorktree(path=<absolute-path>)` first.** From the main session this works for any registered worktree (including rimba's `../<repo>-worktrees/` layout). If rejected because the session is already inside a **different worktree** (target path outside `.claude/worktrees/`), the primary remedy is `ExitWorktree(action=keep)` → return to main session → retry `EnterWorktree(path=<absolute-path>)` (re-anchors session caches; `action=keep` is non-destructive — the source worktree stays on disk). As a last resort only for non-rimba checkouts with no `.claude/worktrees` infrastructure, fall back to `cd <absolute-path>` via Bash; `cd` only anchors the Bash persistent cwd and does not re-anchor session-level caches (plans dir, memory dir) the way `EnterWorktree` does. After entry by either method, still run the Step 3 confirmation — the `--git-dir ≠ --git-common-dir` check is path-independent and confirms you are actually in a linked worktree regardless of entry method.

3. Confirm: run `git rev-parse --git-dir --git-common-dir` and verify the two paths differ (linked worktree, not main). Report the new CWD.

### Mode B — Create a new worktree for this task

Triggers: "in a fresh worktree", "in a new worktree", "spin up a worktree for this".

Defer entirely to `superpowers:using-git-worktrees`. That skill handles consent, `.gitignore` safety check, baseline tests, and calls `EnterWorktree(name=…)` itself (Step 1a of that skill). Do not duplicate its logic here.

> **rimba integration:** if rimba is available (on PATH or at a common install location — see detection helper in `workflow-development` Phase 1), `workflow-development` Phase 1 detects it and uses `rimba add <task>` directly for branch creation. Mode B here still defers to `superpowers:using-git-worktrees` for consent, `.gitignore` checks, and baseline tests — rimba detection is owned by that caller's Phase 1. Do not bypass the superpowers lifecycle steps.

### Mode C — Exit the current worktree

Triggers: "exit the worktree", "go back", "leave this worktree", "return to main".

Call `ExitWorktree(action: "keep")` by default. If it succeeds, the session was `EnterWorktree`-anchored and exit is complete.

**If it reports a no-op:** a no-op means only *no active `EnterWorktree` session* — it does **not** by itself confirm `cd`-entry. Two causes present identically:

1. **cd-entry** — the session was always anchored via the `cd` fallback and `EnterWorktree` was never called.
2. **Compaction dropped tracking** — the session *was* `EnterWorktree`-anchored, but auto-compaction silently lost the harness's session-level anchoring while the Bash cwd stayed inside the worktree (issue #497). `EnterWorktree`/`ExitWorktree` are harness-owned tools — the plugin cannot change their output or make the harness persist this across compaction.

Before assuming cd-entry, actively probe for context:

```bash
git rev-parse --git-dir --git-common-dir
```

If the two paths differ, cwd is genuinely inside a linked worktree (not the main checkout). This is necessary context but **not proof of which cause applies** — a `cd`-fallback entry produces the identical divergence, since cwd is physically inside the worktree either way. Additionally, check for a fresh `.claude/cache/workflow-state/<branch>.json` (see `docs/workflow-state.md`): a `context.worktree_root` matching the live cwd confirms this branch's workflow was operating in this worktree, but `worktree_root` is written via `git rev-parse --show-toplevel` regardless of entry method — so it does not discriminate either.

Git state alone cannot distinguish cd-entry from compaction-dropped tracking; the harness's internal `EnterWorktree` session state is not observable from outside. When cwd resolves to a linked worktree, state the situation without asserting a definitive cause — e.g. **"tracking may have been lost to compaction — this cannot be confirmed from git state alone, since cd-entry produces identical evidence"** — citing the `--git-dir`/`--git-common-dir` divergence and/or the `worktree_root` match as the (non-discriminating) context, not proof. Either way, proceed to the same recovery below.

**Recovery is the same regardless of which cause applies** — run the following to return to the main repo root:

```bash
_GCD=$(git rev-parse --git-common-dir)
# relative (.git) means we're already at main root — nothing to do
[[ "$_GCD" != /* ]] || cd "${_GCD%/.git}"
```

> **Note:** assumes a standard embedded `.git` directory; `--separate-git-dir` setups and submodule common dirs may return a path that does not end in `/.git`, requiring a different navigation strategy.

Call `ExitWorktree(action: "remove")` **only** when the user explicitly says *remove*, *delete*, or *clean up* the worktree. If it is rejected or unavailable and the session is `cd`-entered, remove the worktree and then navigate to the main repo root. Only run this snippet when confirmed to be inside a linked worktree (if cwd is already at main root, `git worktree remove` will fail with "fatal: is a main worktree"):

```bash
# capture before remove — path is gone after git worktree remove
_GCD=$(git rev-parse --git-common-dir)
git worktree remove "$(git rev-parse --show-toplevel)"
# relative (.git) means we're already at main root — cd is a no-op
[[ "$_GCD" != /* ]] || cd "${_GCD%/.git}"
```

> **Note:** assumes a standard embedded `.git` directory; `--separate-git-dir` setups and submodule common dirs may return a path that does not end in `/.git`, requiring a different navigation strategy.

## Forbidden pattern

**`cd` is not the primary session switch — `EnterWorktree` is.** The Bash tool's working directory *does* persist across calls (subsequent commands run from the `cd`-ed directory), but `cd` does not re-anchor session-level caches (plans dir, memory dir, env cwd) the way `EnterWorktree` does. Use `cd` only as the sanctioned fallback when `EnterWorktree(path=…)` is rejected (see Mode A step 2 above).

**Active remedy:** If you notice you have already been prepending `cd <worktree>` to commands this session, that is the signal — stop and try `EnterWorktree(path=<worktree-path>)` now. If it succeeds, the session is properly anchored. If it is rejected because the session is already inside a **different worktree** (target path outside `.claude/worktrees/`), call `ExitWorktree(action=keep)` to return to the main session, then retry `EnterWorktree(path=<worktree-path>)` — this is the correct switch-between-worktrees sequence (`action=keep` is non-destructive; the source worktree remains on disk). Use `cd` only as a last resort for non-rimba checkouts with no `.claude/worktrees` infrastructure.

## Do not auto-exit

Do not call `ExitWorktree` proactively. Only call it when the user explicitly requests it (Mode C). The harness prompts the user on session end; do not second-guess it.

## Quick reference

| User says | Mode | Tool call |
|-----------|------|-----------|
| "open the `feat-login` worktree" | A | `EnterWorktree(path=<resolved>)` → if in different worktree: `ExitWorktree(keep)`+retry → `cd <path>` (last resort, no-infra only) |
| "switch to `.worktrees/auth`" | A | `EnterWorktree(path=<abs-path>)` → if in different worktree: `ExitWorktree(keep)`+retry → `cd <path>` (last resort, no-infra only) |
| "continue work in the worktree I made" | A | `EnterWorktree(path=<resolved>)` → if in different worktree: `ExitWorktree(keep)`+retry → `cd <path>` (last resort, no-infra only) |
| "resume in the worktree" | A | `EnterWorktree(path=<resolved>)` → if in different worktree: `ExitWorktree(keep)`+retry → `cd <path>` (last resort, no-infra only) |
| "I've been cd-ing into the worktree" | A | `EnterWorktree(path=<resolved>)` → if in different worktree: `ExitWorktree(keep)`+retry → `cd <path>` (last resort, no-infra only) |
| "in a fresh worktree" | B | defer to `superpowers:using-git-worktrees` |
| "exit the worktree" | C | `ExitWorktree(action: "keep")` → no-op ⇒ probe `--git-dir`/`--git-common-dir` + `worktree_root` (cd-entry **or** compaction-dropped tracking, not confirmed cd-entry) → `cd <main-root>` |
| "delete this worktree and go back" | C | `ExitWorktree(action: "remove")` → else capture GCD, `git worktree remove <path>`, `cd <main-root>` |
| "add a branch for this work" | — | **skill does not fire** (no "worktree" word) |
