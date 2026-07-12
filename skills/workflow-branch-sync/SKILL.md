---
name: workflow-branch-sync
description: Sync the current branch with the default branch via rimba or git, then resolve conflicts file by file with a per-hunk rationale and a keep-mine / keep-main / manual recommendation before staging. Push only happens after explicit confirmation — never automatic.
orchestrator: true
---

# Workflow: Branch Sync

**Announce at start:** "I'm using the workflow-branch-sync skill to bring this branch up to date and help resolve any conflicts."

## When to Invoke

- User's branch has fallen behind the default branch and they want it brought up to date.
- User asks for help resolving merge/rebase conflicts, or wants guidance on "which side is correct".
- Invoked by `/swe-workbench:sync`.

## What This Skill Does NOT Do

- Does not open, merge, or comment on a PR — that is `workflow-commit-and-pr` / the user's action.
- Does not resolve any conflict without first showing both sides and a recommendation with rationale.
- Does not auto-push — ever. The push is a separate, explicitly prompted step at the end.
- Does not rewrite history beyond the single merge or rebase the user asked for.

## Sync Contract

### Step 1 — Preflight Guard

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
_SCRIPTS="$_RT/skills/workflow-branch-sync/scripts"
eval "$("$_SCRIPTS/preflight-guard.sh")"
```

Emits `CURRENT_BRANCH`, `DEFAULT_BRANCH` (detected — never hardcode `main`), `IS_DEFAULT`, `DETACHED`, `DIRTY`.

- **`IS_DEFAULT=1`**: refuse. Report "already on `$DEFAULT_BRANCH` — nothing to sync onto itself" and stop.
- **`DETACHED=1`**: refuse. Report "detached HEAD — checkout a branch first" and stop.
- **`DIRTY>0`**: offer **stash-or-abort** before touching history — `git stash push -u -m "branch-sync: pre-sync stash"` if the user opts to stash, otherwise stop and let the user commit or discard first. Never proceed with a dirty tree. If the user stashes, set `STASHED=1` — Step 7 restores it before reporting.

### Step 2 — Overlap Advisory (optional)

If the rimba MCP server is active in the session, invoke its `conflict-check` tool with `dry_merge: true` as an **informational heads-up only** — it detects cross-worktree file overlaps between rimba-managed worktrees, not the authoritative conflict set for this sync. Surface any overlap it reports, but never block or skip Step 3 on its account. Skip silently if rimba MCP is not active.

### Step 3 — Mechanical Sync

**Resolve strategy** from the invoking command into `SYNC_STRATEGY=merge|rebase` — default is **merge**; `--rebase` selects **rebase**. Keep `SYNC_STRATEGY` separate from `OPERATION` (Step 4): `OPERATION` means "conflict resolution currently in progress" (and is `none` on a clean sync — the common case), not "which strategy was used." Step 7's push branching reads `SYNC_STRATEGY`, never `OPERATION`.

**Resolve the redundancy flag** from the invoking command into `CHECK_REDUNDANCY=on|off` — default is **off**; `--check-redundancy` selects **on**. This gates the optional Step 6 assessment below; plain `sync` (flag absent) is byte-for-byte unchanged from today.

**When `CHECK_REDUNDANCY=on`, capture the merge-base baseline now — before the mechanical sync below runs:**

```bash
if [ "$CHECK_REDUNDANCY" = "on" ]; then
  MERGE_BASE=$(git merge-base HEAD "origin/$DEFAULT_BRANCH" 2>/dev/null || true)
  PRE_SYNC_HEAD=$(git rev-parse HEAD)
fi
```

This capture must happen **before** the sync, never after: once the mechanical sync below completes (merge or rebase), HEAD contains the default branch's tip, and `git merge-base HEAD origin/$DEFAULT_BRANCH` collapses to the default branch itself — silently losing the branch's own additions that Step 6 needs to diff against. `MERGE_BASE` comes back empty for unrelated-history repos; Step 6 skips gracefully in that case. When `CHECK_REDUNDANCY=off`, skip this capture entirely — no cost on the common path.

**Derive the task identifier** for rimba from `CURRENT_BRANCH` by stripping a known type prefix (`feature/`, `bugfix/`, `fix/`, `hotfix/`, `docs/`, `test/`, `chore/`) if present — `fix/` is accepted as an input alias for hand-named branches even though rimba's canonical output prefix is `bugfix/`; otherwise use `CURRENT_BRANCH` as-is.

**Provider detection** (mirror the rimba MCP → binary → shell ordering of `skills/workflow-development/SKILL.md`):

```bash
RIMBA=$(command -v rimba 2>/dev/null \
  || { [ -x "$HOME/.local/bin/rimba" ] && echo "$HOME/.local/bin/rimba"; } \
  || { [ -x "$HOME/go/bin/rimba" ]     && echo "$HOME/go/bin/rimba"; } \
  || true)
```

**rimba's defaults are the inverse of this skill's, and rimba pushes by default — both must be translated on every call:**

| `/swe-workbench:sync` strategy | rimba MCP `sync` call | rimba binary call |
|---|---|---|
| default (merge) | `{task, merge: true, no_push: true}` | `rimba sync <task> --merge --no-push` |
| `--rebase` | `{task, no_push: true}` (rebase is rimba's default) | `rimba sync <task> --no-push` |

`no_push: true` / `--no-push` is passed **always**, regardless of strategy — the push happens only in Step 7, only if the user opts in.

**Try rimba first, fall back on "not a rimba worktree" — never pre-check.** Whether the current branch is a rimba-managed task worktree is not knowable in advance without an extra round-trip; instead, attempt the call and read the failure:

- **rimba MCP server active** → invoke the `sync` tool with the table above. If it errors indicating the worktree/task was not found, fall through to the shell fallback below.
- **`$RIMBA` non-empty (binary found)** → run the table's binary form. The binary exits non-zero with `Error: worktree not found for task "<task>"` when `CURRENT_BRANCH`'s derived task isn't a rimba-managed worktree — on exactly that message, fall through to the shell fallback below. Any other non-zero exit is a real sync failure (see Failure Mode Table) and must not fall through.
- **rimba absent, or the rimba call above fell through on "worktree not found"** → shell fallback:
  ```bash
  git fetch origin "$DEFAULT_BRANCH"
  git merge origin/"$DEFAULT_BRANCH"     # default (merge)
  # or, under --rebase:
  git rebase origin/"$DEFAULT_BRANCH"
  ```

### Step 4 — Detect Result

```bash
_DETECT_OUT="$("$_SCRIPTS/detect-conflicts.sh")"
eval "$(head -1 <<<"$_DETECT_OUT")"
UNMERGED=$(tail -n +2 <<<"$_DETECT_OUT")
```

Capture the script's output **once** into `_DETECT_OUT`, then split it — do not invoke `detect-conflicts.sh` twice; a second `git diff --diff-filter=U` call could observe different repo state if anything mutates the index between the two calls.

`OPERATION` is `merge`, `rebase`, or `none` (via `.git/MERGE_HEAD` vs `.git/rebase-merge`/`.git/rebase-apply`). `UNMERGED` lists conflicted paths, one per line, from `git diff --name-only --diff-filter=U` — treat these as **raw file paths, never eval them**.

- **`OPERATION=none`**: clean sync (fast-forward or no-conflict merge/rebase). Skip to Step 6.
- **`OPERATION=merge` or `rebase`** with a non-empty `UNMERGED` list: proceed to Step 5.

### Step 5 — Interactive Resolve Loop

For **each** file in `UNMERGED`:

1. Dispatch the `conflict-resolver` subagent with the file path, `OPERATION`, and the conflicted content (both sides, retrievable via `git show :2:<file>` / `git show :3:<file>` for a merge, or the equivalent staged blobs during a rebase — the subagent may also use `git log`/`git blame` on both sides for judgement).
2. Present the subagent's per-hunk rationale and its file-level recommendation to the user, alongside both sides' content.
3. Prompt for one of: **keep-mine**, **keep-main**, **manual**.
   - **keep-mine / keep-main**: apply via
     ```bash
     "$_SCRIPTS/apply-resolution.sh" "<file>" "<mine|main>" "<merge|rebase>"
     ```
     This script does the ours/theirs translation (see Common Mistakes) and stages the file — do not call `git checkout --ours/--theirs` directly from this skill.
   - **manual**: open the file in place for the user to edit, wait for confirmation. Before staging, verify no conflict markers remain: `grep -qE '^(<{7}|={7}|>{7})' "<file>"` must find **nothing**. If a marker is still present, do not stage — warn the user and re-prompt for confirmation instead of silently committing broken content. Once clean, `git add "<file>"`.

After every file in `UNMERGED` has been resolved and staged:

- **`OPERATION=merge`** → `git commit --no-edit`.
- **`OPERATION=rebase`** → `git rebase --continue`. **A rebase can pause again on the next replayed commit** — re-run Step 4 (`detect-conflicts.sh`) and loop back into Step 5 if `OPERATION=rebase` with a fresh `UNMERGED` list. Only proceed to Step 6 once `git rebase --continue` completes the rebase entirely.

### Step 6 — Redundancy Assessment (opt-in, flag-gated)

Surfaces *functional* duplication a textual diff structurally cannot see — the branch adding a function or file that the default branch independently grew elsewhere (renamed or relocated), which git reports as no conflict at all.

1. **Skip conditions** — check in order:
   - `CHECK_REDUNDANCY` is `off` → skip this step entirely, proceed straight to Step 7. This is the default; plain `sync` never reaches here.
   - `CHECK_REDUNDANCY=on` but `MERGE_BASE` came back empty from Step 3 (unrelated histories) → report "redundancy check skipped: unrelated histories" and proceed to Step 7.
2. **Gather** (deterministic):
   ```bash
   _REDUND_OUT="$("$_SCRIPTS/redundancy-scope.sh" "$MERGE_BASE" "$PRE_SYNC_HEAD" "origin/$DEFAULT_BRANCH")"
   eval "$(grep -E '^(MERGE_BASE|CANDIDATES)=' <<<"$_REDUND_OUT")"
   ```
   Only the plain `MERGE_BASE=`/`CANDIDATES=` scalar lines are eval-safe and get eval'd here — the `CANDIDATE`/`MAIN_ADD` records are structured, not simple `KEY=VALUE`, and are parsed as data below, never eval'd. If `CANDIDATES=0`, report "no redundancy candidates found" and proceed to Step 7 — never dispatch the subagent for zero candidates.
3. **Reason** (advisory, never mutates): dispatch the `swe-workbench:redundancy-assessor` subagent with the full `_REDUND_OUT` (every `CANDIDATE`/`MAIN_ADD` record) and the `MERGE_BASE..PRE_SYNC_HEAD` branch diff.
4. **Validate before acting** — this is the load-bearing invariant of this step: the skill never trusts the subagent's free-text for an actionable path **or for the tier label itself**. Parse each `**Redundancy: AUTO-APPLY|ESCALATE|NONE** id=<n>` sentinel it emits, cross-check every `id` against the enumerated `CANDIDATE id=<n>` lines `redundancy-scope.sh` produced, and **reject any id the script did not enumerate** — never act on an agent-invented id. The actionable file path always comes from the script's own `CANDIDATE path=<p>` record for that id, never from the subagent's prose. **For every `AUTO-APPLY` sentinel specifically**, also re-derive that same id's `refs=<count>` from its `CANDIDATE` line and **downgrade the finding to `ESCALATE` if `refs` is nonzero** — the `AUTO-APPLY` label is still the subagent's free text; only the script's own `refs` count is authoritative for the auto-apply precondition, and a subagent that mislabels a referenced or symbol-level candidate as `AUTO-APPLY` must never bypass the human because of it.
5. **Tiered gate** — per validated (and, for `AUTO-APPLY`, refs-downgrade-checked) finding:
   - `NONE` → no action.
   - `AUTO-APPLY` (re-validated in step 4 as a whole-file candidate with `refs=0` — never taken on the subagent's label alone) → `git rm <script-path>`, stage, then `git commit -m "[refactor] drop redundant <path>, superseded by main"`. List this commit explicitly in the Step 7 summary — that's the human-eyeball moment the never-auto-push gate exists for.
   - `ESCALATE` → present the subagent's rationale, its recommendation (Remove / Keep-as-is / Edit-manually), and the superseding evidence; prompt the user for one of **Remove**, **Keep**, **Edit**. Remove → same `git rm` + `[refactor]` commit as AUTO-APPLY. Edit → open the file for the user, wait for confirmation, then stage whatever they leave behind and commit with `git commit -m "[refactor] resolve redundant <path> (manual edit)"` — an Edit that only stages and never commits would never reach Step 7's push and would silently vanish from the summary below. Keep → no-op.
6. The subagent never stages or commits anything itself — every mutation above is this skill's action, gated exactly like Step 5's resolve loop. Nothing here pushes; only Step 7 pushes, and only on explicit confirmation.

### Step 7 — Leave Local & Prompt Before Push

**If `STASHED=1`** (Step 1 stashed a dirty tree), restore it now, before reporting: `git stash pop`.
- **Pop succeeds cleanly** → note it in the resolution summary ("Restored N file(s) from the pre-sync stash").
- **Pop conflicts** → surface it exactly like a file conflict from Step 5 (show both sides, let the user resolve, `git add` the resolved files), then `git stash drop` once resolved — a conflicting pop leaves the stash entry in place rather than consuming it, so an explicit drop is required after manual resolution.

Report the resolution summary: one line per file — which side was kept (or "manual") and the one-line rationale from Step 5, plus one line per Step 6 `[refactor]` commit (auto-applied or user-confirmed removal), if any. **Never auto-push.**

Prompt: "Sync complete locally on `$CURRENT_BRANCH`. Push now?"

- **Yes, and `SYNC_STRATEGY` was `merge`** → `git push`.
- **Yes, and `SYNC_STRATEGY` was `rebase`** → `git push --force-with-lease`. Force-push surfaces **only** here, under `--rebase` — never anywhere else in this skill. This branches on `SYNC_STRATEGY`, not `OPERATION` — `OPERATION` is `none` for the common clean-sync case and would otherwise leave a `--rebase` sync with no push path at all.
- **No** → stop. The result stays local; the user pushes later at their own discretion (follow `workflow-commit-and-pr` push conventions if they ask for help with that later — this is an async handoff, not this skill's job to chase).

## Failure Mode Table

| Failure | Signal | Action |
|---------|--------|--------|
| Already on default branch | `IS_DEFAULT=1` | Refuse. Nothing to sync onto itself. |
| Detached HEAD | `DETACHED=1` | Refuse. Ask the user to checkout a branch first. |
| Dirty working tree | `DIRTY>0` | Offer stash-or-abort before touching history. Never proceed dirty. |
| Mechanical sync itself fails (not a conflict — e.g. network) | Non-zero exit from `rimba sync` / `git fetch` / `git merge` / `git rebase` with no `MERGE_HEAD`/`rebase-merge` present | Report the error verbatim. Do not enter the resolve loop. |
| `conflict-resolver` subagent cannot form a confident recommendation | Subagent emits `**Resolution: MANUAL**` | Route to the manual path — never force a keep-mine/keep-main guess. |
| Rebase pauses again after `git rebase --continue` | Fresh `OPERATION=rebase` with non-empty `UNMERGED` from Step 4 | Loop back into Step 5. Do not treat the first `--continue` as completion. |
| User declines to stash a dirty tree | User says no at Step 1 | Abort. Do not force-stash. |
| rimba worktree but binary/MCP both unavailable mid-session | `$RIMBA` empty and MCP not active | Fall through to the shell fallback — never block on rimba's absence. |
| Derived task isn't a rimba-managed worktree | `Error: worktree not found for task "<task>"` from the rimba binary (or the MCP equivalent) | Fall through to the shell fallback — this is expected for branches not created via `rimba add`, not a sync failure. |
| A conflicting file was deleted on the chosen side | `apply-resolution.sh` reports `git checkout` failed with "does not have our/their version" | Handled in-script: resolves as `git rm` instead of aborting — no skill-level action needed. |
| Push requested after a rebase without `--force-with-lease` | N/A — this skill always uses `--force-with-lease` under rebase | N/A — documented so a future edit doesn't regress to plain `--force`. |
| Clean sync with `SYNC_STRATEGY=rebase` has no push path | N/A — this skill branches Step 7 on `SYNC_STRATEGY`, not `OPERATION` (which is `none` on a clean sync) | N/A — documented so a future edit doesn't regress to reading `OPERATION` for push branching. |
| Pre-sync stash pop conflicts | `git stash pop` reports a conflict in Step 7 | Surface exactly like a Step 5 file conflict — show both sides, let the user resolve, `git add`, then `git stash drop` (a conflicting pop leaves the stash entry in place rather than consuming it). |
| `--check-redundancy` requested on an unrelated-history repo | `MERGE_BASE` comes back empty from Step 3's capture | Skip Step 6 with a one-line reason ("unrelated histories") — never crash, never treat this as a sync failure. |
| `redundancy-assessor` emits an id `redundancy-scope.sh` never enumerated | Sentinel `id=<n>` with no matching `CANDIDATE id=<n>` line in `_REDUND_OUT` | Reject the finding outright — never act on an unvalidated id, regardless of how plausible its accompanying prose looks. |
| `redundancy-assessor` labels a `refs>0` or symbol-level candidate `AUTO-APPLY` | That id's own `CANDIDATE ... refs=<count>` line in `_REDUND_OUT` shows `refs` nonzero despite an `AUTO-APPLY` sentinel | Downgrade to `ESCALATE` before the tiered gate runs — the tier label is agent free text too, not just the path/id; never bypass the human because of a mislabeled tier. |
| `redundancy-scope.sh` enumerated a candidate but `redundancy-assessor` never emitted a sentinel for its id | A `CANDIDATE id=<n>` line in `_REDUND_OUT` with no matching `**Redundancy: …** id=<n>` in the subagent's output | Treat that candidate as unresolved — do not assume `NONE`, do not act on it. Report it to the user alongside the resolved findings. |
| A branch and main both add the identical path (add/add conflict) | The path already appeared in Step 5's resolved `UNMERGED` list, yet also surfaces as a Step 6 `CANDIDATE` | Narrow overlap: the two steps can disagree since Step 6 reasons independently. Prefer the Step 5 resolution — Step 5's keep-mine/keep-main choice for a path already-resolved there takes precedence over a same-path Step 6 finding. |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treat `--ours`/`--theirs` as the user's "mine"/"main" intent directly | Never. Under a **merge**, `--ours` = HEAD (your branch, "mine"), `--theirs` = the incoming default branch ("main"). Under a **rebase**, git inverts this: `--ours` = the rebase target ("main"), `--theirs` = your replayed commits ("mine"). Always route through `apply-resolution.sh`, which does this translation — never call `git checkout --ours/--theirs` inline. |
| Assume `mcp__rimba__sync` defaults match this skill's defaults | They don't. rimba's `sync` **rebases by default** (pass `merge: true` for merge) and **pushes by default** (pass `no_push: true` to suppress it). This skill defaults to **merge** and **never** auto-pushes. Always pass `no_push: true` / `--no-push` regardless of strategy. |
| Hardcode `main` as the default branch | Never. `preflight-guard.sh` detects `DEFAULT_BRANCH` via `gh repo view` with a `git symbolic-ref` fallback — the plugin runs against arbitrary repos. |
| Treat the first `git rebase --continue` as "done" | A rebase replays one commit at a time and can pause again on the very next one. Re-run `detect-conflicts.sh` after every `--continue` and loop back into Step 5 until `OPERATION=none`. |
| Resolve a file without showing both sides | Always present both sides plus the `conflict-resolver` subagent's per-hunk rationale before prompting keep-mine/keep-main/manual — resolving is review-and-confirm, not a guess. |
| Push automatically once conflicts are resolved | Never. Step 7 always stops and prompts — the result is left local until the user explicitly opts in. |
| Use plain `git push --force` after a rebase | Always `--force-with-lease` — it aborts if the remote moved since the last fetch, instead of silently clobbering someone else's push. |
| Stage a manually-edited file on confirmation alone | Grep for `<<<<<<<`/`=======`/`>>>>>>>` markers first — a premature confirmation or a missed hunk can leave literal conflict-marker text in the file, which stages and commits broken content. |
| Pre-check whether the branch is "a rimba worktree" before calling `rimba sync` | Don't — try the call and read the failure. The binary's `Error: worktree not found for task "<task>"` (or the MCP equivalent) is the signal to fall through to shell, not an upfront probe. |
| Branch Step 7's push logic on `OPERATION` | Don't — `OPERATION` is `none` on a clean sync (the common case), so an `OPERATION`-keyed branch has no path for a clean `--rebase` sync's required `--force-with-lease` push. Capture the resolved strategy into `SYNC_STRATEGY` in Step 3 and branch Step 7 on that instead. |
| Leave a pre-sync stash unpopped after a successful sync | Always attempt `git stash pop` at the start of Step 7 when `STASHED=1` — a forgotten stash silently parks the user's uncommitted work indefinitely across repeated syncs. |
| Run the Step 6 redundancy assessment on every sync | Don't — it's opt-in via `--check-redundancy`; default `CHECK_REDUNDANCY=off` means plain `sync` never reaches Step 6 and stays byte-for-byte unchanged. |
| Trust the `redundancy-assessor` subagent's id or path text directly | Don't — always resolve the actionable path from `redundancy-scope.sh`'s own `CANDIDATE` record for that id, and reject any id the script didn't enumerate. The skill never evals or trusts agent free-text for an actionable path. |
| Trust an `AUTO-APPLY` sentinel's tier label at face value | Don't — the tier label is still the subagent's free text. Re-derive that id's own `refs=<count>` from the script's `CANDIDATE` line and downgrade to `ESCALATE` if nonzero, before the tiered gate acts. |
| Auto-apply a symbol-level or referenced (`refs>0`) redundancy finding | Don't — Step 6's tiered gate permits `AUTO-APPLY` only for whole-file, `refs=0` candidates; anything else escalates to the user regardless of the subagent's confidence. |
