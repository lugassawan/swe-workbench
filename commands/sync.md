---
description: Bring the current branch up to date with the default branch — delegates the mechanical merge/rebase to rimba (or git), then walks through any conflicts file-by-file with a recommended resolution before applying. Never auto-pushes. Always fetches origin's default branch before comparing. Pass --rebase to rebase instead of merge. Pass --check-redundancy to also surface functional duplication the default branch already provides. Pass --check-alignment to assess architectural or conceptual drift against main's commit history.
argument-hint: "[--rebase] [--check-redundancy] [--check-alignment]"
---

Target: $ARGUMENTS

## Strategy resolution

Parse `$ARGUMENTS` left to right for `--rebase`, `--check-redundancy`, and `--check-alignment`:

- **`--rebase` present**: strip the flag from the target text and use **rebase** strategy.
- **`--rebase` absent**: use the **merge** strategy (default).
- **`--check-redundancy` present**: strip the flag from the target text and resolve `CHECK_REDUNDANCY=on`.
- **`--check-redundancy` absent**: resolve `CHECK_REDUNDANCY=off` (default) — plain `sync` stays unchanged.
- **`--check-alignment` present**: strip the flag from the target text and resolve `CHECK_ALIGNMENT=on`.
- **`--check-alignment` absent**: resolve `CHECK_ALIGNMENT=off` (default).

Invoke `swe-workbench:workflow-branch-sync`, passing the resolved strategy (`merge` or `rebase`), `CHECK_REDUNDANCY=on|off`, and `CHECK_ALIGNMENT=on|off`.

## Output

The `swe-workbench:workflow-branch-sync` skill produces a per-file resolution summary followed by a push prompt:

1. **Sync result** — clean (fast-forward/no-conflict) or resolved-with-conflicts, and the strategy used (merge/rebase). Prefixed by the fetch status line from the skill's remote-ref refresh (`origin/<default> updated <old>→<new>` or `unchanged`).
2. **Per-file resolution** — one line per conflicting file: which side was kept (mine/main/manual) and the one-line rationale surfaced by the `swe-workbench:conflict-resolver` subagent.
3. **Redundancy assessment** (only when `--check-redundancy` was passed — opt-in) — any whole-file candidates the branch added that the default branch already grew independently elsewhere, auto-applied (whole-file, zero references) or escalated to you per candidate.
4. **Alignment assessment** (only when `--check-alignment` was passed — opt-in) — evaluates branch changes against main's recent history to detect architectural drift or paradigm shifts, escalating to you if drift is detected.
5. **Push prompt** — the result is left local; the skill asks before pushing. Merge pushes with `git push`; rebase pushes with `git push --force-with-lease` — never a plain force push.

No push happens without an explicit yes from the user.
