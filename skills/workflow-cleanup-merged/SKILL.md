---
name: workflow-cleanup-merged
description: Use after a PR has been merged on GitHub to remove the local worktree, delete the local branch, delete the remote branch, and fast-forward local main — safely, with squash-merge support.
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

### Batch A — Locate Worktree + Safety Checks

Combine the worktree locate and both git safety checks into one shell. Emit exactly three fields:

```bash
WORKTREE=$(git worktree list --porcelain \
  | awk '/^worktree /{p=$2} /^branch refs\/heads\/<headRefName>$/{print p; exit}')
DIRTY=$([ -n "$WORKTREE" ] && git -C "$WORKTREE" status --porcelain | wc -l | tr -d ' ' || echo 0)
UNPUSHED=$([ -n "$WORKTREE" ] && git -C "$WORKTREE" log @{upstream}..HEAD --oneline | wc -l | tr -d ' ' || echo 0)
printf 'WORKTREE=%s\nDIRTY=%s\nUNPUSHED=%s\n' "$WORKTREE" "$DIRTY" "$UNPUSHED"
```

- `WORKTREE`: matching worktree path, or empty if none (skip Batch B when empty).
- `DIRTY`: count of uncommitted-change lines. Must be 0; if not, abort — re-run `git -C "$WORKTREE" status --porcelain` to show files.
- `UNPUSHED`: count of unpushed commits. Must be 0; if not, abort — re-run `git -C "$WORKTREE" log @{upstream}..HEAD` to list them.

### [Optional] cwd-fix

If `cwd` is a subdirectory of `$WORKTREE`, cd to the main repo root before removal:
```
cd "$(git rev-parse --show-toplevel)"
```

### Batch B — Remove Worktree + Delete Local Branch

Only run if `WORKTREE` is non-empty. Both commands share abort-on-fail semantics; `&&` preserves that:

```bash
git worktree remove "$WORKTREE" && git branch -D <headRefName>
```

No `--force`. If `git worktree remove` fails, the `&&` prevents `git branch -D` from running — abort and report the error verbatim.

Capital `-D` is required: squash-merged branches are not merge ancestors of `main`; lowercase `-d` would refuse.

### Step 9 — Delete Remote Branch

```
git push origin --delete <headRefName>
```

Treat HTTP 404 or "remote ref does not exist" as success — GitHub's `auto-delete-head-branches` repo setting commonly removes the remote branch on merge. Any other error: report it.

### Batch C — Sync Local Main (Best-Effort)

Both commands share best-effort semantics; `||` prevents abort while `&&` ensures pull runs only after a clean checkout:

```bash
(git checkout main && git pull --ff-only origin main) \
  || echo "sync-main: best-effort failed — reconcile main manually"
```

`--ff-only` is non-negotiable; plain `git pull` can synthesize a merge commit on divergence.

### Step — Report

```
Cleanup complete for PR #<number> (<headRefName>):
  ✓ Worktree removed: <path>        (or: no worktree found — skipped)
  ✓ Local branch deleted: <branch>  (or: already gone)
  ✓ Remote branch deleted: <branch> (or: already gone)
  ✓ Local main synced to origin/main (or: ⚠ sync skipped — <reason>)
```

## Failure Mode Table

| Failure | Signal | Action |
|---------|--------|--------|
| PR not yet merged | `state != "MERGED"` or `mergedAt == null` | Abort. Print PR state and URL. Do not delete anything. |
| Uncommitted changes in worktree | `DIRTY > 0` | Abort. Re-run `git status --porcelain` to show files. Tell user to stash or commit first. |
| Unpushed commits in worktree | `UNPUSHED > 0` | Abort. Re-run `git log @{upstream}..HEAD` to list commits. Tell user to push or discard first. |
| cwd is inside the worktree | Path comparison | `cd` to main repo root before Batch B, or abort if not possible. |
| `git worktree remove` fails | Batch B `&&` short-circuits | Abort. Do not delete branches. Report verbatim. |
| No matching worktree found | `WORKTREE` empty | Skip Batch B. Proceed to Step 9 (local branch deletion). |
| Remote branch already gone | HTTP 404 / "remote ref does not exist" | Treat as success. Report "already gone". |
| Batch C fails | Non-zero exit from `git checkout` or `git pull` | Warn in report. Do not abort — deletions already succeeded. |
| PR number not derivable from current branch | `gh pr view` fails | Ask the user for the PR number explicitly. |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Use `git branch --merged` to check if a PR is merged | Never. Squash-merges lie. Use `gh pr view --json state,mergedAt`. |
| Use lowercase `git branch -d` | Always use `-D`. Squash-merged branches are not merge ancestors of `main`. |
| Force-delete a worktree with dirty state | Never. Batch A aborts before Batch B runs. |
| Run cleanup from inside the worktree being deleted | Always cd to the main repo root first (cwd-fix step). |
| Auto-trigger cleanup on merge | Never. Cleanup is user-initiated or explicitly orchestrated. No Stop hooks. |
| Treat remote-404 as an error | It is success — `auto-delete-head-branches` already removed it. |
| Use plain `git pull origin main` for the sync | Always `--ff-only`. Plain pull can synthesize a merge commit. |
