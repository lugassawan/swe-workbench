# Cleanup with a foreign primary lease

Use this route only when Step 3's checked handoff preflight marks the primary unsafe. It preserves the foreign lease and primary files while removing only the sealed merged-PR target.

## Classify before exit

While still in the target, resolve both roots canonically. `git worktree list --porcelain` lists the primary first; normalize that root and `git rev-parse --show-toplevel` before comparing either to `.data.leases[].worktree_root` from the checked preflight result.

A missing primary row is safe. A row is safe only when both `owner_harness` and `receiver_session_ref` exactly identify this harness and session. Treat a `released` owner, another harness, another session, malformed data, or any failed list/checker result as unsafe. Do not infer safety from a checkpoint status.

## Deferred-verification choice

Before preparation, inspect the merged PR body already fetched in Step 2. If it has the deferred-verification marker, offer only **File a follow-up issue** (`file_issue`) or **Skip** (`skip`). Do not offer a test branch: target removal makes that ordinary Step 8 option unavailable. With no marker, use `not_required`.

## Prepare

Prepare from the target with the selected fixed choice, then read the checked request id before exit:

```bash
PREPARED=$(swe-workbench-cleanup-merged prepare --pr "$NUMBER" --repo "$OWNER/$REPO" --as claude --session-ref-env CLAUDE_CODE_SESSION_ID --deferred-follow-up file_issue | swe-workbench-result-check swb.cleanup-merged/1) || exit 1
printf '%s' "$PREPARED" | jq -r '.data.request_id'
```

For Pi, use `--as pi --session-ref-env PI_SESSION_ID`; use `skip` or `not_required` when selected. Read the printed UUID into the agent's context. It is an opaque capability, not a value to interpolate in a later shell command.

## Exit and execute

Call `ExitWorktree(action=keep)`. The very next Bash call must be exactly one checked execute pipeline, with the UUID copied into the command as a literal. Replace the example UUID with the actual returned UUID before issuing the call; never use a shell variable, command substitution, or an extra shell call.

```bash
swe-workbench-cleanup-merged execute --request 123e4567-e89b-12d3-a456-426614174000 --as claude --session-ref-env CLAUDE_CODE_SESSION_ID | swe-workbench-result-check swb.cleanup-merged/1
```

For Pi, the exact alternative is:

```bash
swe-workbench-cleanup-merged execute --request 123e4567-e89b-12d3-a456-426614174000 --as pi --session-ref-env PI_SESSION_ID | swe-workbench-result-check swb.cleanup-merged/1
```

The primary's foreign lease permits only this sealed command shape. After it returns, do not issue another Bash call from the blocked primary. The cleanup runtime works from its child cwd and removes the sealed target; it never checks out, pulls, or otherwise changes primary main. In Pi, execution can finish from the target through that child cwd, but the terminal session is not reanchored after target removal.

## Report

Render the checked execute envelope already returned by that Bash call; do not shell out to inspect it. Report `worktree_removed`, `residual_none`, `local_branch_deleted`, and `remote_branch_deleted` as the target cleanup outcomes, then state `main_sync_skipped: true` as `sync skipped — foreign primary lease`. The response is target-specific, so it does not invent global worktree counts.

## Failure and retry

The main sync is intentionally skipped, but merge validation, target cleanliness, lease protection, ordered removal, residual sweep, and branch deletion remain enforced by the sealed request. Preparation or execution failure is fail-closed: do not use rimba cleanup, shell fallback, bulk cleanup, a helper worktree, or a manual fresh session. Retry an interrupted or failed execution with the same prepared request ID; its journal makes the ordered target cleanup resumable.
