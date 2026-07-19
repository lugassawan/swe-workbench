---
name: workflow-hotfix
description: Branch-based P0 hotfix lifecycle — skips the worktree provider, ships a PR immediately after a minimal fix (ahead of verification and review, deferred by design), stamps a deferred-verification marker on the PR body, then reconciles it once a regression test lands and the suite is green again. Activated by /swe-workbench:hotfix.
orchestrator: true
---

# Workflow: Hotfix (branch-based, deferred verification)

**Announce at start:** "I'm using the workflow-hotfix skill to ship this as a fast branch-based hotfix."

## When to invoke

- `/swe-workbench:hotfix` command.
- A P0/incident fix where the PR must go up before verify/review complete.

## When NOT to invoke

- Non-urgent work → `/swe-workbench:implement` (worktree-isolated, verify-before-PR).
- Mid-PR follow-on → `/swe-workbench:extend`.
- Pure diagnosis with no urgency to ship → `/swe-workbench:debug`.

## Why the lifecycle is reordered

`workflow-development`'s Mode B hard-enforces verify → review → deliver so a broken change never
reaches a reviewer. A hotfix inverts the trade: the PR must exist *now* so reviewers, CI, and
stakeholders see it immediately; verification and review still happen, just after, against the
open PR. The deferred-verification marker on the PR body is what keeps that trade-off visible
instead of silently becoming permanent debt — `workflow-cleanup-merged` reads it at merge time and
offers a backfill follow-up.

## Phase 1 — Branch (forced, no worktree)

Never invoke the worktree provider (`rimba add` / `superpowers:using-git-worktrees`) — a hotfix
stays in the current checkout. If uncommitted changes are present (`git status --porcelain`),
stop and ask before switching branches.

```bash
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null \
  || git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' \
  || echo main)
git checkout "$DEFAULT_BRANCH" && git pull --ff-only origin "$DEFAULT_BRANCH"
git checkout -b "hotfix/<slug>"
```

Derive `<slug>` (kebab-case) from the ticket ref or a short symptom summary — same slugging as
rimba's own `<task>` normalization. `--ff-only` is non-negotiable (plain `pull` can synthesize a
merge commit on a stale local default branch).

## Phase 2 — Implement (TDD relaxed)

Apply the minimal fix via `superpowers:executing-plans` or direct edits for a single-file change.
TDD is intentionally **relaxed** here — no test-first; the regression test is the deferred work
this command's marker tracks. Escalate a genuine design fork to `senior-engineer` rather than
guessing (unchanged rule from `workflow-development`).

## Phase 3 — Deliver the PR first (reordered)

**Detect the commit/PR tag.** Read `.githooks/commit-msg` (or run `git log --oneline -20`) for the
host repo's allowed `[type]` set. Prefer, in order: `hotfix` → `bugfix` → `fix` — use the first one
the repo's convention actually allows. (In this repo the hook allows only
`feat|fix|refactor|test|ci|docs|perf|chore|polish|breaking`, so this resolves to `fix`.)

**Create the PR ready-for-review.** Invoke `swe-workbench:workflow-commit-and-pr` for the commit +
push + `gh pr create` mechanics unmodified — its own PR-template detection, `Closes #<N>` /
`Issue: N/A — urgent hotfix` substitution, and test-plan seeding all apply as-is. Answer its two
interactive gates automatically, without surfacing either to the user:

- **Draft vs ready:** always **Ready for review** — never Draft. A hotfix's entire identity is
  speed; a draft PR defeats the purpose.
- **Branch-rename offer** (fires because a freshly created `hotfix/<slug>` branch has no upstream
  yet, so the "already pushed" suggest-only bypass doesn't apply): always **Keep as-is** —
  `hotfix/<slug>` is this command's canonical, non-negotiable prefix.

**Stamp the marker after creation.** `workflow-commit-and-pr` has no input hook for injecting extra
body content at creation time, so do this as a separate step immediately after `gh pr create`
succeeds — the same fetch/append/edit pattern `workflow-extend` Phase D already uses for its
optional follow-on section:

```bash
gh pr view <N> --json body -q .body > /tmp/hotfix-pr-body-<N>.txt
printf '\n<!-- swe-workbench:deferred-verification -->\n' >> /tmp/hotfix-pr-body-<N>.txt
gh pr edit <N> --body-file /tmp/hotfix-pr-body-<N>.txt
```

Confirm the marker landed (`gh pr view <N> --json body -q .body` contains the exact line) before
moving to Phase 4 — this is the single line Phase 5 and `workflow-cleanup-merged` Step 8 both gate
on, so a silent failure here silently breaks the whole deferred-verification contract.

## Phase 4 — Verify + Review (after the PR is open)

Run exactly the same two gates `workflow-development` runs, just against the now-open PR:

- **Verify:** `superpowers:verification-before-completion` (imports/format/quality/lint/test).
- **Review — BOTH in parallel, neither optional:**
  - `superpowers:requesting-code-review` (a **Skill**) — plan-alignment, standards.
  - `swe-workbench:reviewer` (a **subagent**) — diff correctness/security/design in
    `Severity | File:Line | Issue | Why it matters | Suggested fix` format.

Fix Critical/Important issues on the branch, re-verify, re-review, then `git push` — the open PR
updates in place. Do not open a second PR.

## Phase 5 — Reconcile the marker

The deferred debt is paid only when **both** hold: a regression test was added covering the fix,
**and** Phase 4 verification is green with evidence. Judge this from what actually happened in
Phase 2–4, not from intent.

- **Paid:** `gh pr view <N> --json body -q .body`, remove exactly the
  `<!-- swe-workbench:deferred-verification -->` line (nothing else), write the result to a temp
  file, `gh pr edit <N> --body-file <tmp>`.
- **Not paid:** leave the marker untouched — `workflow-cleanup-merged` reads it at merge time and
  offers the backfill follow-up there. Do not strip it preemptively "because verification passed"
  if no regression test was added; a green test suite that never exercises the fix is not paid debt.

Report the final state: PR URL, ready-for-review confirmed, marker present or stripped.

## Project Detection

- `commit-tag` — `.githooks/commit-msg` regex, or `git log --oneline -20` type tally; resolves per
  the `hotfix → bugfix → fix` preference in Phase 3.
- `pr-template-path` — same detection as `workflow-commit-and-pr`.
- Imports/format/quality/lint/test commands — same detection as `workflow-development`.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| Uncommitted changes at invocation | `git status --porcelain` non-empty | Stop, ask to commit/stash before branching. |
| Ticket has no acceptance criteria | Command-level check | Stop and ask — never invent scope, even under time pressure. |
| `gh pr create` fails | Non-zero exit | Diagnose per `workflow-commit-and-pr`'s failure table; PR is not open yet, so no marker exists to reconcile. |
| Marker stamp fails or doesn't land | `gh pr edit` non-zero, or a re-fetch of the body doesn't show the marker | Retry the fetch/append/edit once; if it still fails, stop and report loudly rather than proceeding to Phase 4 with an unmarked PR. |
| Phase 4 review finds Critical/Important issues | Reviewer output | Fix on branch, re-verify, re-review, push — PR updates in place. |
| Regression test added but Phase 4 fails | Verification evidence missing/red | Marker stays — debt is not paid until both conditions hold. |
| PR merged before Phase 4 completes | External merge | Stop the in-flight review; the marker (if still present) is `workflow-cleanup-merged`'s signal at cleanup time. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Creating a worktree "just in case" | Never. Phase 1 is branch-only by design — that is this command's entire reason to exist. |
| Verifying before opening the PR | Never for this flow. Phase 3 (PR) always precedes Phase 4 (verify/review) — use `/swe-workbench:implement` if verify-first is wanted. |
| Opening the PR as a draft | Never. Always answer workflow-commit-and-pr's gate with Ready for review. |
| Letting workflow-commit-and-pr's branch-rename offer rename `hotfix/<slug>` away | Always answer that gate Keep as-is — see Phase 3. |
| Stripping the marker because tests happen to pass | Only strip when a regression test was actually added for this fix, not on green-suite alone. |
| Using `[hotfix]` or `[bugfix]` in this repo's commits | This repo's hook only allows the standard type set — detection resolves to `[fix]` here. |
| Writing the failing test first | TDD is intentionally relaxed for Phase 2 — the test is the deferred work, not a Phase-2 gate. |
