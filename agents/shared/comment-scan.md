# Comment-scan invocation

Advisory scan for unnecessary or over-cap comments, backing `principle-clean-code`'s
Comment discipline caps with a deterministic, checkable artifact instead of prose recall alone.
**Advisory-with-accounting, not a hard gate** — the scan never fails your verify step; it produces
findings that verdict accounting (below) requires you to account for before calling verify done.

## Running the scan

No git access lives inside the script — resolve the diff yourself and pipe it in:

```bash
command -v swe-workbench-comment-scan >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
MERGE_BASE=$(git merge-base HEAD "origin/$DEFAULT_BRANCH" 2>/dev/null || true)
git diff -M "${MERGE_BASE:-origin/$DEFAULT_BRANCH}" | swe-workbench-comment-scan
```

**The preflight check is load-bearing, not boilerplate.** This scan runs against an arbitrary target
repo — if `swe-workbench-comment-scan` isn't on `PATH` for any reason (plugin not installed, or an
install predating `bin/`), the invocation would otherwise fail ambiguously (or, worse, get silently
treated as "not applicable" rather than "misconfigured") instead of erroring loudly with a fix
("reinstall or update the swe-workbench plugin"). Same pattern as `bin/README.md`'s canonical
preflight — don't drop the check when copying the snippet.

`-M` detects renames so a moved function's untouched doc comment isn't misread as newly added.
Diffing from the merge-base (not `origin/main` directly) covers committed + staged + unstaged work
in one pass without picking up main's own post-branch-point changes as if they were yours. If
`MERGE_BASE` comes back empty (unrelated-history repo), the fallback diffs straight against the
branch tip — same defensive posture as `workflow-branch-sync`'s redundancy-check capture.

## Verdict accounting

The script's footer reports a must-triage count, e.g. `COMMENT-SCAN: 3 must-triage (OVER_CAP=2
RESTATES=1) INFO=1`. Your Phase 3 / verify evidence must carry exactly one line per must-triage
finding, referencing its `detector:file:line` id:

- `KEEP <id> <reason>` — the comment stays; state why (e.g. a genuinely non-obvious gotcha that
  earns its length, or a doc-comment whose value outweighs the soft cap).
- `FIXED <id>` — you trimmed, rewrote, or removed the flagged comment.

**INFO findings (DENSITY) never require a verdict line** — they're context, not a checklist item.

**Confirm every `FIXED`:** re-run the scan after your edits. A `FIXED` id must be absent from the
second run's output; `KEEP` ids are expected to persist. **Caveat:** ids are `detector:file:line` —
if your fix added or removed lines above another finding in the *same file*, that finding's line
number (and therefore its id) shifts too. Re-match surviving `KEEP`s by detector + message content
against the second run's ids, not by expecting the exact same id string to reappear.

**No verdict for something that isn't a real finding?** You disagree with the detector, not with
the comment — say so as part of the `KEEP` reason (e.g. `KEEP RESTATES:foo.py:12 not a restatement,
overlap is coincidental identifier reuse`). Verdict accounting is about coverage (every finding
addressed), not about the detector always being right.
