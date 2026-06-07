---
description: Clean up worktree and local + remote branch for a merged PR
argument-hint: [PR number — optional, defaults to current branch]
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
Target: $ARGUMENTS (PR number if provided; otherwise derive from current branch)

Invoke `swe-workbench:workflow-cleanup-merged` to perform the full cleanup.

Pass the PR number from $ARGUMENTS to the skill if provided. If $ARGUMENTS is empty, the skill will derive the target branch from the current branch.

When the skill completes, print a summary listing each artifact (worktree, local branch, remote branch) and whether it was removed or was already gone, plus whether local main was synced to origin/main.

## Output

The `workflow-cleanup-merged` skill produces a structured artifact summary. Expect one status line per artifact:

- **Worktree** — path and whether it was removed or was already absent.
- **Local branch** — branch name and whether it was deleted or was already gone.
- **Remote branch** — remote ref and whether it was deleted, was already gone, or was skipped (no push permission).
- **Main sync** — whether local `main` was fast-forwarded to `origin/main` or was already up to date.

Total lines: four. No severity tiers — this is a cleanup confirmation, not a findings report.
