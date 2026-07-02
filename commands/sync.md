---
description: Bring the current branch up to date with the default branch — delegates the mechanical merge/rebase to rimba (or git), then walks through any conflicts file-by-file with a recommended resolution before applying. Never auto-pushes. Pass --rebase to rebase instead of merge.
argument-hint: "[--rebase]"
---

Target: $ARGUMENTS

## Strategy resolution

Parse `$ARGUMENTS` left to right for `--rebase`:

- **`--rebase` present**: strip the flag from the target text and use **rebase** strategy.
- **`--rebase` absent**: use the **merge** strategy (default).

Invoke `swe-workbench:workflow-branch-sync`, passing the resolved strategy (`merge` or `rebase`).

## Output

The `workflow-branch-sync` skill produces a per-file resolution summary followed by a push prompt:

1. **Sync result** — clean (fast-forward/no-conflict) or resolved-with-conflicts, and the strategy used (merge/rebase).
2. **Per-file resolution** — one line per conflicting file: which side was kept (mine/main/manual) and the one-line rationale surfaced by the `conflict-resolver` subagent.
3. **Push prompt** — the result is left local; the skill asks before pushing. Merge pushes with `git push`; rebase pushes with `git push --force-with-lease` — never a plain force push.

No push happens without an explicit yes from the user.
