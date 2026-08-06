---
description: Run an unattended review→fix→re-review loop on the current branch until the reviewer has no findings at or above Medium, then push once. Findings stay in a local scratch file and are never posted to GitHub. Stops early on oscillation, a red test suite, or a 4-review cap.
argument-hint: "[--cap <2-6>]"
---

Run a local, unattended convergence loop on the current branch: review → verify findings → fix →
re-review, until the reviewer has nothing left to say at or above Medium severity, then push once.
No intermediate round is ever posted to GitHub — findings live in a local scratch file under
`$RUN_DIR` and are deleted the moment they're consumed.

## Argument parsing

`$ARGUMENTS` carries at most one flag: `--cap <N>`, `N` in `2..6`. Parse it once, up front:

```bash
CAP=4
case "$ARGUMENTS" in
  *--cap*)
    CAP=$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--cap[= ]([0-9]+)' | grep -oE '[0-9]+' | head -1)
    case "$CAP" in
      2|3|4|5|6) ;;
      *) echo "converge: --cap must be an integer in 2..6 (got: ${CAP:-<empty>})" >&2; exit 1 ;;
    esac
    ;;
esac
echo "Cap: $CAP reviews (default 4 when unset)"
```

`CAP` counts **reviews, not rounds** — see "Cap and the loop invariant" below.

## Phase 0 — Preflight

Runtime guard, one representative script (proves the whole `bin/` PATH entry is present):

```bash
command -v swe-workbench-new-run-dir >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
```

Refuse on the default branch or a detached HEAD — the loop commits, so it needs a branch to commit
onto:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
[ -n "$DEFAULT_BRANCH" ] || DEFAULT_BRANCH=main
if [ "$BRANCH" = "$DEFAULT_BRANCH" ] || [ "$BRANCH" = "HEAD" ]; then
  echo "converge: refusing to run on '$BRANCH' — check out a feature branch first." >&2
  exit 1
fi
BASE="$DEFAULT_BRANCH"
git fetch origin "$BASE" --quiet || true
if [ -z "$(git diff "origin/$BASE"...HEAD)" ]; then
  echo "converge: no diff between origin/$BASE and HEAD — nothing to converge." >&2
  exit 1
fi
```

### Ownership gate — refuse, do not warn

The loop commits and pushes autonomously, so running it against a PR you don't own is a
destructive-by-default hazard, not a style issue. This is a **stronger** gate than
`swe-workbench:workflow-address-feedback`'s owner check, which only shapes prompts.

```bash
gh auth status >/dev/null 2>&1 || {
  echo "converge: gh is not authenticated — run 'gh auth login' first." >&2
  exit 1
}
CURRENT_USER=$(gh api /user -q .login)
PR_VIEW_OUT=$(gh pr view --json author,number 2>&1)
PR_VIEW_EXIT=$?
if [ "$PR_VIEW_EXIT" -eq 0 ]; then
  PR_AUTHOR=$(printf '%s' "$PR_VIEW_OUT" | jq -r '.author.login')
  PR_NUM=$(printf '%s' "$PR_VIEW_OUT" | jq -r '.number')
elif printf '%s' "$PR_VIEW_OUT" | grep -q "no pull requests found"; then
  PR_AUTHOR=""
  PR_NUM=""
else
  echo "converge: could not verify PR ownership — gh pr view failed: $PR_VIEW_OUT" >&2
  exit 1
fi
if [ -n "$PR_AUTHOR" ] && [ "$PR_AUTHOR" != "$CURRENT_USER" ]; then
  echo "PR #$PR_NUM is authored by @$PR_AUTHOR; /swe-workbench:converge only runs on your own PRs. Use /swe-workbench:review $PR_NUM to review someone else's work." >&2
  exit 1
fi
```

- `PR_AUTHOR` non-empty and `!= CURRENT_USER` → refuse, non-zero exit, **before any `$RUN_DIR` is
  allocated** — nothing to reap because nothing was allocated.
- No PR yet (`PR_AUTHOR` empty, only reached when `gh pr view` fails with its specific "no pull
  requests found" message) → proceed. The branch is local and unpushed; you own it by construction,
  and the first push happens under your identity at Phase 5.
- **Any other `gh pr view` failure — network blip, rate limit, API hiccup — fails closed, not
  open.** Silently treating an unrelated `gh` error the same as "no PR exists" would let the loop
  proceed against a branch that in fact has an open PR authored by someone else, whenever the
  ownership check itself happens to fail transiently — defeating the one gate this section exists
  to enforce.
- `gh` unauthenticated → stop with the standard `gh auth login` remediation, never assume ownership.

Only after the gate passes, allocate the run dir once:

```bash
LOOP_ID="${PR_NUM:-0}"
eval "$(swe-workbench-new-run-dir review-converge "$LOOP_ID")"
```

`review-converge` matches the `review-[a-z][a-z-]*` allowlist in both
`bin/swe-workbench-new-run-dir` and `bin/swe-workbench-reap-run-dir` — no script edits needed, and
Phase 6's cleanup works for free.

### Loop state

Two cross-round artifacts, both scoped to this run:

- `$RUN_DIR/loop-state.json` — the ledger: `{version, branch, base, cap, floor, round, reviews[],
  retired[], rejected[], unfounded[], out_of_diff[], adjudicated[], commits[]}`. Initialize with
  `round=0, floor="Medium", cap=$CAP` and empty arrays. `out_of_diff[]` holds findings excluded from
  the convergence predicate for being outside the branch diff — kept distinct from `unfounded[]`
  (see Phase 1b) since the two are different claims about a finding.
- `<git-toplevel>/.claude/cache/workflow-state/<branch-with-slashes-as-dashes>.json` — the Tier-4
  checkpoint (see `docs/workflow-state.md`), written at every round boundary so the round count
  survives compaction. Use `skill: converge`, `phase: round-<N>-review` (or `-fix`, `-verify`),
  `context.notes: run_dir=<RUN_DIR>; cap=<CAP>; floor=Medium; fixed=<n>; rejected=<n>`. Deleted in
  Phase 6.

**Esc abort is external, not in-turn.** A bash `trap` covers only one bash invocation; Esc
terminates the model turn, so no in-turn handler fires here. The guarantee instead rests on three
things that already exist: `$RUN_DIR` is mode-0700 under `/tmp/swe-workbench-run/` (OS-purged,
bounded, private); `context.notes` carries `run_dir=<path>` and `hooks/workflow_resume_hint.sh`
already surfaces it on the next `SessionStart` with a 24h sweep; and
`bin/swe-workbench-new-run-dir` age-reaps orphans older than 24h at the next allocation. This
command does not pretend to catch Esc in-turn — say so if asked.

## Phase 1 — Review round N

Dispatch `swe-workbench:reviewer` against `git diff origin/$BASE...HEAD` with:

- The **Decision footer** and **Blocking-scope verdict** instructions (per its own "when
  instructed" contracts).
- The same anchor-assignment rule `skills/workflow-pr-review/SKILL.md` Step 6 uses: `anchor:
  inline` when the finding's line is in-diff (a `+` line), `anchor: pr-level` otherwise, per the
  reviewer's own out-of-diff informational marker.
- A **suppression block** built from the ledger — see "Cross-round dedup" below — carrying
  `retired[]`, `rejected[]`, and `unfounded[]` **with their evidence**, not a bare "don't
  re-report".

Write the parsed findings to `$RUN_DIR/round-<N>-findings.json` using the **existing sanctioned
schema** — `{severity, body, anchor, path, line}` (`anchor` = `inline` or `pr-level`), the same one
`_finding_problem()` in `bin/swe-workbench-pr-review-submit` validates. Do not invent a second
findings format — this keeps the file submit-compatible and keeps one schema in the repo.

Footer parsing reuses `swe-workbench:workflow-pr-review`'s Step 5 rules verbatim:

- Regex `^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$`, scanned over all non-blank lines.
- Zero matches, more than one match, or `REQUEST_CHANGES` appearing anywhere → **ABORT** — do not
  fix on a findings set that could not be parsed coherently. Report and jump to Phase 6 (parse
  fault).
- `^\*\*Blocking Scope:\s+(NONE|OUT-OF-DIFF-ONLY|IN-DIFF)\*\*$` — zero or >1 matches default to
  `IN-DIFF` (fail-safe) with a warning; never aborts on its own.

**One new cross-check, specific to this loop:** if the footer says `Blocking Scope: NONE` but the
parsed findings array holds an in-diff Critical/High row (or the inverse — `IN-DIFF` with no such
row) → the parse is faulty. Abort, report, jump to Phase 6 (parse fault). No push.

## Phase 1b — Mechanical anchor validation

Before anything counts as a finding, check what can be checked deterministically — no agent, no
tokens. For each row in `round-<N>-findings.json` with `anchor: inline`:

| Check | Fails → |
|---|---|
| `path` exists in the working tree | `UNFOUNDED (no such file)` |
| `path` ∈ `git diff origin/$BASE...HEAD --name-only` | out-of-diff → excluded from the convergence predicate (not unfounded) |
| `line` ≤ the file's line count | `UNFOUNDED (line out of range)` |
| the line at `path:line` resolves inside a diff hunk | `UNFOUNDED (anchor not in diff)` |

The last check reuses `bin/swe-workbench-diff-line-lookup`, and — critically — confirms the
resolved line number matches the finding's claimed line, not merely that *some* added line in the
file contains matching text (a bare `}` or `pass` recurs across a diff; a content-only match would
wrongly validate an unrelated anchor):

```bash
DIFF_FILES=$(git diff "origin/$BASE"...HEAD --name-only)
jq -c '.[] | select(.anchor == "inline")' "$RUN_DIR/round-${N}-findings.json" | while IFS= read -r row; do
  ROW_PATH=$(printf '%s' "$row" | jq -r '.path')
  ROW_LINE=$(printf '%s' "$row" | jq -r '.line')
  [ -f "$ROW_PATH" ] || { echo "UNFOUNDED (no such file): $ROW_PATH"; continue; }
  printf '%s\n' "$DIFF_FILES" | grep -qxF "$ROW_PATH" \
    || { echo "OUT-OF-DIFF (excluded from predicate): $ROW_PATH"; continue; }
  TOTAL_LINES=$(awk 'END{print NR}' "$ROW_PATH")
  [ "$ROW_LINE" -le "$TOTAL_LINES" ] || { echo "UNFOUNDED (line out of range): $ROW_PATH:$ROW_LINE"; continue; }
  CONTENT=$(sed -n "${ROW_LINE}p" "$ROW_PATH")
  RESOLVED=$(swe-workbench-diff-line-lookup "$ROW_PATH" "$CONTENT" --range="origin/$BASE...HEAD" 2>/dev/null)
  LOOKUP_EXIT=$?
  if [ "$RESOLVED" = "${ROW_PATH}:${ROW_LINE}" ]; then
    :  # anchor-valid
  elif [ "$LOOKUP_EXIT" -eq 2 ]; then
    # Ambiguous (exit 2): the line's content recurs elsewhere in this file's diff (a bare "}",
    # "pass", a blank line) — content-uniqueness failed, not the anchor. Fall back to hunk-range
    # membership instead of declaring UNFOUNDED on an artifact of the content match, not the claim.
    IN_HUNK=$(git diff "origin/$BASE"...HEAD -- "$ROW_PATH" | awk -v line="$ROW_LINE" '
      /^@@/ {
        if (match($0, /\+[0-9]+(,[0-9]+)?/)) {
          s = substr($0, RSTART + 1, RLENGTH - 1)
          split(s, a, ",")
          start = a[1]
          len = (a[2] == "" ? 1 : a[2])
          if (line >= start && line < start + len) print "yes"
        }
      }')
    [ "$IN_HUNK" = "yes" ] || echo "UNFOUNDED (anchor not in diff): $ROW_PATH:$ROW_LINE"
  else
    echo "UNFOUNDED (anchor not in diff): $ROW_PATH:$ROW_LINE"
  fi
done
```

The diff-membership check runs *before* the diff-line-lookup call and is load-bearing on its own —
without it, a path the branch never touched falls through to `diff-line-lookup`, which fails to
resolve any line for a file with no `+++` header in the diff, and the row would be mislabeled
`UNFOUNDED` (premise false) instead of `OUT-OF-DIFF` (premise untested, out of scope). The two are
not the same claim, and only `UNFOUNDED` rows feed the reviewer-degradation signal in "Cap and the
loop invariant" below. `OUT-OF-DIFF` rows go to the ledger's `out_of_diff[]` array and the report's
"observations outside the branch diff" bucket — never `unfounded[]`.

Anchor-invalid (`UNFOUNDED`) rows move straight to `unfounded[]` in the ledger with their reason;
`OUT-OF-DIFF` rows move to `out_of_diff[]`. Neither reaches the fixer, and neither **blocks
convergence**. A fabricated file path or a line number past EOF is the cheapest, most common
hallucination shape, and this catches it for one script call per row.

## Phase 2 — Termination check

> **converged ⟺ zero *anchor-valid* findings at or above `FLOOR`, restricted to findings inside
> the branch diff.**

Three load-bearing qualifications:

- **Only anchor-valid findings count.** A round whose findings are all `UNFOUNDED` per Phase 1b is
  a **converged round**, not a blocked one — otherwise a hallucinating reviewer could hold the
  loop hostage indefinitely.
- **`FLOOR` is hardcoded to `Medium`.** A literal-zero bar (including Low) makes non-convergence
  the normal outcome on any real diff and hands the fixer a mandate for cosmetic churn. Residual
  Low findings are printed in the final report as *"accepted nits — not acted on"* — nothing is
  silently swallowed.
- **Out-of-diff findings are excluded from the predicate.** On a repo with pre-existing debt the
  reviewer would report it every round while the fixer's scope fence refuses to touch it — the
  most likely cause of false non-convergence. Such findings go to the report under "observations
  outside the branch diff", never to the fixer.

The Decision-footer / Blocking-Scope pair is retained only as a **consistency assertion** (the
Phase 1 cross-check) — never as the predicate itself. `Blocking Scope: NONE` covers only
Critical/High and is a lossy proxy for the actual `≥Medium` bar.

If converged → go to Phase 5. Otherwise, **check the cap before fixing anything**: if this round's
review count `N` has already reached `CAP`, jump straight to Phase 6 (cap exhausted) — do **not**
run Phase 3. Only proceed to Phase 3 when `N < CAP`. This is where the loop invariant in "Cap and
the loop invariant" below is actually enforced: checking the cap here, before a fix pass can start,
is what guarantees termination always lands immediately after a review — checking it after Phase 4
instead would let one more fix run and commit without ever being re-reviewed.

## Phase 3 — Fix round N

Brief `swe-workbench:code-impl` with:

1. **The findings file *path*, not its text** — `$RUN_DIR/round-<N>-findings.json` — the agent
   reads the JSON itself. This is the cheapest available context-growth mitigation; pasting
   findings inline would put every finding in context twice per round.
2. **Scope fence:** only files in `git diff origin/$BASE...HEAD --name-only`. Anything outside →
   `REJECTED`.
3. **Verify before you fix — mandatory first step per finding.** *A finding is a claim, not a
   fact. Read the cited code before editing it and confirm the claim is actually true of this
   code. If the premise is false — the cited construct is not there, the described behaviour is
   not what the code does, the "missing" guard already exists upstream, the API is in fact used
   correctly — return `UNFOUNDED` with the actual code as evidence. Do not "fix" your way into
   agreement with a wrong claim.* Every disposition must cite evidence: `FIXED` states what the
   code did and now does; `UNFOUNDED` quotes what is actually at `path:line`.
4. **Explicit prohibitions** — the most important paragraph in the brief: never delete, skip,
   `xfail`, `@Ignore`, weaken an assertion, lower a coverage threshold, or broaden a lint-ignore
   to make a finding go away. If a finding can only be satisfied that way, return `REJECTED` with
   the reason. No new features, no drive-by refactors.
5. **Return format:** one line per finding —
   `<fingerprint> | FIXED <what changed> | UNFOUNDED <what is actually there> | REJECTED <reason> | DEFERRED <reason> | UNVERIFIABLE <what was investigated, and the specific question the codebase cannot answer>`.
   **`fingerprint` is the same normalized-path + Jaccard-bucket identity "Cross-round dedup" below
   uses for `retired[]`/`rejected[]`/`unfounded[]`** — deliberately *not* line-sensitive, for the
   identical reason that section gives: a fix shifts line numbers within the same round, so a
   line-anchored fingerprint would break precisely when a disposition needs to be looked up again.
   **This explicitly overrides `swe-workbench:code-impl`'s standard `status:`/`files_changed:`/
   `concerns:`/`blockers:` output contract for this invocation** — state that override plainly in
   the brief. The per-finding disposition line above is what the orchestrator's ledger parses;
   without the override instruction the agent may default to its own documented contract instead,
   and the round's fixed/unfounded/rejected/deferred accounting would never arrive.

**`UNFOUNDED` is deliberately distinct from `REJECTED`.** `REJECTED` means *the finding is real
and I decline to act on it* (would require weakening a test, out of scope). `UNFOUNDED` means *the
finding's factual premise is false*. Collapsing them would hide the signal that matters most: a
rising `UNFOUNDED` rate is direct evidence the reviewer is degrading, and warrants stopping the
loop and reading the diff yourself. Both feed suppression, but they are counted and reported
separately.

**Zero-edit stop (hard stop).** If a fix pass produces no code changes at all — every finding
`UNFOUNDED`, `REJECTED`, or `DEFERRED` — **stop the loop**, jump to Phase 6. Round N+1 would review
a byte-identical tree and reach the same conclusion, so continuing burns the cap for nothing. This
is the degenerate case of the progress requirement, not a new stop condition, and it is the
failure mode a hallucinating reviewer produces.

## Phase 3b — Escalate to the human (last resort only)

The fixer gets a fifth disposition, `UNVERIFIABLE`, with a hard precondition borrowed in spirit
from `swe-workbench:workflow-grill`: **exhaust the codebase first, escalate only when it is
silent.** Before a finding may be marked `UNVERIFIABLE` the agent must have read the cited code,
followed its definitions and callers, and checked the surrounding tests, docs, and config. Only a
claim the repository *cannot answer* qualifies — one turning on runtime behaviour under real load,
an external service's contract, product or domain intent, or a spec that lives outside the repo.
"I'm not sure" is not `UNVERIFIABLE`; **not settleable from this codebase** is. A finding that is
merely hard to check is `REJECTED` with the reason, not an escalation.

`swe-workbench:code-impl` is a subagent and holds no `AskUserQuestion`, so it **surfaces** the
question in its returned line rather than asking. This command body — running in the orchestrator
— owns the ask:

- **One batched `AskUserQuestion` per round, never one per finding.** Up to 4 findings become the
  4 questions of a single call. Each offers *Real — fix it* / *Not real — drop it* / *Real, don't
  fix now*, with the finding body and the agent's investigation notes as context.
- **More than 4 `UNVERIFIABLE` findings in one round → stop the loop** and jump to Phase 6
  (too-many-unverifiable). At that density the review needs a human reading, not an
  interrogation.
- **Answers are cached in the ledger's `adjudicated[]`, keyed by the same path+Jaccard `fingerprint`
  defined above, and replayed into later rounds' suppression block — the same question is never
  asked twice.** Without this, an unattended 4-round loop would re-ask the same unanswerable thing
  every round.
- Answers map to normal dispositions: *Real* → dispatch a scoped follow-up `swe-workbench:code-impl`
  fix for just that one finding, and record `FIXED` in the ledger only once that follow-up lands —
  never mark a finding `fixed` on the strength of the answer alone, or a human-confirmed real bug
  could satisfy Phase 2's termination predicate with no code ever changed; *Not real* →
  `unfounded[]` with reason `adjudicated by user`; *Don't fix now* → `rejected[]`. All three are
  reported.

This is the only main-thread-only tool in the loop, and deliberately the *rarest* path — reachable
only after a mechanical check and a full codebase investigation have both failed to settle the
claim.

## Phase 4 — Verify + commit round N

Run the **full** test suite for the target repo — never a subset scoped to touched files. **A red
tree ends the loop (hard stop)**: report and jump to Phase 6; do not keep iterating on a broken
build. Also compute `git diff --stat` over test paths for the round and flag a net-negative
test-line delta in the report even when tests pass.

Then commit via `swe-workbench:workflow-commit-and-pr` in **commit** mode (never ship) with
message `[fix] review loop round <N>: <k> findings`.

Immediately after dispositions land in the ledger:

```bash
rm -f "$RUN_DIR/round-${N}-findings.json"
```

The full findings text never outlives the round that consumed it — with no per-round prompt,
nobody is watching to catch a stale file leaking into round N+1.

Increment `N`, update the workflow-state checkpoint, and return to Phase 1. (Phase 2 already
guaranteed `N < CAP` before this fix pass was allowed to run, so no cap check belongs here — the
next round's Phase 2 checks again after its own review.)

## Phase 5 — Deliver (convergence only)

Print the convergence summary, then invoke `swe-workbench:workflow-commit-and-pr` in **ship** mode
— one push, PR create-or-update. That skill owns the draft-vs-ready prompt, the `[type]` format,
PR-template detection, and the `[no ci]` docs-only rule; do not reimplement any of it.
**Non-convergence never pushes.**

The delivery message must state: *"converged after N rounds of automated self-review — not a
substitute for human review or `/swe-workbench:review`."* The reviewer and fixer are the same
model family, so convergence means "this model can no longer find issues in its own output",
which is weaker than "correct". Never let this output be summarized as "reviewed and approved."

## Phase 6 — Terminal reap

One named phase that **all seven exit paths** jump to: converged, cap exhausted, oscillation, red
tree, zero-edit, too-many-unverifiable, parse fault. Not seven copies.

```bash
swe-workbench-reap-run-dir "$RUN_DIR"
[ -e "$RUN_DIR" ] \
  && echo "⚠ run dir NOT reaped: $RUN_DIR" >&2 \
  || echo "✓ run dir reaped: $RUN_DIR"
STATE_FILE="$(git rev-parse --show-toplevel)/.claude/cache/workflow-state/$(git rev-parse --abbrev-ref HEAD | tr '/' '-').json"
rm -f "$STATE_FILE"
[ -e "$STATE_FILE" ] \
  && echo "⚠ workflow-state file NOT reaped: $STATE_FILE" >&2 \
  || echo "✓ workflow-state file reaped: $STATE_FILE"
```

## Cross-round dedup, without GitHub's thread dedup

> A finding matches a ledger entry when **same normalized path** AND **Jaccard ≥ 0.4** over body
> tokens.

Reuses the repo's existing dedup semantics (`skills/workflow-pr-review-post/SKILL.md`) minus the
±5-line component — local fixes shift line numbers *within* a round, so a line-sensitive
fingerprint would fail precisely when it matters most. Same Jaccard threshold means one dedup
concept in the repo, not two.

Each round's reviewer brief carries a suppression block built from the ledger: `retired[]` ("do
not re-report unless the code at this location changed since round k"), `rejected[]` ("do not
re-report; the reason is …"), and `unfounded[]` ("this was checked against the actual code and the
premise was false; here is what is actually there — do not re-report"). Carrying the *evidence*
rather than a bare "don't" is what stops the same hallucination recurring, since the reviewer would
otherwise re-derive it from the same diff every round.

**Never silently drop a suppressed finding** — a match against `rejected[]` or `unfounded[]` is
filtered out of the fixer brief but counted and printed under "suppressed by prior rejection" /
"suppressed as previously unfounded". Silent suppression is how a genuinely new bug at an
already-rejected path disappears.

**Oscillation detector.** A round-N finding matching `retired[]` means something previously fixed
came back. Stop immediately — jump to Phase 6 (oscillation) without burning the remaining cap —
and report *"regression: finding X was fixed in round 2 and reappeared in round 4."* The ledger
already holds this; the check is free.

## Cap and the loop invariant

**`MAX_REVIEWS = 4`** by default (≤3 fix passes), overridable via `--cap 2..6`. The cap counts
**reviews, not rounds** — worth stating explicitly: **the loop always ends on a review, never on a
fix** — every applied fix has been re-reviewed. A cap counting fixes would let the loop exit having
just applied unverified edits.

Four rather than ten because each round is a reviewer agent + an implementer agent + a full test
run, and reviewer non-determinism makes rounds 4+ mostly noise. Wall-clock is unenforceable in a
model-driven loop, so the honest second budget is the human's Esc — print a one-line progress
marker every round so the user knows when to use it: `Round 2/4 — review: 5 findings above floor`.

**Watched signal, not a stop condition:** print a warning when `UNFOUNDED` exceeds half a round's
anchor-valid findings — *"round 3: 4 of 6 findings did not hold against the code; treat this
round's review as low-signal."* Deliberately not a sixth stop condition — the zero-edit stop
already catches the terminal case.

## Non-convergence report shape

```
Review loop stopped: <cap exhausted after 4 reviews | oscillation | tests red | no edits produced | too many unverifiable | parse fault>
Rounds: 4  Fixed: 11  Rejected: 3  Unfounded: 2  Adjudicated by you: 1  Suppressed: 1  Remaining ≥Medium: 2
Remaining:
  High   | src/foo.ts:42 | <body>   (first seen round 1; re-reported 2, 3, 4)
Rejected by fixer:
  Medium | src/bar.ts:9  | <body> — reason: <fixer's reason>
Unfounded (claim did not hold against the code):
  High   | src/baz.ts:7  | <body> — actually: <what is at that line>
Out of branch diff (not acted on): 4
Residual Low (below floor): 5
Local commits: 3 — NOT pushed.
Next: /swe-workbench:review to inspect manually, or ship deliberately.
```
