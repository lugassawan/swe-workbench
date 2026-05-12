---
name: principle-version-control
description: Version control & collaboration hygiene — atomic commits (one logical change), commit-message quality (imperative subject, body explains why), branching strategy (feature-branch vs trunk-based), rebase vs merge trade-offs, squash vs preserve history, PR description quality (what/why/how-to-test). Auto-load when discussing commit hygiene, writing commit messages, choosing a branching strategy, debating rebase vs merge, deciding when to squash, or reviewing PR description quality.
---

# Version Control & Collaboration

`git log` is a debugging instrument. Its quality depends entirely on the discipline of the people who wrote to it.

## Atomic commits — one logical change

One commit, one reason to revert it. The test: can you describe the change in a short subject line without using "and"?
- Atomic commits make `git bisect` effective — a failing test traces to the exact change that introduced it.
- Atomic commits make reverts safe — reverting "add feature X" does not also undo "fix unrelated bug Y".
- Split a large change by concern: refactor first (pure mechanical moves), then behavior change, then test additions.

## Commit messages — what makes them load-bearing

Subject line: imperative mood, ≤50 characters, no trailing period. Body: wrap at 72 characters, explain *why*, not *what*.

```
[type] Short imperative subject (≤50 chars)

Why this change was made. What would break if reverted.
Link the issue or ticket. Note non-obvious constraints.
```

Format schemes — Conventional Commits (`feat:`, `fix:`), `[type] Subject`, JIRA-prefix — are all valid conventions. Pick one; apply consistently and enforce via a `commit-msg` hook. Example: the swe-workbench plugin repo enforces `[type] Subject` via `.githooks/commit-msg`. Before authoring commit messages, detect the host repo's convention via the detection step in `swe-workbench:workflow-commit-and-pr`.

## Never mix formatting and logic

Formatting commits (whitespace, import sort, rename) belong in a separate commit from behavior changes. Reviewers can skim a formatting-only commit in seconds; mixing it into a logic commit makes the diff unreadable and breaks `git blame` for every touched line.

## Branching — feature-branch vs trunk-based

**Feature branches** work when: CI is slower than a few minutes, teams have >2 engineers, or releases are discrete.
- Keep branches short-lived (days, not weeks). Long-lived branches accumulate merge debt.
- Branch naming convention keeps the log readable — `feat/<issue>-<slug>`, `fix/<slug>`, `chore/<slug>`.

**Trunk-based development** works when: CI is fast (<5 min), team is small and disciplined, and deployments are continuous.
- Requires feature flags for incomplete work landing on trunk.
- Pair with small, frequent commits — a day's work at most.

## Rebase vs merge — preserving vs flattening history

**Rebase** local, unpublished branches to keep a clean linear history. Never rebase a branch others have pulled — it rewrites SHAs and orphans their work. Exception: `--force-with-lease` on your own solo feature branch is safe when you are the sole author and communicate the rewrite.
- `git pull --ff-only` for main: fast-forward only; fail loudly on divergence instead of silently creating a merge commit.
- Interactive rebase (`rebase -i`) before opening a PR: squash WIP commits, fix-up typos, reorder logically.

**Merge** preserves the full branch topology — useful when the branch history documents a parallel exploration or a release boundary.
- `--no-ff` merge commits document "this was a feature branch" even when the history would fast-forward cleanly.

See `swe-workbench:workflow-cleanup-merged` for post-merge local cleanup (fast-forward pull, squash-merge branch detection).

## Squash vs preserve on merge

**Squash** when: branch commits are WIP saves, fix-ups, or cleanup noise. The merged result is one clean commit on main.

**Preserve** when: each commit is a meaningful, independently-reviewable step. The branch history survives on main and remains bisectable.

Default rule: if you would be embarrassed for a commit message to live on main forever, squash it.

## PR descriptions — what reviewers actually need

A PR description answers three questions:
1. **What changed?** — the minimal summary a stranger needs to understand scope.
2. **Why?** — link the issue; explain the motivation if it is not obvious from the ticket.
3. **How to verify?** — test plan, repro steps, or a note that CI covers it.

Flag risk explicitly: migrations, breaking API changes, coordinated-deploy requirements.
See `swe-workbench:workflow-pr-review` for review orchestration and `swe-workbench:principle-clean-code` for the small-change discipline that makes atomic commits tractable.

## When strict discipline is overkill

- Solo throwaway repos or local experiments — no reviewer means no need for archaeology-quality messages.
- Single-shot scripts that will never be modified again.
- Exploratory spikes: commit freely with "wip"; squash the whole branch before the real PR.

Even then: one commit per coherent idea costs nothing and pays off the first time you need `git bisect`.

## Red Flags

| Flag | Problem |
|------|---------|
| "WIP", "fix", "asdf" on a shared branch | Bisect useless; history tells no story |
| Force-push to a branch others have pulled | Rewrites SHAs; orphans teammates' local branches |
| Formatting mixed with logic in one commit | `git blame` broken; reviewer cannot skim the diff |
| "fix typo" chains on a feature branch | Noise that should be squashed before the PR |
| Branch open for >2 weeks | Merge debt compounds; rebase conflicts grow |
| PR body empty or only "closes #N" | No context for reviewer; future archaeology blocked |
| `git pull` without `--ff-only` on main | Creates a silent merge commit when local main has diverged; `--ff-only` fails loudly instead |
