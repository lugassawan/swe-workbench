---
name: workflow-pr-review-followup
description: Use when a reviewer wants to re-check a PR after the owner has addressed feedback — re-runs the reviewer agent against the updated diff, deduplicates against existing threads (Jaccard ±5-line), posts only truly-new inline comments, and submits an APPROVE or COMMENT review event.
orchestrator: true
---

# Workflow: PR Review Follow-up

**Announce at start:** "I'm using the workflow-pr-review-followup skill to re-check PR #N."

## When to invoke

- The user runs `/swe-workbench:review --check-followup <N>`.
- A reviewer has already posted a full review and wants to verify that their findings were addressed.
- Phrases: "re-check PR 123", "check if my review comments were addressed", "follow up on review #456".

## When NOT to invoke

- Full first-pass review → use `swe-workbench:workflow-pr-review` instead.
- The PR is closed/merged → out of scope.

## Composition

This skill orchestrates; analysis is delegated to:

- `swe-workbench:reviewer` subagent — produces `Severity | File:Line | Issue | Why | Fix` findings + a Review Decision footer.
- `swe-workbench:ticket-context` skill — prepended when PR references a ticket key.
- `swe-workbench:workflow-pr-review-post` skill — the shared posting core (Step 6): dedup, inline/PR-level posting, self-review gate + diff-scoping flip, submit, CTA, its own state reap.

## 7-step flow

### Step 1 — Pre-flight

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
[ -f "$_RT/runtime/clean-state-files.sh" ] || {
  echo "swe-workbench runtime scripts not found under $_RT/runtime — set CLAUDE_PLUGIN_ROOT and retry." >&2
  exit 1
}
JSON="/tmp/swe-workbench-pr-review/${PR}-followup.json"
eval "$("$_RT/runtime/preflight-pr.sh" "$PR" "$JSON")"
CURRENT_USER=$(gh api /user -q .login)
```

`preflight-pr.sh` handles `gh auth status`, fetches the PR JSON to `$JSON` (stored under `${PR}-followup.json` — distinct from `${PR}.json` used by the primary review to allow both to coexist), and emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as shell assignments.

Check that the PR is open before proceeding:
```bash
[ "$STATE" = "OPEN" ] || { echo "PR #$PR is $STATE — follow-up review only applies to open PRs."; exit 1; }
```

### Step 2 — Ephemeral worktree

**When rimba is available** (preferred — handles cross-fork remotes automatically and skips dep installation):

```bash
RIMBA_OUT=$(rimba add pr:$PR --task "pr-followup-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

**When rimba is absent** (fallback — direct git, NOT `superpowers:using-git-worktrees` which is consent-gated for durable feature work):

```bash
WT="/tmp/swe-workbench-pr-review/${PR}-followup"
if [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || bash "$_RT/runtime/clean-ephemeral.sh" "$WT" 2>/dev/null
fi
mkdir -p "$(dirname "$WT")"
git fetch origin "pull/${PR}/head:pr-followup-${PR}" --force
git worktree add --detach "$WT" "pr-followup-${PR}"
```

### Step 3 — Ticket-context chain

Identical to `workflow-pr-review` Step 3. Read `title` and `body` from the saved JSON. Match `[A-Z]+-\d+`, atlassian/Confluence URLs, or `#\d+`/PR refs in either field plus the last 5 commit messages. If matched, invoke `swe-workbench:ticket-context` and capture its summary as a prelude.

### Step 4 — Invoke `reviewer`

Pass the agent:
- Working-directory hint: absolute path of the worktree (`$WT`).
- Before diffing, refresh the remote base so already-merged commits are excluded (best-effort — a fetch failure is non-fatal): `git -C "$WT" fetch origin "$BASE" --quiet || true`
- Diff: `git -C "$WT" diff "origin/$BASE"...HEAD` (three-dot = merge-base; only commits unique to the PR branch).
- Repo-relative-path instruction (load-bearing): emit **repo-relative** paths (e.g. `src/foo.ts:42`, NOT `$WT/src/foo.ts:42`). The orchestrator uses these paths to position GitHub comments.
- Footer instruction (opt-in per `## Decision footer`): end with EXACTLY ONE of `**Review Decision: APPROVE**` or `**Review Decision: COMMENT**`. Never `REQUEST_CHANGES`.
- Blocking-scope instruction (opt-in per `## Blocking-scope verdict`): classify each Critical/High as in-diff (`+` lines) or out-of-diff; mark out-of-diff with `**Informational (out-of-diff):** `; emit `**Blocking Scope: NONE|OUT-OF-DIFF-ONLY|IN-DIFF**` before the footer. APPROVE/COMMENT rule unchanged.
- Ticket-context prelude (if Step 3 produced one).

### Step 5 — Parse decision footer + blocking-scope verdict

Scan ALL non-blank lines for the footer pattern:

```
^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$
```

Abort with "reviewer agent did not emit a valid Review Decision footer (APPROVE|COMMENT). Refusing to submit." if ANY of:
- Zero matches found.
- More than one matching line found.
- `REQUEST_CHANGES` appears anywhere in the agent output.

Do NOT clean up the worktree on abort — leave it for inspection.

Also scan for `^\*\*Blocking Scope:\s+(NONE|OUT-OF-DIFF-ONLY|IN-DIFF)\*\*$`; parse into `$BLOCKING_SCOPE`. Zero or >1 matches → `BLOCKING_SCOPE=IN-DIFF` (fail-safe). Log warning; do **not** abort — footer is the only hard-required contract.

### Step 6 — Invoke the posting core

Parse Step 4's `reviewer` output into `FINDINGS[]` rows (`severity`, `path`, `line`, `body`); anchor `inline` when the line is in-diff, `pr-level` otherwise (per the reviewer's own out-of-diff informational marker). Invoke `swe-workbench:workflow-pr-review-post` with:

- `PR`, `OWNER`, `REPO`, `HEAD_SHA`, `BASE`, `CURRENT_USER`, `AUTHOR_LOGIN` — from Step 1.
- `DECISION`, `BLOCKING_SCOPE` — parsed in Step 5.
- `BYLINE` — `_Re-reviewed by \`reviewer\`_` (identity-only — the core appends the swe-workbench remark itself, conditionally on public repos; see `skills/workflow-pr-review-post/SKILL.md` Step 4).
- `CALLER_TAG` — `followup` (scopes the core's own threads-cache filename so it never collides with a concurrent primary or specialist run on the same PR).
- `FINDINGS[]` — as parsed above.

The core owns thread fetch + dedup, inline/PR-level posting, the self-review gate + diff-scoping flip, submit, the address-feedback CTA, and its own state reap. See `skills/workflow-pr-review-post/SKILL.md` for the full contract, dedup algorithm, and failure modes.

### Step 7 — Cleanup

Foreground state-file reap for this skill's own preflight state (the core reaps its own separately) — runs immediately after Step 6 returns; failures surface (no `2>/dev/null` or `|| true`):

```bash
bash "$_RT/runtime/clean-state-files.sh" "/tmp/swe-workbench-pr-review/${PR}-followup.json"
[ -e "/tmp/swe-workbench-pr-review/${PR}-followup.json" ] \
  && echo "⚠ state file NOT reaped: /tmp/swe-workbench-pr-review/${PR}-followup.json" >&2 \
  || echo "✓ state file reaped: /tmp/swe-workbench-pr-review/${PR}-followup.json"
```

Worktree teardown stays backgrounded (slow); it no longer carries state-file cleanup:

```bash
( rimba remove "pr-followup-$PR" --force 2>/dev/null \
  || { git worktree remove --force "$WT" 2>/dev/null; \
       git branch -D "pr-followup-$PR" 2>/dev/null; \
       bash "$_RT/runtime/clean-ephemeral.sh" "$WT" 2>/dev/null; } ) &
```

## Footer parsing contract

Identical to `workflow-pr-review`:
- Regex: `^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$`
- Source: scan ALL non-blank lines of agent output.
- Abort cases (do NOT submit, preserve worktree):
  - Zero matches.
  - More than one matching line.
  - `REQUEST_CHANGES` appears anywhere in the agent output.

Dedup algorithm, diff-scoping flip contract, and posting failure modes now live entirely in `skills/workflow-pr-review-post/SKILL.md` — this skill hands off decision + findings and does not duplicate that mechanism.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth status` fails | Non-zero exit | Abort. Print fix hint. |
| PR not open / 404 | `gh pr view` fails | Abort. |
| `git fetch pull/N/head` fails | Non-zero exit | Abort. Do not create worktree. |
| Reviewer aborts mid-scan | Agent error | Skip submit. **Leave worktree** for inspection. |
| Decision footer missing or malformed | Regex no-match | Abort with explicit message. Worktree preserved. |

See `skills/workflow-pr-review-post/SKILL.md` § Failure modes for posting/dedup/submit failures (422s, stale SHA, pagination).

## Common mistakes

| Mistake | Fix |
|---|---|
| Use `--task "pr-review-$PR"` for the worktree | Use `--task "pr-followup-$PR"` to avoid colliding with a still-active primary-review worktree. |
| Omit the footer instruction in Step 4 | Without it, the agent does NOT emit the footer. Step 5 will then abort. |
| Forget repo-relative-path instruction | GitHub comment positioning requires repo-relative paths. The agent will emit `$WT/...` paths otherwise. |
| Reuse the core's own dedup/CTA/flip logic inline instead of invoking it | Duplicating that mechanism here is exactly the drift this skill was split to remove — always delegate Step 6 to `swe-workbench:workflow-pr-review-post`. |
