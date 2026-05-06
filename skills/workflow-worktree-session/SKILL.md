---
name: workflow-worktree-session
description: Use when the user mentions "worktree" to start, switch, or end a worktree-bound session — routes to `EnterWorktree` / `ExitWorktree` so the running claude moves without restart. Covers switching into an existing worktree (`git worktree add` then mid-session entry), pivoting current work into a new worktree, and exiting back. Does NOT replace `superpowers:using-git-worktrees` for new feature kickoffs (consent, ignore-check, baseline tests).
---

# Workflow: Worktree Session

**Announce at start:** "I'm using the workflow-worktree-session skill to move the session into the worktree."

## Decision tree

Read the user's prompt and pick exactly one mode:

### Mode A — Switch into an existing worktree

Triggers: user named or pointed at a worktree that already exists
("open the `feat-login` worktree", "switch to `test-enter`", "move into `.worktrees/auth`", "cd into the worktree I made").

1. Discover the path. Try `rimba list --json` first if `rimba` is on PATH (forward-compatible with rimba worktree-lifecycle integration). Otherwise use `git worktree list --porcelain`:

   ```bash
   git worktree list --porcelain | awk '/^worktree /{path=$2} /^branch /{branch=$2; print path, branch}'
   ```

   Match the user's name against branch names or directory basenames.

2. Call `EnterWorktree(path=<absolute-path>)`.

3. Confirm: run `git rev-parse --git-dir --git-common-dir` and verify the two paths differ (linked worktree, not main). Report the new CWD.

### Mode B — Create a new worktree for this task

Triggers: "in a fresh worktree", "in a new worktree", "spin up a worktree for this".

Defer entirely to `superpowers:using-git-worktrees`. That skill handles consent, `.gitignore` safety check, baseline tests, and calls `EnterWorktree(name=…)` itself (Step 1a of that skill). Do not duplicate its logic here.

> **When rimba (#111) lands:** `rimba add <task>` prints a path. In that case, pass the printed path to `EnterWorktree(path=<rimba output>)` instead of deferring.

### Mode C — Exit the current worktree

Triggers: "exit the worktree", "go back", "leave this worktree", "return to main".

Call `ExitWorktree(action: "keep")` by default.
Call `ExitWorktree(action: "remove")` **only** when the user explicitly says *remove*, *delete*, or *clean up* the worktree.

## Forbidden pattern

**Never use `Bash(cd <worktree-path>)` to switch the session.** `cd` in a Bash invocation only affects that single shell subprocess. The Claude Code session CWD is owned by `EnterWorktree` / `ExitWorktree`; `cd` silently does nothing to it.

## Do not auto-exit

Do not call `ExitWorktree` proactively. Only call it when the user explicitly requests it (Mode C). The harness prompts the user on session end; do not second-guess it.

## Quick reference

| User says | Mode | Tool call |
|-----------|------|-----------|
| "open the `feat-login` worktree" | A | `EnterWorktree(path=<resolved>)` |
| "switch to `.worktrees/auth`" | A | `EnterWorktree(path=<abs-path>)` |
| "in a fresh worktree" | B | defer to `superpowers:using-git-worktrees` |
| "exit the worktree" | C | `ExitWorktree(action: "keep")` |
| "delete this worktree and go back" | C | `ExitWorktree(action: "remove")` |
| "add a branch for this work" | — | **skill does not fire** (no "worktree" word) |
