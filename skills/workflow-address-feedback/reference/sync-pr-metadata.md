# Sync PR metadata reference

Full mechanics for Phase 6 — syncing the PR's title and `## Summary` body section after
Phase 4 fixes are committed, so the PR description stays accurate as the diff grows.

Skip this phase entirely if `$FIX_SHA` is unset (no fixes were committed in Phase 4).

Fetch: `gh pr view "$PR" --json title,body`; commit subjects via `git -C "$WT" log "$BASE"..HEAD --format='%s'`; diff stat via `git -C "$WT" diff "$BASE"..HEAD --stat`. No new state file — the reap already ran in Phase 5 (covers `${PR}-pr-comments.json` too).

**Judge drift** by comparing the live title and `## Summary` section of the PR body against the commit subjects and diff stat. If aligned, emit "PR metadata is up to date — no changes needed." and fall through to Phase 7 — Cleanup.

**If drift is detected,** draft a revised `$NEW_TITLE` and `$NEW_SUMMARY`. Rewrite only the `## Summary` section of the body; preserve `## Test Plan`, the `Closes #`/`Fixes #`/`Issue: N/A` trailer, and all other collaborator sections. Preview old→new for title and summary, then:

> Reply `yes` to apply these changes to PR #N.

On `yes`:
```bash
NEW_BODY_FILE=$(mktemp)
trap 'rm -f "$NEW_BODY_FILE"' EXIT
printf '%s' "$NEW_BODY" > "$NEW_BODY_FILE"
swe-workbench-sync-pr-metadata "$PR" "$NEW_TITLE" "$NEW_BODY_FILE" \
  || echo "Warning: PR metadata update failed — continuing to cleanup." >&2
```
