# Supersede PR reference

Delivery tail for `--new-pr` mode. The order exists for failure safety: any failure before
step 5 leaves the original PR untouched. The old PR's branch is never deleted.

1. Create the new PR through `swe-workbench:workflow-commit-and-pr` (it owns the `[type]`
   title prefix, the draft/ready prompt and the PR template). Tell it the body must
   contain a standalone `Supersedes #N` line and must carry the old PR's issue linkage
   forward: take the `Closes #X` / `Fixes #X` / `Issue: N/A` trailer from the old body, or
   `gh pr view N --json closingIssuesReferences`, and put it in the new body too. Without
   it, CI rejects the new PR or the issue never auto-closes.
2. Verify the new PR: `gh pr view <new> --json state,url,body` must report `OPEN`, and the
   body must contain the line `Supersedes #N` on its own — match
   `grep -Eq "^Supersedes #N( |$)"`, so `#12` never matches `#123`. Otherwise stop here
   and leave the old PR alone.
3. Re-check the original: `gh pr view N --json state,author` must still be `OPEN` and
   still authored by `$CURRENT_USER`. If it was merged or closed mid-run, skip the close
   and say so.
4. Ask for the extra confirmation: "Close #N in favor of <new url>? Reply `yes`." Any other
   reply leaves the old PR open.
5. On `yes`: `gh pr close N --comment "Superseded by <new url>"`.

If the close fails, print the manual command (`gh pr close N --comment "Superseded by <new url>"`)
and do not retry. The new PR stands either way.
