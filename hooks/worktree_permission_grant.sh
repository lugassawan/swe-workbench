#!/usr/bin/env bash
# PreToolUse:Read|Edit|Write handler — grants permissions for file ops inside
# the current git linked worktree when the worktree's own
# .claude/settings.local.json permits them.
#
# Never blocks: exit 0 always, never exit 2.  Any error → fail-open (no grant,
# normal harness prompt).  Grants are limited to files under the worktree root.
set -u

input=$(cat)

# Fail-open on any jq parse error
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null) || exit 0
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0

[ -z "$tool_name" ] && exit 0
[ -z "$file_path" ] && exit 0

# Resolve to an absolute path.  Read/Edit/Write always supply absolute paths in
# Claude Code, but handle the relative case gracefully via the cwd field.
case "$file_path" in
    /*)
        file_abs="$file_path"
        ;;
    *)
        cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || exit 0
        [ -z "$cwd" ] && exit 0
        file_abs="$cwd/$file_path"
        ;;
esac

# Reject paths containing a .. segment (refuse to reason about traversal).
case "$file_abs" in
    */../*|*/..|../*|..)
        exit 0
        ;;
esac

# Determine git context from the file's own directory (no reliance on cwd in
# the hook payload, which is absent for file-op tools per CC internals).
file_dir=$(dirname "$file_abs")
git_dir=$(git -C "$file_dir" rev-parse --absolute-git-dir 2>/dev/null) || exit 0

# Only act inside a linked worktree — the main checkout is handled natively.
# Linked worktrees always have a git-dir path of the form:
#   /repo/.git/worktrees/<name>
case "$git_dir" in
    */.git/worktrees/*) ;;
    *) exit 0 ;;
esac

wt_root=$(git -C "$file_dir" rev-parse --show-toplevel 2>/dev/null) || exit 0

# Security: never grant for files outside the worktree root.
# Strict prefix: file_abs must be a child of wt_root, not wt_root itself.
case "$file_abs" in
    "$wt_root"/*) ;;
    *) exit 0 ;;
esac

file_rel="${file_abs#"$wt_root"/}"

# Secondary containment: resolve symlinks and verify the real path is still
# inside the worktree.  python3 is used for portability (GNU realpath -m is
# not available on macOS without coreutils; readlink -f requires the path to
# exist, which breaks Write on new files).
file_real=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$file_abs" 2>/dev/null) || exit 0
# Same strict-prefix requirement: resolved path must also be a child of wt_root.
case "$file_real" in
    "$wt_root"/*) ;;
    *) exit 0 ;;
esac

# Honor only settings.local.json — user-authored and gitignored.
# Never read a committed settings.json, which an untrusted repo could ship.
settings="$wt_root/.claude/settings.local.json"
[ -f "$settings" ] || exit 0

# parent is the directory that contains sibling worktrees (rimba layout:
# repo-worktrees/<name> are all siblings under the same parent).
parent=$(dirname "$wt_root")

# Iterate allow entries, looking for a match for the current tool.
while IFS= read -r entry; do
    # Filter to entries whose tool prefix matches.
    case "$entry" in
        "$tool_name("*) ;;
        *) continue ;;
    esac

    # Strip  tool_name( … )  to get the raw glob string.
    glob="${entry#"$tool_name"(}"
    glob="${glob%)}"

    # Derive a worktree-relative pattern P from the glob.
    case "$glob" in
        //*)
            # Claude Code absolute-path marker: //abs/path → /abs/path
            abs_glob="/${glob#//}"
            case "$abs_glob" in
                "$wt_root"/*)
                    P="${abs_glob#"$wt_root"/}"
                    [ -z "$P" ] && P="**"
                    ;;
                "$wt_root")
                    P="**"
                    ;;
                "$parent"/*)
                    # Sibling worktree grant — remap the sub-path to THIS worktree.
                    # A bare grant (no sub-path) or empty remainder grants NOTHING:
                    # collapsing to "**" would broaden a *different* worktree's root
                    # grant to the entire current worktree (fail-open, #501).
                    remainder="${abs_glob#"$parent"/}"
                    case "$remainder" in
                        */?*) P="${remainder#*/}" ;;
                        *)    continue ;;
                    esac
                    ;;
                *)
                    # Unrelated absolute path (e.g. //tmp/x/**) — skip.
                    continue
                    ;;
            esac
            ;;
        /*)
            # Single-slash absolute (uncommon but valid).
            abs_glob="$glob"
            case "$abs_glob" in
                "$wt_root"/*)
                    P="${abs_glob#"$wt_root"/}"
                    [ -z "$P" ] && P="**"
                    ;;
                "$wt_root")
                    P="**"
                    ;;
                "$parent"/*)
                    # Sibling worktree grant — see the //* branch above for rationale
                    # on why a bare/empty remainder must fail closed (grant nothing).
                    remainder="${abs_glob#"$parent"/}"
                    case "$remainder" in
                        */?*) P="${remainder#*/}" ;;
                        *)    continue ;;
                    esac
                    ;;
                *)
                    continue
                    ;;
            esac
            ;;
        *)
            # Relative glob — use directly as the project-relative pattern.
            P="$glob"
            ;;
    esac

    # bash case: * matches any string including those containing /, so ** ≡ *.
    # Leave $P unquoted so bash treats it as a glob pattern.
    # shellcheck disable=SC2254
    case "$file_rel" in
        $P)
            printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"worktree allowlist grant (.claude/settings.local.json)"}}\n'
            exit 0
            ;;
    esac
done < <(jq -r '.permissions.allow[]?' "$settings" 2>/dev/null)

exit 0
