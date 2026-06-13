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

2. Enter the worktree. **Try `EnterWorktree(path=<absolute-path>)` first.** From the main session this works for any registered worktree (including rimba's `../<repo>-worktrees/` layout). If it is rejected for any reason (most commonly: session already inside a worktree with the target path outside `.claude/worktrees/`) — fall back to `cd <absolute-path>` via Bash. The Bash tool's working directory persists across calls, so subsequent git/build/test commands run from the worktree; note that this fallback does not re-anchor session-level caches (plans dir, memory dir) the way `EnterWorktree` does. After `cd`, still run the Step 3 confirmation — the `--git-dir ≠ --git-common-dir` check is path-independent and confirms you are actually in a linked worktree regardless of entry method.

3. Confirm: run `git rev-parse --git-dir --git-common-dir` and verify the two paths differ (linked worktree, not main). Report the new CWD.

### Mode B — Create a new worktree for this task

Triggers: "in a fresh worktree", "in a new worktree", "spin up a worktree for this".

Defer entirely to `superpowers:using-git-worktrees`. That skill handles consent, `.gitignore` safety check, baseline tests, and calls `EnterWorktree(name=…)` itself (Step 1a of that skill). Do not duplicate its logic here.

> **rimba integration:** if rimba is available (on PATH or at a common install location — see detection helper in `workflow-development` Phase 1), `workflow-development` Phase 1 detects it and uses `rimba add <task>` directly for branch creation. Mode B here still defers to `superpowers:using-git-worktrees` for consent, `.gitignore` checks, and baseline tests — rimba detection is owned by that caller's Phase 1. Do not bypass the superpowers lifecycle steps.

### Mode C — Exit the current worktree

Triggers: "exit the worktree", "go back", "leave this worktree", "return to main".

Call `ExitWorktree(action: "keep")` by default. If uncertain whether the session was entered via `EnterWorktree` or the `cd` fallback, attempt `ExitWorktree(action=keep)` first — if it succeeds the session was `EnterWorktree`-anchored and exit is complete; if it reports a no-op (confirms `cd`-entry) or is unavailable (treat the following as a best-effort fallback — entry method is unknown) — run the following to return to the main repo root:

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

**Active remedy:** If you notice you have already been prepending `cd <worktree>` to commands this session, that is the signal — stop and try `EnterWorktree(path=<worktree-path>)` now. If it succeeds, the session is properly anchored. If it is rejected for any reason (most commonly: session is already in a worktree + path is outside `.claude/worktrees/`), the `cd`-prefix is the correct sanctioned fallback — ensure you are consistently `cd`-ing to the same path and do not also call `ExitWorktree` (it is a no-op for `cd`-entered worktrees; use the `cd`-to-main-root fallback in Mode C instead).

## Do not auto-exit

Do not call `ExitWorktree` proactively. Only call it when the user explicitly requests it (Mode C). The harness prompts the user on session end; do not second-guess it.

## Quick reference

| User says | Mode | Tool call |
|-----------|------|-----------|
| "open the `feat-login` worktree" | A | `EnterWorktree(path=<resolved>)` → else `cd <path>` |
| "switch to `.worktrees/auth`" | A | `EnterWorktree(path=<abs-path>)` → else `cd <path>` |
| "continue work in the worktree I made" | A | `EnterWorktree(path=<resolved>)` → else `cd <path>` |
| "resume in the worktree" | A | `EnterWorktree(path=<resolved>)` → else `cd <path>` |
| "I've been cd-ing into the worktree" | A | `EnterWorktree(path=<resolved>)` → else `cd <path>` |
| "in a fresh worktree" | B | defer to `superpowers:using-git-worktrees` |
| "exit the worktree" | C | `ExitWorktree(action: "keep")` → else `cd <main-root>` (best-effort if tool unavailable; lock may remain) |
| "delete this worktree and go back" | C | `ExitWorktree(action: "remove")` → else capture GCD, `git worktree remove <path>`, `cd <main-root>` |
| "add a branch for this work" | — | **skill does not fire** (no "worktree" word) |
