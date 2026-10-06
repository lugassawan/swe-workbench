---
name: workflow-redesign
description: Replace the approach of a PR — weigh redesign alternatives against its current design, then reimplement or supersede after approval. Activated by /swe-workbench:design --pr.
orchestrator: true
---

Announce at start: "Using `swe-workbench:workflow-redesign` — re-planning the approach of an open PR."

## When to invoke

- `/swe-workbench:design --pr [N] "<why>"` — the command parses flags and dispatches here
- The PR works but uses the wrong abstraction, too many moving parts, or the wrong layer

## When NOT to invoke

- Adding a related sub-idea to the PR → `/swe-workbench:extend`
- Keeping the design and cleaning it up → `/swe-workbench:refactor`
- Fixing review comments → `/swe-workbench:address-feedback`
- A PR you do not own → `/swe-workbench:review`

## Precondition

The command passes `PR_ARG` (optional PR number), `WHY` (the user's reason), `NEW_PR` (`true` when `--new-pr` was given, else `false`) and `MODE` (`grill`, `standard`, or empty when the invocation carried no explicit signal). If `WHY` is empty, ask for it once before continuing.

Every abort or stop path in Phases A–F still runs the `$RUN_DIR` reap (`swe-workbench-reap-run-dir "$RUN_DIR"`, once it exists) and, if `$WT` exists, prints its path. Nothing is ever removed on an abort.

## Phase A — Read-only context

Nothing in this phase writes to the repo or the PR.

```bash
command -v gh >/dev/null 2>&1 && command -v jq >/dev/null 2>&1 \
  && command -v swe-workbench-new-run-dir >/dev/null 2>&1 \
  && command -v swe-workbench-reap-run-dir >/dev/null 2>&1 \
  && command -v swe-workbench-address-feedback-worktree >/dev/null 2>&1 \
  && command -v swe-workbench-sync-pr-metadata >/dev/null 2>&1 \
  && command -v swe-workbench-pr-title-drift >/dev/null 2>&1 \
  && command -v swe-workbench-result-check >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
```

Run Part 1 of `reference/pr-context-fetch.md`: resolve the PR (binding `PR`, `PR_BRANCH`, `BASE_BRANCH`, `PR_URL`), check it is `OPEN` (drafts allowed), refuse fork PRs, and run the ownership gate. The gate refuses — it does not warn — in both modes, and fails closed on any `gh` error. All of it happens before senior-engineer is called.

Then allocate the scratch dir and run Part 2 (the baseline fetch) into it:

```bash
RUN_DIR=$(swe-workbench-new-run-dir extend "$PR")
```

The `extend` prefix is the run-dir flow prefix this helper accepts for PR-extending flows. Never write a literal `/tmp` path.

## Phase B — Analysis and Gate 1

Resolve the interrogation mode now, after the gates, so a refused PR never starts a grill loop: an explicit `MODE` is honored; otherwise ask once via `AskUserQuestion` (header "Mode", **Standard** recommended, **Grill me**). Grill-me activates `swe-workbench:workflow-grill`, and its `## Resolved decisions` block joins the prompt below. A `#N` after `--pr` is a PR number, never a ticket reference.

Dispatch `swe-workbench:senior-engineer` with data only: the PR diff (or stat plus file list above the size threshold), title, body, `WHY`, and any resolved decisions. Ask for 2–3 alternatives to the PR's current approach, each with sketch, strengths, weaknesses and reversibility, plus a recommendation and risks.

**Gate 1.** Present the alternatives with `AskUserQuestion`. `AskUserQuestion` allows at most 4 options, so offer one option per alternative (recommended first, at most 3) plus **Keep current approach**. Cancelling and keeping end the same way, so there is no separate Cancel option; a dismissed or unrecognised answer is treated as Keep, and so is `AskUserQuestion` being unavailable or erroring.

- **Keep current approach** → reap `$RUN_DIR` and end the run. No worktree is created, nothing is edited, nothing is pushed, and the PR is untouched.
- An alternative → continue to Phase C.

## Phase C — Plan and Gate 2

Activate `swe-workbench:workflow-development` in **Mode A** for the chosen alternative and embed the rendered `## Workflow` section in the plan, as `/swe-workbench:design` does for any codebase-changing plan. The template's Branch and Deliver phases are overridden per mode, so the plan the user approves is the plan that runs:

- **Existing-PR mode:** Branch is "reuse the PR branch `$PR_BRANCH`"; Deliver is the "Update existing PR" path — never `gh pr create`.
- **`--new-pr`:** Branch is "a fresh branch with a name distinct from `$PR_BRANCH`, never resumed or promoted"; Deliver ends with the supersede steps.

**Gate 2.** Submit the plan through `ExitPlanMode`. If `ExitPlanMode` is unavailable or errors (outside plan mode, headless), fall back to `AskUserQuestion` with **Approve plan**, **Revise** and **Cancel**, and fail closed: anything but Approve stops. Revise feedback goes back to Phase C. Rejection or Cancel ends the run like Keep does. No worktree is created and no file is edited until both gates have passed.

## Phase D — Branch

Initialise `DELIVERED=false`.

**Existing-PR mode (default).** Acquire the worktree after approval:

```bash
RESULT=$(swe-workbench-address-feedback-worktree acquire --pr "$PR" --branch "$PR_BRANCH" \
  | swe-workbench-result-check swb.address-feedback-worktree-acquire/1) || exit 1
WT=$(printf '%s' "$RESULT" | jq -r '.data.path')
CREATED_WT=$(printf '%s' "$RESULT" | jq -r 'if .data.reused then "false" else "true" end')
printf '%s' "$RESULT" | jq -r '.warnings[]? | "⚠ " + .message'
```

If `.data.dirty` or `.data.diverged` is `true`, stop and ask before Phase E: a dirty tree would sweep unrelated edits into the commit, and a diverged branch would only be rejected at push time, after the whole rebuild. Enter `$WT`, then hand off to `swe-workbench:workflow-development` Mode B at Phase 2, citing `skip-phase-1: existing PR branch reused from open PR $PR`. The rebuild is edits toward the new approach, committed as forward commits.

**`--new-pr` mode.** Run Mode B Phase 1 with a task slug that differs from the old PR's (for example, suffix `-redesign`), and do not resume an existing worktree or promote existing work: either would land commits on the old branch. After Mode B Phase 1, bind the worktree path it reports and check the branch:

```bash
WT="<absolute worktree path reported by Mode B Phase 1>"
[ -d "$WT" ] || { echo "redesign: no worktree at '$WT'." >&2; exit 1; }
NEW_BRANCH=$(git -C "$WT" rev-parse --abbrev-ref HEAD)
[ "$NEW_BRANCH" != "$PR_BRANCH" ] && [ "$NEW_BRANCH" != "$BASE_BRANCH" ] || { echo "redesign: new branch '$NEW_BRANCH' must differ from '$PR_BRANCH' and '$BASE_BRANCH'." >&2; exit 1; }
```

Re-run this check before the push in Phase F.

## Phase E — Implement → Verify → Review

Mode B Phases 2–4. This skill takes over after Mode B Phase 4: Mode B's own Phase 5 is not run, Phase F below replaces it.

- **Implement** with `superpowers:executing-plans` or `superpowers:subagent-driven-development`, applying `swe-workbench:principle-tdd` per unit.
- **Verify** with `superpowers:verification-before-completion`. Do not advance until format, lint and tests pass with evidence.
- **Review.** Dispatch **BOTH** reviewers **IN PARALLEL** — in a single batch (same turn), as two distinct required invocations, **neither optional**:
  - `superpowers:requesting-code-review` (a **Skill**) — plan-alignment, standards
  - `swe-workbench:reviewer` (a **subagent**) — diff correctness/security/design in `Severity | File:Line | Issue | Why it matters | Suggested fix` format

  Running the Skill inline and skipping the subagent (or vice-versa) does **not** satisfy this phase.

## Phase F — Deliver

First re-check the PR: `gh pr view "$PR" --json state -q .state` must still be `OPEN`. If it was merged or closed mid-run, abort and print `$PR_URL`.

**Existing-PR mode.**

1. Commit via `swe-workbench:workflow-commit-and-pr`, taking its **Update existing PR** path. Never `gh pr create`.
2. Push without force: `git -C "$WT" push origin "HEAD:refs/heads/$PR_BRANCH"` (a no-op when step 1 already pushed). If rejected as non-fast-forward, stop and tell the user to `git pull --rebase`.
3. Confirm the remote head equals local HEAD: `git -C "$WT" fetch origin "$PR_BRANCH"`, then `git -C "$WT" rev-parse HEAD` must equal `git -C "$WT" rev-parse "origin/$PR_BRANCH"`. If they differ, stop and report. Once this passes, set `DELIVERED=true`.
4. Sync the title and body: set `FIX_SHA=$(git -C "$WT" rev-parse HEAD)` and `BASE="origin/$BASE_BRANCH"`, then follow `skills/workflow-address-feedback/reference/sync-pr-metadata.md` — title-drift check, rewrite `## Summary` only, keep the `Closes` trailer, preview, require `yes`, apply with `swe-workbench-sync-pr-metadata`. The preview also flags `## Test Plan`: a redesign can leave it verifying code that no longer exists, so ask whether to rewrite it and do so only on the user's say-so; otherwise keep it. Skip its "fall through to Phase 7" step; this skill's Phase G follows. A declined or failed sync does not undo `DELIVERED`.

**`--new-pr` mode.** Re-run the `NEW_BRANCH` check from Phase D, then follow `reference/supersede-pr.md`: create the new PR through `swe-workbench:workflow-commit-and-pr` with `Supersedes #$PR` in the body, verify it, and close the old PR only behind an extra confirmation.

## Phase G — Cleanup

The reap of `$RUN_DIR` always runs: `swe-workbench-reap-run-dir "$RUN_DIR"`.

**`--new-pr` mode:** nothing else. The new worktree stays for `swe-workbench:cleanup-merged`, and the old PR's worktree was never touched.

**Existing-PR mode:** `release` runs `git worktree remove --force`, which would destroy uncommitted work. It runs only when `DELIVERED` is `true` and the worktree is provably clean — a `git status` that fails counts as not clean:

```bash
STATUS=$(git -C "$WT" status --porcelain) || STATUS="unknown"
if [ "$DELIVERED" = "true" ] && [ -z "$STATUS" ]; then
  RELEASE_RESULT=$(swe-workbench-address-feedback-worktree release \
    --pr "$PR" --path "$WT" --branch "$PR_BRANCH" --created "$CREATED_WT" \
    | swe-workbench-result-check swb.address-feedback-worktree-release/1) || RELEASE_RESULT=""
  if [ -z "$RELEASE_RESULT" ]; then
    echo "⚠ release failed — worktree at $WT may need manual cleanup." >&2
  elif [ "$CREATED_WT" = "true" ] && [ "$(printf '%s' "$RELEASE_RESULT" | jq -r '.data.removed')" != "true" ]; then
    echo "⚠ release did not remove $WT:" >&2
    printf '%s' "$RELEASE_RESULT" | jq -r '.warnings[]? | "⚠ " + .message' >&2
  fi
else
  echo "Worktree kept at $WT (delivery incomplete or uncommitted changes present)."
fi
```

Unlike address-feedback, which releases on every exit, this skill releases only after a delivered, clean state. `release` keeps the local `$PR_BRANCH`.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| Not the PR author | `gh api /user` login differs from PR author, or any `gh` error | Refuse before senior-engineer is called. |
| PR not open | state is `CLOSED` or `MERGED` | Stop. Suggest `/swe-workbench:implement`. |
| Fork PR | `isCrossRepository` is true | Refuse with the hint in `reference/pr-context-fetch.md`. |
| Empty or missing diff | fetch fails or `pr.diff` is empty | Abort; never analyse an approach that was not shown. |
| PR merged mid-run | Phase F re-check not `OPEN` | Abort, print `$PR_URL`. |
| Push rejected | non-zero `git push` | Abort; `git pull --rebase`. Never force-push. |
| Remote head differs from local HEAD | Phase F step 3 | Stop and report; do not touch PR metadata. |
| `--new-pr` branch equals old or base branch | `NEW_BRANCH` check | Abort before any commit or push. |
| Close of the old PR fails | `gh pr close` non-zero | Print the manual command; do not retry. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Creating a worktree before Gate 2 | Both gates pass first; acquire runs in Phase D only. |
| Offering more than 4 options at Gate 1 | At most 3 alternatives plus Keep. |
| Calling senior-engineer for baseline reads | It cannot see the PR head; the main thread passes the diff. |
| Running `release` after a failed delivery | Guarded by `DELIVERED` and the clean-tree check; otherwise print the path. |
| Using `gh pr create` in existing-PR mode | Only the Update existing PR path. |
| Resuming the old PR's worktree in `--new-pr` mode | Distinct slug; the `NEW_BRANCH` check enforces it. |
| Rewriting `## Test Plan` or the `Closes` trailer unasked | Only `## Summary` and the title change; the Test Plan changes only if the user accepts it from the preview. |
