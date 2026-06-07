---
description: Help the PR owner address review feedback — fetches open threads, presents a per-thread triage (ADDRESSED / CLARIFIED / DEFERRED), applies fixes, commits, posts per-thread replies, and resolves addressed threads.
argument-hint: "<PR number>"
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
## Step 1 — Parse arguments

Parse `$ARGUMENTS`:

- Matches `[1-9][0-9]*` (stripping a leading `#` if present) → use as `$PR`.
- If empty, run `gh pr view --json number 2>/dev/null`. If it succeeds, offer:
  > "Detected PR #N on this branch — address feedback on it? Reply `yes` to proceed."
  Wait for reply. `yes` → use that PR number. Else → print "No PR number provided." and stop.
- If non-numeric and no PR detected → print usage hint and stop.

## Step 2 — Ticket context (when a ref is present)

Inspect `$ARGUMENTS` plus `git rev-parse --abbrev-ref HEAD` and `git log --oneline -5` for ticket keys (`[A-Z]+-\d+`), `atlassian.net` URLs, Confluence wiki URLs, or `#NNN` GitHub refs. If matched, invoke `swe-workbench:ticket-context` and prepend its structured summary to the delegation context in Step 3.

## Step 3 — Invoke workflow skill

Invoke `swe-workbench:workflow-address-feedback` with the resolved PR number and any ticket-context prelude from Step 2.

The skill owns: pre-flight (`gh auth`, `gh pr view`), owner-identity check, worktree setup via `rimba add pr:$PR --task "address-feedback-$PR"` (cleaned up on exit via Phase 6), thread fetch via GraphQL `reviewThreads`, per-thread A/C/D triage, Edit-tool fix application, `swe-workbench:workflow-commit-and-pr` for committing, REST reply posting, and GraphQL `resolveReviewThread` for resolved threads.
