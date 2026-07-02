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
- **`DIRTY>0`**: offer **stash-or-abort** before touching history — `git stash push -u -m "branch-sync: pre-sync stash"` if the user opts to stash, otherwise stop and let the user commit or discard first. Never proceed with a dirty tree.

### Step 2 — Overlap Advisory (optional)

If the rimba MCP server is active in the session, invoke its `conflict-check` tool with `dry_merge: true` as an **informational heads-up only** — it detects cross-worktree file overlaps between rimba-managed worktrees, not the authoritative conflict set for this sync. Surface any overlap it reports, but never block or skip Step 3 on its account. Skip silently if rimba MCP is not active.

### Step 3 — Mechanical Sync

**Resolve strategy** from the invoking command: default is **merge**; `--rebase` selects **rebase**.

**Derive the task identifier** for rimba from `CURRENT_BRANCH` by stripping a known type prefix (`feature/`, `bugfix/`, `hotfix/`, `docs/`, `test/`, `chore/`) if present; otherwise use `CURRENT_BRANCH` as-is.

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

`no_push: true` / `--no-push` is passed **always**, regardless of strategy — the push happens only in Step 6, only if the user opts in.

- **rimba MCP server active** → invoke the `sync` tool with the table above.
- **`$RIMBA` non-empty (binary found) AND the current worktree is a rimba-managed task worktree** → run the table's binary form.
- **rimba absent, OR the current branch/worktree was not created by rimba** → shell fallback:
  ```bash
  git fetch origin "$DEFAULT_BRANCH"
  git merge origin/"$DEFAULT_BRANCH"     # default (merge)
  # or, under --rebase:
  git rebase origin/"$DEFAULT_BRANCH"
  ```

### Step 4 — Detect Result

```bash
eval "$("$_SCRIPTS/detect-conflicts.sh" | head -1)"
UNMERGED=$("$_SCRIPTS/detect-conflicts.sh" | tail -n +2)
```

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
   - **manual**: open the file in place for the user to edit, wait for confirmation, then `git add "<file>"`.

After every file in `UNMERGED` has been resolved and staged:

- **`OPERATION=merge`** → `git commit --no-edit`.
- **`OPERATION=rebase`** → `git rebase --continue`. **A rebase can pause again on the next replayed commit** — re-run Step 4 (`detect-conflicts.sh`) and loop back into Step 5 if `OPERATION=rebase` with a fresh `UNMERGED` list. Only proceed to Step 6 once `git rebase --continue` completes the rebase entirely.

### Step 6 — Leave Local & Prompt Before Push

Report the resolution summary: one line per file — which side was kept (or "manual") and the one-line rationale from Step 5. **Never auto-push.**

Prompt: "Sync complete locally on `$CURRENT_BRANCH`. Push now?"

- **Yes, and `OPERATION` was `merge`** → `git push`.
- **Yes, and `OPERATION` was `rebase`** → `git push --force-with-lease`. Force-push surfaces **only** here, under `--rebase` — never anywhere else in this skill.
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
| Push requested after a rebase without `--force-with-lease` | N/A — this skill always uses `--force-with-lease` under rebase | N/A — documented so a future edit doesn't regress to plain `--force`. |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treat `--ours`/`--theirs` as the user's "mine"/"main" intent directly | Never. Under a **merge**, `--ours` = HEAD (your branch, "mine"), `--theirs` = the incoming default branch ("main"). Under a **rebase**, git inverts this: `--ours` = the rebase target ("main"), `--theirs` = your replayed commits ("mine"). Always route through `apply-resolution.sh`, which does this translation — never call `git checkout --ours/--theirs` inline. |
| Assume `mcp__rimba__sync` defaults match this skill's defaults | They don't. rimba's `sync` **rebases by default** (pass `merge: true` for merge) and **pushes by default** (pass `no_push: true` to suppress it). This skill defaults to **merge** and **never** auto-pushes. Always pass `no_push: true` / `--no-push` regardless of strategy. |
| Hardcode `main` as the default branch | Never. `preflight-guard.sh` detects `DEFAULT_BRANCH` via `gh repo view` with a `git symbolic-ref` fallback — the plugin runs against arbitrary repos. |
| Treat the first `git rebase --continue` as "done" | A rebase replays one commit at a time and can pause again on the very next one. Re-run `detect-conflicts.sh` after every `--continue` and loop back into Step 5 until `OPERATION=none`. |
| Resolve a file without showing both sides | Always present both sides plus the `conflict-resolver` subagent's per-hunk rationale before prompting keep-mine/keep-main/manual — resolving is review-and-confirm, not a guess. |
| Push automatically once conflicts are resolved | Never. Step 6 always stops and prompts — the result is left local until the user explicitly opts in. |
| Use plain `git push --force` after a rebase | Always `--force-with-lease` — it aborts if the remote moved since the last fetch, instead of silently clobbering someone else's push. |
