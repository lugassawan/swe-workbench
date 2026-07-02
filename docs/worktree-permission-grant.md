# Worktree permission-grant hook

When rimba creates a new git worktree it copies `.claude/` into it, including `settings.local.json`.  That file lists `Read(...)`, `Edit(...)`, and `Write(...)` allow entries — but their paths are absolute and pinned to the *original* worktree.  Claude Code's harness therefore re-prompts on every file operation in the new worktree, because none of the old paths match.

The `worktree_permission_grant.sh` hook eliminates that friction by re-interpreting each allow entry at runtime against the *current* worktree.

## How it works

A single `PreToolUse` hook fires on `Read`, `Edit`, and `Write` tool calls:

| Hook | Script | Matcher |
|---|---|---|
| `PreToolUse:Read\|Edit\|Write` | `hooks/worktree_permission_grant.sh` | `Read\|Edit\|Write` |

For each call the hook:

1. Extracts `tool_name` and `tool_input.file_path` from the hook payload.
2. Rejects paths containing `..` (traversal guard).
3. Confirms the session is in a **linked** worktree (main checkouts fall through to native handling).
4. Reads `.claude/settings.local.json` from the worktree root.
5. For each allow entry whose tool prefix matches:
   - **Absolute sibling entry** (`//path/to/other-worktree/**`): remaps to the equivalent path inside the *current* worktree.
   - **Absolute same-tree entry** (`//path/to/current-worktree/**`): used as-is.
   - **Relative entry** (`skills/**`): matched directly against the project-relative file path.
   - **Unrelated absolute entry** (`//tmp/x/**`): skipped.
6. On a match: emits `permissionDecision: "allow"` and exits.
7. No match: exits with no output — the harness prompts as usual.

The hook never emits `exit 2` (which would *deny* the call).  Any error exits 0 (fail-open → normal harness prompt).

## Sibling-worktree remapping

rimba places all worktrees under a shared parent directory:

```
swe-workbench-worktrees/
  chore-old-task/      ← prior worktree (allow entries pinned here)
  chore-new-task/      ← current session
```

An allow entry `Read(//…/swe-workbench-worktrees/chore-old-task/**)` is rewritten to `**` (the whole tree) relative to `chore-new-task/` — so reads in the new worktree are granted without re-prompting.  Sub-path entries like `Read(//…/chore-old-task/skills/**)` are similarly narrowed: only `skills/**` inside the new worktree is allowed.

## Security boundaries

| Boundary | Enforcement |
|---|---|
| Linked worktrees only | `git rev-parse --absolute-git-dir` must contain `.git/worktrees/` |
| Files under worktree root only | String-prefix check AND `python3 os.path.realpath` resolves symlinks; resolved path must also be under `wt_root` |
| No `..` traversal | Pattern `*/../*\|*/..\|../*\|..` checked before any git call |
| No committed `settings.json` | Only `settings.local.json` (gitignored, user-authored) is read |
| Unrelated absolute paths skipped | Must be under `wt_root` or a recognized sibling directory |

## Manual smoke test

After creating a worktree with rimba (`rimba add <task>`):

1. Open a file in the new worktree — `Read` should **not** prompt if `settings.local.json` has a matching `Read(...)` entry from a previous worktree.
2. Edit a file — still prompts (no `Edit(...)` whole-tree grant exists by default).
3. Run `shellcheck hooks/worktree_permission_grant.sh` — should report 0 issues.

## Troubleshooting

**Still getting Read prompts after entering a worktree:**

- Confirm `.claude/settings.local.json` was copied (rimba `copy_files = ['.claude']`).
- Confirm it contains a `Read(...)` entry for a path that remaps to the worktree.
- Confirm the session is in a linked worktree, not the main checkout: `git rev-parse --absolute-git-dir` should show a path containing `.git/worktrees/`.

**Hook never fires:**

- Confirm `CLAUDE_PLUGIN_ROOT` is set and `hooks/hooks.json` contains the `Read|Edit|Write` entry.
- Run `bash scripts/validate.sh` to verify hooks.json schema.
