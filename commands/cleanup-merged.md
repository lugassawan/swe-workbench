---
description: Clean up worktree and local + remote branch for a merged PR
argument-hint: [PR number — optional, defaults to current branch]
---

Target: $ARGUMENTS (PR number if provided; otherwise derive from current branch)

Invoke `swe-workbench:workflow-cleanup-merged` to perform the full cleanup.

Pass the PR number from $ARGUMENTS to the skill if provided. If $ARGUMENTS is empty, the skill will derive the target branch from the current branch.

When the skill completes, print a summary listing each artifact (worktree, local branch, remote branch) and whether it was removed or was already gone, plus whether local main was synced to origin/main.
