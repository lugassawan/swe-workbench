---
name: workflow-address-feedback
description: Use when a PR owner wants to address review feedback — fetches outstanding threads, presents a per-thread triage (ADDRESSED / CLARIFIED / DEFERRED), applies fixes via the Edit tool, commits via workflow-commit-and-pr, posts per-thread replies via the GitHub comments API, and resolves addressed threads via GraphQL resolveReviewThread.
orchestrator: true
---

# Workflow: Address Feedback

**Announce at start:** "I'm using the workflow-address-feedback skill to address review feedback on PR #N."

## When to invoke

- The user runs `/swe-workbench:address-feedback <N>`.
- A PR owner wants to systematically work through review threads.
- Phrases: "address the feedback on PR 123", "help me resolve review comments", "triage and fix the review threads on #456".

## When NOT to invoke

- The reviewer side of the loop → use `swe-workbench:workflow-pr-review` or `swe-workbench:workflow-pr-review-followup`.
- The user just wants to reply to a single comment without the full triage flow.
- The PR is closed/merged.

## Composition

This skill orchestrates:
- `swe-workbench:ticket-context` — prepended context when PR references a ticket.
- `swe-workbench:workflow-commit-and-pr` — invoked after all ADDRESSED fixes are applied to commit and push.

## 5-phase flow

### Phase 1 — Pre-flight + fetch

```bash
gh auth status >/dev/null || { echo "gh not authenticated. Run 'gh auth login'."; exit 1; }
CURRENT_USER=$(gh api /user -q .login)
mkdir -p /tmp/swe-workbench-address-feedback
gh pr view "$PR" --json number,title,body,headRefName,baseRefName,author,reviewDecision,headRepository,state \
  > "/tmp/swe-workbench-address-feedback/${PR}.json"
[ -s "/tmp/swe-workbench-address-feedback/${PR}.json" ] || { echo "PR #$PR not found or not accessible."; exit 1; }
```

Extract fields from the JSON:
- `AUTHOR_LOGIN` from `author.login`
- `OWNER` from `headRepository.nameWithOwner | split("/")[0]`
- `REPO` from `headRepository.name`
- `STATE` from `state`

Check that the PR is open before proceeding:
```bash
STATE=$(jq -r .state "/tmp/swe-workbench-address-feedback/${PR}.json")
[ "$STATE" = "OPEN" ] || { echo "PR #$PR is $STATE — address-feedback only applies to open PRs."; exit 1; }
```

If `CURRENT_USER != AUTHOR_LOGIN`, warn:
> "You are not the PR author (PR author: @AUTHOR_LOGIN, you: @CURRENT_USER). Address-feedback flows are typically owner-side. Continue anyway? Reply `yes` to proceed."

Wait for confirmation before continuing.

Fetch outstanding review threads via GraphQL:

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
  }' > "/tmp/swe-workbench-address-feedback/${PR}-threads.json"
```

If all threads are resolved (or no threads exist), print:
> "No open threads — nothing to address."
Then exit cleanly.

If a prior triage save exists at `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, offer to resume from it.

### Phase 2 — Worktree

**When rimba is available** (preferred — durable, owner commits land here):

```bash
PR_BRANCH=$(jq -r .headRefName "/tmp/swe-workbench-address-feedback/${PR}.json")
RIMBA_OUT=$(rimba add "$PR_BRANCH" --task "address-feedback-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

**When rimba is absent** (durable fallback):

```bash
PR_BRANCH=$(jq -r .headRefName "/tmp/swe-workbench-address-feedback/${PR}.json")
WT="$HOME/.local/share/swe-workbench/address-feedback-${PR}"
mkdir -p "$(dirname "$WT")"
git fetch origin "${PR_BRANCH}"
git worktree add "$WT" "${PR_BRANCH}"
```

**This is a durable worktree** — no auto-cleanup. The owner's commits persist here until merged. After merge, run `swe-workbench:workflow-cleanup-merged` to remove it.

### Phase 3 — Triage digest

Render outstanding unresolved threads, one by one. Skip any thread where `isResolved == true` — only present threads where `isResolved == false`. For each remaining thread:

```
─────────────────────────────────────────────────
Thread #ID — {path}:{line}  by @{author}  [{Severity if parseable}]
─────────────────────────────────────────────────
> {first 200 chars of comment body}

[A]ddressed — fix + commit + reply + resolve
[C]larified — reply only (no resolve)
[D]eferred — skip this thread
[Q]uit — save progress and exit
```

Parse severity from `Severity: <level>` prefix in comment body if present; otherwise label `Unknown`.

Capture: `triage[<thread_id>] = A|C|D`.

If the owner replies `Q`, save triage state to `/tmp/swe-workbench-address-feedback/${PR}-triage.json` and exit. Re-invocation resumes from this file.

### Phase 4 — Implement + commit

For each `ADDRESSED` thread (in order):

1. Show the finding and the relevant file/line context.
2. Ask the owner for the fix approach (free-text). If the comment already contains a `### Suggested fix` block, offer to apply it automatically via the Edit tool.
3. Apply edits using the Edit tool.

After all `ADDRESSED` fixes are applied, invoke `swe-workbench:workflow-commit-and-pr` with the prompt:
> "commit and push these fixes addressing review feedback on PR #N"

This reuses the existing `[type]` commit format, branch-naming check, and push logic. After the skill returns, capture the resulting commit SHA:

```bash
FIX_SHA=$(git -C "$WT" rev-parse HEAD)
```

### Phase 5 — Reply + resolve

For each thread, post a reply via REST then conditionally resolve. Use `comments.nodes[0].databaseId` (the thread root comment) as `$COMMENT_DATABASEID` — replies must target the first comment in the thread, not a subsequent reply.

```bash
# Post reply
gh api "repos/${OWNER}/${REPO}/pulls/${PR}/comments/${COMMENT_DATABASEID}/replies" \
  -F body="$REPLY_BODY"
```

Reply body templates by triage classification:
- **ADDRESSED**: `"Addressed in ${FIX_SHA}: <one-line summary of fix>."`
- **CLARIFIED**: free-text owner-authored reply (asked interactively). No resolve.
- **DEFERRED**: no reply posted, no resolve.

For each `ADDRESSED` thread, resolve via GraphQL after the reply succeeds:

```bash
gh api graphql -F threadId="$THREAD_ID" -f query='
  mutation($threadId: ID!) {
    resolveReviewThread(input: {threadId: $threadId}) {
      thread { id isResolved }
    }
  }'
```

After all replies and resolutions land, emit the follow-up CTA:

> "Want me to ping the reviewer to re-check? Reply `yes` to run `/review --check-followup <N>`."

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth` fails | Non-zero exit | Abort. |
| PR not found | `gh pr view` fails | Abort. |
| `CURRENT_USER != AUTHOR_LOGIN` | JSON mismatch | Warn + ask to continue. |
| No outstanding threads | GraphQL returns 0 unresolved | Print "No open threads — nothing to address." Exit. |
| Owner picks Q mid-triage | Loop exit | Save triage state to `/tmp/swe-workbench-address-feedback/${PR}-triage.json`. Exit cleanly. |
| Reply REST fails (404 — comment deleted) | HTTP 404 | Skip that thread, log "skipped (comment deleted)". |
| Resolve mutation fails | GraphQL error | Reply already posted — log "reply posted but resolve failed". Continue. Do not roll back the reply. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Omit `--skip-deps --skip-hooks` on the rimba call | Always pass both flags — same as other worktree-creating skills. Deps can be installed manually in the worktree if needed. |
| Auto-cleanup the worktree after Phase 5 | This is a durable worktree — commits land here. Clean up post-merge via `swe-workbench:workflow-cleanup-merged`. |
| Post the reply before the commit | Always commit first (Phase 4) so `$FIX_SHA` is available for the ADDRESSED reply template. |
| Resolve a CLARIFIED thread | Only resolve ADDRESSED threads. CLARIFIED = reply only, no resolve. |
| Try to resolve via REST | Thread resolution is GraphQL-only (`resolveReviewThread` mutation). REST has no equivalent endpoint. |
