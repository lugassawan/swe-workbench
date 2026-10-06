# PR context fetch reference

Read-only context the main thread gathers before `swe-workbench:senior-engineer` is
dispatched. senior-engineer has no Bash, so everything it needs about the PR's current
approach travels in the delegation prompt. Two parts: **gates** (run first, allocate
nothing) and **baseline** (run after `$RUN_DIR` exists).

## Part 1 — Gates

### Resolve the PR

`PR_ARG` must be empty or match `^#?[0-9]+$`. Anything else (a URL, a branch name) is
refused: the later steps run against the current checkout's repository, so a PR from
another repo must never pass the gates.

```bash
PR_ARG="${PR_ARG#\#}"   # a leading '#' on N is stripped
case "$PR_ARG" in *[!0-9]*) echo "redesign: PR number must be digits, got '$PR_ARG'." >&2; exit 1 ;; esac
FIELDS=number,state,isDraft,headRefName,baseRefName,isCrossRepository,author,title,body,url
PR_JSON=$(gh pr view ${PR_ARG:+"$PR_ARG"} --json "$FIELDS") \
  || { echo "redesign: could not read the PR — gh pr view failed (pass a PR number if the branch has none)." >&2; exit 1; }
PR=$(printf '%s' "$PR_JSON" | jq -r .number)
PR_BRANCH=$(printf '%s' "$PR_JSON" | jq -r .headRefName)
BASE_BRANCH=$(printf '%s' "$PR_JSON" | jq -r .baseRefName)
PR_URL=$(printf '%s' "$PR_JSON" | jq -r .url)
```

Use `$PR`, never `$PR_ARG`, from here on. Without `N`, the PR found for the current
branch is shown (`#N — title`) and the user must reply `yes` before anything else runs.
Any other reply stops the flow.

### State, fork and ownership gates

One executable block, so none of the checks can be skipped on their own. The PR must be
`OPEN` (drafts are allowed; `CLOSED` and `MERGED` stop the flow) and must not be a fork PR
(`isCrossRepository`): the head branch of a fork lives on the fork's remote, so `acquire`
would find nothing on `origin`. A missing field fails the check, like any other doubt.

```bash
printf '%s' "$PR_JSON" | jq -e '.state == "OPEN"' >/dev/null \
  || { echo "redesign: PR #$PR is not OPEN — nothing to redesign." >&2; exit 1; }
printf '%s' "$PR_JSON" | jq -e '.isCrossRepository == false' >/dev/null \
  || { echo "Fork PRs are not supported by /swe-workbench:design --pr yet — the head branch lives on the fork. Check the PR out by hand and use /swe-workbench:implement for a replacement." >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "redesign: gh is not authenticated — run 'gh auth login' first." >&2; exit 1; }
CURRENT_USER=$(gh api /user -q .login) || { echo "redesign: could not read the current gh user." >&2; exit 1; }
PR_AUTHOR=$(printf '%s' "$PR_JSON" | jq -r '.author.login // empty')
[ -n "$CURRENT_USER" ] && [ -n "$PR_AUTHOR" ] && [ "$PR_AUTHOR" = "$CURRENT_USER" ] || {
  echo "PR #$PR is authored by @$PR_AUTHOR; /swe-workbench:design --pr only runs on your own PRs. Use /swe-workbench:review $PR to review someone else's work." >&2
  exit 1
}
```

Refuse, do not warn, in both modes. Every failure (not open, fork, unauthenticated,
unreadable user, empty author, mismatch) refuses — the gate fails closed.

## Part 2 — Baseline for senior-engineer

Run after `$RUN_DIR` is allocated. Write into `$RUN_DIR` (never a literal `/tmp` path).
Every fetch is checked; an empty diff or file list aborts, so senior-engineer is never
asked to judge an approach it was not shown.

```bash
gh pr diff "$PR" > "$RUN_DIR/pr.diff" || { echo "redesign: could not fetch the PR diff." >&2; exit 1; }
gh pr diff "$PR" --name-only > "$RUN_DIR/pr.files" || { echo "redesign: could not fetch the PR file list." >&2; exit 1; }
gh pr view "$PR" --json files -q '.files[] | "\(.path) +\(.additions) -\(.deletions)"' > "$RUN_DIR/pr.stat" \
  || { echo "redesign: could not fetch the PR file stats." >&2; exit 1; }
[ -s "$RUN_DIR/pr.diff" ] && [ -s "$RUN_DIR/pr.files" ] || { echo "redesign: the PR diff is empty or unavailable (very large PRs can exceed the API limit)." >&2; exit 1; }
DIFF_LINES=$(wc -l < "$RUN_DIR/pr.diff")
```

**Size rule.** At or below 3000 diff lines, pass the full diff. Above that, pass
`pr.stat` plus `pr.files` and say so in the prompt: senior-engineer then works from the
file list, per-file sizes and the PR body.

**What senior-engineer can and cannot see.** It has Read, Grep and Glob, but any file it
reads is the current checkout, which is usually not the PR head. Tell it to treat the
passed diff as authoritative and not to cite files it read as if they were the PR's.

The prompt also carries the PR title and body, the user's "why", and any
`## Resolved decisions` block from grill mode.
