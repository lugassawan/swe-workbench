#!/usr/bin/env bash
# workflow_resume_hint.sh — SessionStart(compact) hook
#
# Fires after auto-compaction. Detects a fresh, branch-matching workflow
# checkpoint and injects a resume preamble so the model re-enters the
# interrupted workflow at the correct phase.
#
# Fail-open: exit 0 unconditionally. A broken hook must never block startup.

# Shared advisory wording; $1 is the clause explaining why cwd is suspect.
# Reads $root via dynamic scoping from main().
format_advisory() {
    local clause="$1"
    # Backticks below are literal markdown ticks, not command substitution.
    # shellcheck disable=SC2016
    printf 'WORKTREE RE-ANCHOR ADVISORY: Compaction may have dropped EnterWorktree tracking even though your cwd (`%s`) %s. Call `EnterWorktree(path=%s)` to be safe — idempotent and harmless if you'"'"'re still anchored. A later `ExitWorktree` no-op is consistent with this, though not proof — cd-entry looks identical.' \
        "$root" "$clause" "$root"
}

# Nudges when cwd is a linked worktree but there's no usable checkpoint to
# resume. Reads is_linked_worktree/root/branch via dynamic scoping from main().
maybe_standalone_advisory() {
    [ "$is_linked_worktree" -eq 1 ] || return 0
    local advisory
    advisory=$(format_advisory "is a linked worktree with no usable workflow checkpoint found for branch ${branch}")
    jq -cn --arg ctx "$advisory" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
}

main() {
    local input cwd root branch safe_branch state_dir state_file stale
    local real_state real_dir version ctx_branch
    local skill mode phase phase_label completed notes preamble
    local worktree_root real_wt_root real_live_root cmp_wt_root cmp_live_root reanchor_line
    local git_dir git_common_dir real_git_dir real_common_dir cmp_git_dir cmp_common_dir
    local is_linked_worktree

    input=$(cat)
    cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || return 0
    [ -n "$cwd" ] || cwd="$PWD"

    # Resolve git root — absent in non-git directories, which is fine
    root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || return 0

    # Current branch — absent on detached HEAD, which is fine
    branch=$(git -C "$cwd" branch --show-current 2>/dev/null) || return 0
    [ -n "$branch" ] || return 0

    # --git-dir differs from --git-common-dir when cwd is a linked worktree,
    # independent of any sidecar checkpoint. python3 realpath for portability
    # (macOS lacks GNU realpath -m); os.path.join no-ops on an absolute 2nd arg.
    is_linked_worktree=0
    git_dir=$(git -C "$cwd" rev-parse --git-dir 2>/dev/null) || git_dir=""
    git_common_dir=$(git -C "$cwd" rev-parse --git-common-dir 2>/dev/null) || git_common_dir=""
    if [ -n "$git_dir" ] && [ -n "$git_common_dir" ]; then
        real_git_dir=$(python3 -c "import os,sys; print(os.path.realpath(os.path.join(sys.argv[1], sys.argv[2])))" \
            "$cwd" "$git_dir" 2>/dev/null) || real_git_dir=""
        real_common_dir=$(python3 -c "import os,sys; print(os.path.realpath(os.path.join(sys.argv[1], sys.argv[2])))" \
            "$cwd" "$git_common_dir" 2>/dev/null) || real_common_dir=""
        cmp_git_dir=$(printf '%s' "$real_git_dir" | tr '[:upper:]' '[:lower:]')
        cmp_common_dir=$(printf '%s' "$real_common_dir" | tr '[:upper:]' '[:lower:]')
        if [ -n "$real_git_dir" ] && [ -n "$real_common_dir" ] \
           && [ "$cmp_git_dir" != "$cmp_common_dir" ]; then
            is_linked_worktree=1
        fi
    fi

    # Sanitize branch name: / → - (mirrors the writer contract)
    safe_branch="${branch//\//-}"
    state_dir="$root/.claude/cache/workflow-state"
    state_file="${state_dir}/${safe_branch}.json"

    # Path-containment guard: state_file must resolve inside state_dir.
    # Uses python3 for portability (GNU realpath -m unavailable on macOS without coreutils).
    real_state=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
        "$state_file" 2>/dev/null) || return 0
    real_dir=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
        "$state_dir" 2>/dev/null) || return 0
    case "$real_state" in "$real_dir/"*) ;; *) return 0 ;; esac

    # No usable checkpoint (missing, and below: stale/malformed/wrong
    # version/wrong branch) still gets the standalone nudge if cwd is linked.
    if [ ! -f "$state_file" ]; then
        maybe_standalone_advisory
        return 0
    fi

    # Staleness gate: file older than 24h is deleted and skipped.
    # Only the current branch's file is removed; other branches manage their own.
    stale=$(find "$state_file" -mmin +1440 2>/dev/null)
    if [ -n "$stale" ]; then
        rm -f "$state_file"
        maybe_standalone_advisory
        return 0
    fi

    # Schema version gate — only v1 understood; jq failure means malformed JSON.
    version=$(jq -r '.version // empty' "$state_file" 2>/dev/null) || { maybe_standalone_advisory; return 0; }
    if [ "$version" != "1" ]; then
        maybe_standalone_advisory
        return 0
    fi

    # Branch-match gate — reject a checkpoint left by a different branch
    ctx_branch=$(jq -r '.context.branch // empty' "$state_file" 2>/dev/null) || { maybe_standalone_advisory; return 0; }
    if [ "$ctx_branch" != "$branch" ]; then
        maybe_standalone_advisory
        return 0
    fi

    # Read resume fields
    skill=$(jq -r '.skill // ""' "$state_file" 2>/dev/null) || return 0
    mode=$(jq -r '.mode // ""' "$state_file" 2>/dev/null) || return 0
    phase=$(jq -r '.phase // ""' "$state_file" 2>/dev/null) || return 0
    phase_label=$(jq -r '.phase_label // ""' "$state_file" 2>/dev/null) || return 0
    completed=$(jq -r 'if (.completed_phases | length) > 0 then .completed_phases | join(", ") else "none" end' \
        "$state_file" 2>/dev/null) || completed="none"
    notes=$(jq -r '.context.notes // ""' "$state_file" 2>/dev/null) || notes=""
    worktree_root=$(jq -r '.context.worktree_root // ""' "$state_file" 2>/dev/null) || worktree_root=""

    # Worktree re-anchor check: nudge if the checkpoint's worktree path differs
    # from the live root. python3 realpath for portability; comparison is
    # case-insensitive (tr lowercase) for macOS APFS/HFS+ and bind-mount paths.
    # When the path matches instead, still fire the (differently-worded)
    # advisory if cwd is a linked worktree — tracking can be lost without cwd
    # ever moving.
    reanchor_line=""
    if [ -n "$worktree_root" ]; then
        real_wt_root=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
            "$worktree_root" 2>/dev/null) || real_wt_root=""
        real_live_root=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
            "$root" 2>/dev/null) || real_live_root=""
        cmp_wt_root=$(printf '%s' "$real_wt_root" | tr '[:upper:]' '[:lower:]')
        cmp_live_root=$(printf '%s' "$real_live_root" | tr '[:upper:]' '[:lower:]')
        if [ -n "$real_wt_root" ] && [ -n "$real_live_root" ] \
           && [ "$cmp_wt_root" != "$cmp_live_root" ]; then
            # ${worktree_root} is the original recorded path (not realpath-resolved) — the
            # operator must pass that same path to EnterWorktree so it matches the registered
            # worktree entry. ${root} is the git-resolved live root and is only shown for
            # context; the asymmetry between the two is intentional.
            reanchor_line="
WORKTREE RE-ANCHOR REQUIRED: Your checkpoint recorded work in a worktree at \`${worktree_root}\`, but this session resumed at \`${root}\`. Call \`EnterWorktree(path=${worktree_root})\` before resuming — do not cd-prefix.
"
        elif [ "$is_linked_worktree" -eq 1 ]; then
            reanchor_line="
$(format_advisory "already matches the recorded worktree_root")
"
        fi
    elif [ "$is_linked_worktree" -eq 1 ]; then
        reanchor_line="
$(format_advisory "is a linked worktree")
"
    fi

    # Build preamble
    preamble="[Workflow auto-resume after compaction]

This session was compacted. A workflow checkpoint was found for branch: ${branch}.

Skill:            ${skill}
Current phase:    Phase ${phase}${phase_label:+ — ${phase_label}}${mode:+ (Mode ${mode})}
Completed phases: ${completed}
${notes:+Notes: ${notes}
}
Resume from Phase ${phase}${phase_label:+ (${phase_label})} — do NOT restart from Phase 1 or re-run completed phases.
${reanchor_line}
If the recorded state contradicts current repo reality (wrong branch, missing files, unexpected git state), stop and ask the user how to proceed before resuming."

    # Use jq to build the full JSON envelope — avoids any shell format-string risk
    # from characters in $preamble (%, \n, quotes, etc.).
    jq -cn --arg ctx "$preamble" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}' \
        || return 0
}

main
exit 0
