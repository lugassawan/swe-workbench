---
name: workflow-pr-review
description: Use when reviewing a remote GitHub PR — fetches into an ephemeral worktree, runs the reviewer agent with a Review Decision footer instruction, deduplicates findings against existing review threads (±5-line fuzzy match + Jaccard ≥ 0.4 against any author), posts new inline comments via gh-api, adds 👍 reactions on dedup matches, and submits the review with APPROVE or COMMENT. Counterpart of local-diff review (which workflow-development Phase 4 keeps using).
orchestrator: true
---

# Workflow: PR Review (remote-PR orchestration shell)

**Announce at start:** "I'm using the workflow-pr-review skill to review PR #N."

## When to invoke

- The user passes a PR number to `/swe-workbench:review` (e.g. `/swe-workbench:review 123`).
- The user accepts the auto-detect prompt on `/swe-workbench:review` no-arg ("Detected PR #N — review it? Reply `yes`").
- An agent or command needs to "review this remote PR end-to-end" — fetch + analyse + post + submit.
- Phrases: "review PR 123", "do a peer review of #456", "fetch this PR and post deduped comments".

## When NOT to invoke

- Local-diff review (working tree / staged / branch diff) → use `commands/review.md` no-arg directly. The command stays the entrypoint for local-diff mode.
- `workflow-development` Phase 4 → keeps using local-diff review (no remote PR exists yet during implementation).
- The user wants to post a single comment without running a full review → out of scope.
- The PR is closed/merged → out of scope; reviews target open PRs.

## Composition

This skill orchestrates; analysis is delegated to:
- `swe-workbench:reviewer` subagent — produces `Severity | File:Line | Issue | Why | Fix` findings + a Review Decision footer (when instructed by this skill — see Step 4).
- `swe-workbench:ticket-context` skill — prepended to the reviewer prompt when the PR body or commit messages reference a ticket key, atlassian/Confluence URL, or `#NNN` GitHub ref.
- `swe-workbench:workflow-pr-review-post` skill — the shared posting core (Step 6): dedup, inline/PR-level posting, self-review gate + diff-scoping flip, submit, CTA, its own state reap.
- **Checkpoint:** write the workflow state file (see `docs/workflow-state.md`) at each step boundary, carrying `$PR`/`$BASE`/`$HEAD_SHA`/`$DECISION` in `context`. Also populate `context.worktree_root` with `git rev-parse --show-toplevel`; omit it when working in the main checkout. This lets the resume hook emit a re-anchor nudge on compaction. Delete the state file after Step 7.

## 7-step flow

### Step 1 — Pre-flight

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
[ -f "$_RT/runtime/clean-state-files.sh" ] || {
  echo "swe-workbench runtime scripts not found under $_RT/runtime — set CLAUDE_PLUGIN_ROOT and retry." >&2
  exit 1
}
JSON="/tmp/swe-workbench-pr-review/${PR}.json"
eval "$("$_RT/runtime/preflight-pr.sh" "$PR" "$JSON")"
CURRENT_USER=$(gh api /user -q .login)
```

`preflight-pr.sh` handles `gh auth status`, fetches the PR JSON to `$JSON`, and emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as shell assignments. `title`/`body` stay in `$JSON` — read them with `jq` when needed (Step 3 ticket-context).

### Step 2 — Ephemeral worktree

**When rimba is available** (preferred — handles cross-fork remotes automatically and skips dep installation):

```bash
RIMBA_OUT=$(rimba add pr:$PR --task "pr-review-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

**When rimba is absent** (fallback — direct git, NOT `superpowers:using-git-worktrees` which is consent-gated for durable feature work):

```bash
WT="/tmp/swe-workbench-pr-review/${PR}"
if [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || bash "$_RT/runtime/clean-ephemeral.sh" "$WT" 2>/dev/null
fi
mkdir -p "$(dirname "$WT")"
git fetch origin "pull/${PR}/head:pr-review-${PR}" --force
git worktree add --detach "$WT" "pr-review-${PR}"
```

### Step 3 — Ticket-context chain

Read `title` and `body` from the saved JSON. Match `[A-Z]+-\d+`, atlassian/Confluence URLs, or `#\d+`/PR refs in either field plus the last 5 commit messages (`git -C "$WT" log --oneline -5`). If matched, invoke `swe-workbench:ticket-context` and capture its summary as a prelude to the reviewer prompt.

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
- `BYLINE` — `_Reviewed by \`reviewer\`_` (identity-only — the core appends the swe-workbench remark itself, conditionally on public repos; see `skills/workflow-pr-review-post/SKILL.md` Step 4).
- `CALLER_TAG` — `general` (scopes the core's own threads-cache filename so it never collides with a concurrent followup or specialist run on the same PR).
- `FINDINGS[]` — as parsed above.

The core owns thread fetch + dedup, inline/PR-level posting, the self-review gate + diff-scoping flip, submit, the address-feedback CTA, and its own state reap. See `skills/workflow-pr-review-post/SKILL.md` for the full contract, dedup algorithm, and failure modes.

### Step 7 — Cleanup

Foreground state-file reap for this skill's own preflight state (the core reaps its own separately) — runs immediately after Step 6 returns; failures surface (no `2>/dev/null` or `|| true`):

```bash
bash "$_RT/runtime/clean-state-files.sh" "/tmp/swe-workbench-pr-review/${PR}.json"
[ -e "/tmp/swe-workbench-pr-review/${PR}.json" ] \
  && echo "⚠ state file NOT reaped: /tmp/swe-workbench-pr-review/${PR}.json" >&2 \
  || echo "✓ state file reaped: /tmp/swe-workbench-pr-review/${PR}.json"
```

Worktree teardown stays backgrounded (slow); it no longer carries state-file cleanup:

```bash
( rimba remove "pr-review-$PR" --force 2>/dev/null \
  || { git worktree remove --force "$WT" 2>/dev/null; \
       git branch -D "pr-review-$PR" 2>/dev/null; \
       bash "$_RT/runtime/clean-ephemeral.sh" "$WT" 2>/dev/null; } ) &
```

Delete the workflow-state checkpoint file (see `docs/workflow-state.md`) now that the flow has reached its terminal step.

## Footer parsing contract

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
| PR not open / 404 | `gh pr view` fails | Abort. Print PR URL if known. |
| `git fetch pull/N/head` fails | Non-zero exit | Abort. Do not create worktree. |
| Reviewer aborts mid-scan | Agent error | Skip submit. **Leave worktree** for inspection (do not remove). |
| Decision footer missing or malformed | Regex no-match | Abort with explicit message. Worktree preserved. |

See `skills/workflow-pr-review-post/SKILL.md` § Failure modes for posting/dedup/submit failures (422s, stale SHA, pagination).

## Common mistakes

| Mistake | Fix |
|---|---|
| Use `superpowers:using-git-worktrees` for the PR worktree | That skill is consent-gated and durable-feature-oriented. Use `rimba add pr:$PR --task "pr-review-$PR" --skip-deps --skip-hooks` when rimba is available; direct `git worktree add` otherwise. |
| Forget repo-relative-path instruction | GitHub comment positioning requires repo-relative paths. The agent will emit `$WT/...` paths otherwise — comments won't anchor. |
| Skip the footer instruction | Without it, the agent does NOT emit the footer (per its `## Decision footer (when instructed)` block). Step 5 will then abort. |
| Block on cleanup | Cleanup runs in background `(... ) &`. Don't `wait` for it. |
| Reuse the core's own dedup/CTA/flip logic inline instead of invoking it | Duplicating that mechanism here is exactly the drift this skill was split to remove — always delegate Step 6 to `swe-workbench:workflow-pr-review-post`. |
