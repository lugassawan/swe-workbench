---
name: workflow-pr-review-followup
description: Use when a reviewer wants to re-check a PR after the owner has addressed feedback — re-runs the reviewer agent against the updated diff, deduplicates against existing threads (Jaccard ±5-line), and reports a digest to the reviewer without posting any new comments or submitting a review event.
orchestrator: true
---

# Workflow: PR Review Follow-up

**Announce at start:** "I'm using the workflow-pr-review-followup skill to check PR #N for new findings."

## When to invoke

- The user runs `/swe-workbench:review --check-followup <N>`.
- A reviewer has already posted a full review and wants to verify that their findings were addressed.
- Phrases: "re-check PR 123", "check if my review comments were addressed", "follow up on review #456".

## When NOT to invoke

- Full first-pass review → use `swe-workbench:workflow-pr-review` instead.
- The user wants to post new inline comments → use `swe-workbench:workflow-pr-review` instead.
- The PR is closed/merged → out of scope.

## Composition

This skill orchestrates; analysis is delegated to:

- `swe-workbench:reviewer` subagent — produces `Severity | File:Line | Issue | Why | Fix` findings.
- `swe-workbench:ticket-context` skill — prepended when PR references a ticket key.

**Never** calls `gh pr review --approve` or `gh pr review --comment`. **Never** posts inline comments. This skill is read-only with respect to GitHub — it reports findings to the reviewer in the conversation only.

## 7-step flow

### Step 1 — Pre-flight

```bash
gh auth status >/dev/null || { echo "gh not authenticated. Run 'gh auth login'."; exit 1; }
CURRENT_USER=$(gh api /user -q .login)
mkdir -p /tmp/swe-workbench-pr-review
gh pr view "$PR" --json state,number,headRefName,baseRefName,headRepository,headRefOid,title,body \
  > "/tmp/swe-workbench-pr-review/${PR}-followup.json"
[ -s "/tmp/swe-workbench-pr-review/${PR}-followup.json" ] || { echo "PR #$PR not found or not accessible."; exit 1; }
```

Extract `BASE`, `HEAD_SHA`, `OWNER`, `REPO` from the JSON. The state file is stored under `${PR}-followup.json` (distinct from `${PR}.json` used by the primary review) to allow both to coexist.

Check that the PR is open before proceeding:
```bash
STATE=$(jq -r .state "/tmp/swe-workbench-pr-review/${PR}-followup.json")
[ "$STATE" = "OPEN" ] || { echo "PR #$PR is $STATE — follow-up review only applies to open PRs."; exit 1; }
```

### Step 2 — Ephemeral worktree

**When rimba is available** (preferred):

```bash
RIMBA_OUT=$(rimba add pr:$PR --task "pr-followup-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

The task is named `pr-followup-$PR` (NOT `pr-review-$PR`) so cleanup of the primary-review worktree does not collide with this one.

**When rimba is absent** (fallback):

```bash
WT="/tmp/swe-workbench-pr-review/${PR}-followup"
if [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || rm -rf "$WT"
fi
mkdir -p "$(dirname "$WT")"
git fetch origin "pull/${PR}/head:pr-followup-${PR}" --force
git worktree add --detach "$WT" "pr-followup-${PR}"
```

### Step 3 — Ticket-context chain

Identical to `workflow-pr-review` Step 3. Read `title` and `body` from the saved JSON. Match `[A-Z]+-\d+`, atlassian/Confluence URLs, or `#\d+`/PR refs in either field plus the last 5 commit messages. If matched, invoke `swe-workbench:ticket-context` and capture its summary as a prelude.

### Step 4 — Invoke `reviewer`

Pass the `swe-workbench:reviewer` agent:
- Working-directory hint: absolute path of the worktree (`$WT`).
- Diff: `git -C "$WT" diff "$BASE"..HEAD`.
- Repo-relative-path instruction (load-bearing — strip the `$WT/` prefix before the colon):
  > "Emit **repo-relative** paths in every finding (e.g. `src/foo.ts:42`, NOT `$WT/src/foo.ts:42`)."
- **No footer instruction** — this skill does not submit a review, so the Decision footer is not needed and should NOT be requested.
- Narrative instruction:
  > "Begin the review with a `## Review Summary` section: 2–4 sentences capturing overall posture, the strongest positives, and the most important concerns."
- Ticket-context prelude (if Step 3 produced one).

Store the agent's complete text response as `REVIEWER_OUTPUT`.

### Step 5 — Parse findings

Parse `Severity | File:Line | Issue | Why | Fix` rows from `REVIEWER_OUTPUT`. Collect as a list of `(path, line, severity, issue, why, fix)` tuples. If no rows found, set `agent_findings = 0`, skip Step 6, and jump to Step 7 using the **Case A0** template.

### Step 6 — Dedup (report-only)

Fetch existing review threads via the same GraphQL query used in `workflow-pr-review` Step 6:

```bash
gh api graphql -F number="$PR" -F owner="$OWNER" -F repo="$REPO" -f query='
  query($owner: String!, $repo: String!, $number: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $number) {
        reviewThreads(first: 100) {
          nodes {
            id isResolved path line startLine
            comments(first: 10) {
              nodes {
                id databaseId body
                author { login }
              }
            }
          }
        }
      }
    }
  }' > "/tmp/swe-workbench-pr-review/${PR}-followup-threads.json"
```

**For each finding**, apply the dedup contract:
1. `T.path == finding.path` (exact, repo-relative).
2. `|T.line - finding.line| ≤ 5` (use `startLine` if non-null).
3. Jaccard overlap of word tokens between `T.comments[0].body` and `finding.body` ≥ 0.4.
4. `T.isResolved == false`.

Match against ANY author. Track:
- `truly_new` — findings with no dedup match.
- `deduped` — findings that matched an existing thread.

**Do NOT** post any inline comments. **Do NOT** add 👍 reactions. This step is read-only.

### Step 7 — Report digest (NOT submit)

**Never** call `gh pr review --approve`, `gh pr review --comment`, or any variant. This step renders a summary to the reviewer in the conversation only.

Choose the report template based on counts:

**Case A0 — Agent found no findings at all (clean diff):**
Use this when Step 5 exits early because the agent produced zero findings (before dedup runs).
```
## Follow-up Check: PR #N

Reviewer agent found no new findings in the updated diff. Previously raised threads remain as-is on GitHub.
```

**Case A — Dedup matched all findings (truly_new == 0 AND deduped > 0):**
```
## Follow-up Check: PR #N

No new findings since prior review. All {deduped} finding(s) previously raised are still open (unresolved threads exist).
```

**Case B — New findings present:**
```
## Follow-up Check: PR #N

{truly_new} new finding(s) since prior review; {deduped} previously raised.

### New Findings

| Severity | File:Line | Issue | Why | Fix |
|---|---|---|---|---|
{rows for truly_new findings}
```

After rendering the digest, clean up non-blocking:
```bash
( rimba remove "pr-followup-$PR" --force 2>/dev/null \
  || { git worktree remove --force "$WT" 2>/dev/null; \
       git branch -D "pr-followup-$PR" 2>/dev/null; \
       rm -rf "$WT" 2>/dev/null; } ) &
```

## Dedup contract

Identical to `workflow-pr-review`:
1. `T.path == finding.path` (exact, repo-relative).
2. `|T.line - finding.line| ≤ 5` (if `T.startLine` is null, use `T.line`; otherwise use `T.startLine`).
3. Jaccard overlap of word tokens between `T.comments[0].body` and `finding.body` ≥ 0.4.
4. `T.isResolved == false`.

Match against ANY author.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth status` fails | Non-zero exit | Abort. Print fix hint. |
| PR not open / 404 | `gh pr view` fails | Abort. |
| `git fetch pull/N/head` fails | Non-zero exit | Abort. Do not create worktree. |
| Reviewer aborts mid-scan | Agent error | Skip report. Leave worktree for inspection. |
| GraphQL pagination needed (PR > 100 threads) | `hasNextPage == true` | Document as known v1 limit. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Call `gh pr review --approve` or `gh pr review --comment` | **Never.** This is the key invariant of this skill — it is a read-only follow-up reporter, not a submitter. The primary review (`workflow-pr-review`) owns submission. |
| Use `--task "pr-review-$PR"` for the worktree | Use `--task "pr-followup-$PR"` to avoid colliding with a still-active primary-review worktree. |
| Add 👍 reactions in Step 6 | This skill is GitHub-read-only. No reactions, no comments, no review events. |
| Request the footer instruction in Step 4 | The footer (`**Review Decision: APPROVE|COMMENT**`) is only relevant when submitting. Don't request it here — the agent omits it anyway without the instruction. |
