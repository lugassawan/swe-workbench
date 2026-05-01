---
name: workflow-cleanup-merged
description: Use after a PR has been merged on GitHub to remove the local worktree, delete the local branch, and delete the remote branch — safely, with squash-merge support.
---

# Workflow: Cleanup Merged Branch

**Announce at start:** "I'm using the workflow-cleanup-merged skill to clean up after the merged PR."

## When to Invoke

- After the user has confirmed a PR is merged on GitHub.
- Invoked by `/swe-workbench:cleanup-merged` (user-triggered, one-off cleanup).
- Invoked by Mode C orchestration (`orchestration.md`) at Step 7, after each merge round.

**Never auto-trigger.** Cleanup is user-initiated or orchestrator-initiated. Do not attach to a Stop hook.

## What This Skill Does NOT Do

- Does not merge PRs — that is the user's action.
- Does not force-delete branches with uncommitted work — no `--force`, ever.
- Does not squash, rebase, or alter commit history.
- Does not bypass branch protection rules.
- Does not verify CI status — CI verification happens in Phase 3/4 before the PR is created.

## Cleanup Contract

### Step 1 — Resolve Target PR

- If the user passed a PR number → use it directly.
- Else → derive from current branch:
  ```
  gh pr view --json number,state,mergedAt,headRefName,headRepository
  ```
  Extract `headRefName` as the branch name to clean up.

### Step 2 — Verify Merged via `gh` (Sole Oracle)

```
gh pr view <number> --json state,mergedAt,headRefName
```

Read `state == "MERGED"` **and** `mergedAt != null`. Abort with a clear message if either condition fails.

**Never use `git branch --merged` as a merge check.** GitHub's default squash-merge strategy creates a new commit SHA on `main`; the original branch tip is not a merge ancestor of `main`, so `git branch --merged` silently lies. `gh` is the only oracle that does not lie.

### Step 3 — Locate Worktree

```
git worktree list --porcelain
```

Match by `branch refs/heads/<headRefName>`. Per `superpowers:using-git-worktrees` convention, the worktree directory name equals the branch name. If no worktree matches, skip Steps 4 and 5 — the PR was developed in the main repo checkout, which is fine.

### Step 4 — Safety Checks (Abort on Any Failure)

Run these checks **inside the worktree directory** (if a worktree was found):

**Check 1 — No uncommitted changes:**
```
git -C "<worktree-path>" status --porcelain
```
Must return empty output. If not, print the diff summary and abort — never delete a worktree with uncommitted work.

**Check 2 — No unpushed commits:**
```
git -C "<worktree-path>" log @{upstream}..HEAD
```
Must return empty output. If not, list the unpushed commits and abort.

**Check 3 — Not standing inside the worktree:**
If `cwd` is a subdirectory of `<worktree-path>`, `cd` to the main repo root first:
```
cd "$(git rev-parse --show-toplevel)"
```
Never attempt to delete the directory you're standing in.

### Step 5 — Remove Worktree

```
git worktree remove "<worktree-path>"
```

No `--force`. If this fails (unexpected state), abort and report the error — do not proceed to branch deletion.

### Step 6 — Delete Local Branch

```
git branch -D <headRefName>
```

Capital `-D` is required. Because squash-merge creates a new commit on `main` with a different SHA, the local branch is never a merge ancestor of `main`. Lowercase `-d` would refuse to delete it. This is expected and correct behavior, not a footgun — the `gh` oracle already confirmed the PR is merged.

### Step 7 — Delete Remote Branch

```
git push origin --delete <headRefName>
```

Treat HTTP 404 or "remote ref does not exist" as success — GitHub's `auto-delete-head-branches` repo setting commonly removes the remote branch immediately on merge. If the error is anything else, report it.

### Step 8 — Report

Print a clear summary of which artifacts were removed and which were already gone:

```
Cleanup complete for PR #<number> (<headRefName>):
  ✓ Worktree removed: <path>        (or: no worktree found — skipped)
  ✓ Local branch deleted: <branch>  (or: already gone)
  ✓ Remote branch deleted: <branch> (or: already gone)
```

## Failure Mode Table

| Failure | Signal | Action |
|---------|--------|--------|
| PR not yet merged | `state != "MERGED"` or `mergedAt == null` | Abort. Print PR state and URL. Do not delete anything. |
| Uncommitted changes in worktree | `git status --porcelain` non-empty | Abort. Print the dirty files. Tell user to stash or commit first. |
| Unpushed commits in worktree | `git log @{upstream}..HEAD` non-empty | Abort. List the unpushed commits. Tell user to push or discard first. |
| cwd is inside the worktree | Path comparison | `cd` to main repo root before removal, or abort with a clear message if `cd` is not possible. |
| `git worktree remove` fails | Non-zero exit | Abort. Do not delete branches. Report the error verbatim. |
| No matching worktree found | `git worktree list --porcelain` has no entry | Skip Steps 4–5. Proceed to Step 6 (local branch deletion). |
| Remote branch already gone | HTTP 404 / "remote ref does not exist" | Treat as success. Report "already gone". |
| PR number not derivable from current branch | `gh pr view` fails on current branch | Ask the user for the PR number explicitly. |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Use `git branch --merged` to check if a PR is merged | Never. It lies after squash-merges (GitHub's default). Use `gh pr view --json state,mergedAt`. |
| Use lowercase `git branch -d` | Always use `git branch -D` (capital D). Squash-merged branches are not merge ancestors of `main`. |
| Force-delete a worktree with dirty state | Never. The safety checks in Step 4 exist to prevent data loss. |
| Run cleanup from inside the worktree being deleted | Always `cd` to the main repo root first (Step 4, Check 3). |
| Auto-trigger cleanup on merge | Never. Cleanup is user-initiated or explicitly orchestrated. No Stop hooks. |
| Treat remote-404 as an error | It is success — `auto-delete-head-branches` already removed it. |
