---
name: workflow-extend
description: Captures a mid-PR sub-idea and implements it on the same branch as the existing PR — skips Phase 1 (Branch), preserves Verify → Review → Deliver, and uses workflow-commit-and-pr to update existing PR. Never creates a new branch or new PR.
orchestrator: true
---

Announce at start: "Using `swe-workbench:workflow-extend` — capturing and implementing sub-idea onto the existing PR."

## When to invoke

- `/swe-workbench:extend` command
- "extend the PR", "add this on top of the current PR"
- Mid-PR follow-on idea surfaces while working on an in-flight branch
- Related sub-idea that belongs on the same branch and same PR

## When NOT to invoke

- No open PR exists for the current branch → command body owns the fallback (AskUserQuestion)
- Sub-idea is unrelated to current PR → use `/swe-workbench:implement` for a fresh branch
- PR is already merged → use `/swe-workbench:implement` for a follow-up PR
- Bug on someone else's PR → use `/swe-workbench:debug`

## Precondition

The command body detects the open PR before activating this skill and passes:
- `PR_NUM` — open PR number
- `HEAD_REF` — current branch name
- `PR_URL` — URL of the existing open PR
- `IS_DRAFT` — `"true"` if the PR is a draft, `"false"` otherwise (always lowercase)

If PR_NUM, HEAD_REF, or PR_URL are absent, **fail loudly**: "workflow-extend requires an open PR on the current branch. Run `gh pr view` to diagnose or use the command-level fallback." If `IS_DRAFT` is absent, treat as non-draft and log a warning.

## Phase A — Capture (inline; no top-level issue by default)

Apply the four lenses with brevity. Use `agents/product-manager.md` lens phrasing as canonical reference — do NOT invoke the product-manager agent (its filing-centric contract is wrong here).

1. **Problem.** User pain or constraint, stated as the user's pain — not the feature.
2. **Value.** Who benefits and how. One "so-what" sentence.
3. **Acceptance criteria.** 2–4 bullets (Given/When/Then or simple bullets).
4. **Impact / Effort.** `Impact: S/M/L` and `Effort: S/M/L`, one sentence each.

Obtain a Unix timestamp: `TS=$(date +%s)`. Write spec to `/tmp/extend-${TS}.md` using the Write tool. Print the spec to the user. **Require explicit confirmation before proceeding.**

### Opt-in escalations (only when user phrase matches)

| User phrase | Action |
|---|---|
| "consult senior-engineer" / "this is architectural" | Invoke `senior-engineer` subagent for a boundary read; fold its AC output into the spec before confirming. |
| "frame as a bug" / "this is a regression" | Route entirely to `swe-workbench:debugger` subagent; skip Phases B–D (debugger has its own verify+review loop). Commit per debugger output on the existing branch. |
| "also file an issue" / "track this in github" | After Phase D delivery, chain `product-manager` agent (its confirm gate handles filing). |

## Phase B — Plan (extend section)

Render `skills/workflow-extend/templates/plan-extend-section.md` into the spec. Substitute markers:
- `[[detect:branch-name]]` → `HEAD_REF` from context
- `[[detect:pr-url]]` → `PR_URL` from context
- `[[detect:pr-number]]` → `PR_NUM` from context
- `[[detect:commit-style]]` → from `git log --oneline -5` (detect `[type]` vs `type:` pattern)
- `[[detect:test-command]]`, `[[detect:format-command]]`, `[[detect:lint-command]]` → from Makefile grep or `package.json` scripts

Do NOT invoke `workflow-development` Mode A here — this skill renders its own template. Phase 1 (Branch) is intentionally absent.

## Phase C — Implement, Verify, Review

Hand off to `swe-workbench:workflow-development` Mode B starting at **Phase 2 (Implement)**, citing `skip-phase-1: existing branch [[detect:branch-name]] reused from open PR [[detect:pr-number]]` so the orchestrator does not attempt worktree creation.

**Phase 2:** Execute implementation tasks using `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Apply `swe-workbench:principle-tdd` per unit: red → green → refactor.

**Phase 3 (Verify):** Run `superpowers:verification-before-completion`. Do not advance until all format / lint / test steps pass with evidence.

**Phase 4 (Review):** Dispatch both reviewers:
- `superpowers:code-reviewer` — plan-alignment and standards
- `swe-workbench:reviewer` — diff correctness/security/design

The reviewer must additionally check: **does the diff scope match the captured AC?** Flag scope creep as `Severity: High | scope-creep | <files>` and ask user to confirm or carve out before proceeding.

Do not advance to Phase D until Phase C review passes clean or all issues are resolved.

## Phase D — Deliver via workflow-commit-and-pr

Commit format: `[<type>] sub-idea: <one-line restatement>` (e.g. `[feat] sub-idea: retry on transient client errors`).

Commit body must include `Ref: extend-${TS}` on its own line.

Push. Then invoke `swe-workbench:workflow-commit-and-pr`. That skill will surface an **"Update existing PR"** AskUserQuestion — the user must select it. **Never call `gh pr create`** when an open PR exists for this branch. Tell the user to expect this prompt and select "Update existing PR".

Optional: if the user opts in ("append follow-on section"), fetch the current PR body first (`gh pr view --json body -q .body`), append the `## Follow-on` section, write to a tempfile, then `gh pr edit --body-file <tmp>` — this avoids overwriting collaborator edits.

## Project Detection

Inherits detections from `workflow-development` for shared markers; adds extend-specific PR markers.

**Detection markers** used by `templates/plan-extend-section.md`:

- `branch-name` — `git rev-parse --abbrev-ref HEAD`
- `pr-url` — `gh pr view --json url -q '.url'`
- `pr-number` — `gh pr view --json number -q '.number'`
- `extend-ts` — `TS` captured in Phase A via `date +%s`; substitute manually into template (no shell script context)
- `commit-style` — from `git log --oneline -5` (detect `[type]` vs `type:` pattern)
- `format-command` — from Makefile `format` target or language-marker fallback
- `lint-command` — from Makefile `lint` target or language-marker fallback
- `test-command` — from Makefile `test` target or language-marker fallback

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| PR detection fails at skill entry | PR_NUM/HEAD_REF/PR_URL absent from context | Fail loudly with diagnostic hint. |
| PR merged mid-flow | `gh pr view` returns `MERGED` at Phase D | Abort. Print PR URL. Suggest `/implement` for a follow-up PR. |
| Push rejected (non-FF) | `git push` non-zero | Abort. Tell user: `git pull --rebase`. Never force-push. |
| Scope creep flagged in review | Reviewer flags `Severity: High | scope-creep` | Ask user to confirm scope or carve out before proceeding. |
| Dirty working tree at invocation | `git status --porcelain` non-empty | Abort. Prompt user to commit or stash uncommitted changes. |
| `HEAD_REF` is `main` or `master` | Branch check | Fail loudly: "Cannot extend from a trunk branch. Checkout a feature branch first." |
| Draft PR | `gh pr view` returns `isDraft: true` | Treat as OPEN. Note in output. Do not auto-mark ready-for-review. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Auto-creating a new PR | Never call `gh pr create` when an open PR exists. Use `Update existing PR` path. |
| Skipping Verify because "small change" | Always run Phase 3. Small changes have bugs too. |
| Forgetting `Ref: extend-<ts>` in commit body | The commit body traceability line is required — include it every time. |
| Invoking `senior-engineer` heuristically | Only on explicit user opt-in. Never auto-route to escalation agents. |
| Calling `workflow-development` Phase 1 | Phase 1 is intentionally skipped. Cite `skip-phase-1` rationale explicitly. |
