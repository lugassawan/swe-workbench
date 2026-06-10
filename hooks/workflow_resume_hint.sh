#!/usr/bin/env bash
# workflow_resume_hint.sh — SessionStart(compact) hook
#
# Fires after auto-compaction. Detects a fresh, branch-matching workflow
# checkpoint and injects a resume preamble so the model re-enters the
# interrupted workflow at the correct phase.
#
# Fail-open: exit 0 unconditionally. A broken hook must never block startup.

main() {
    local input cwd root branch safe_branch state_dir state_file stale
    local real_state real_dir version ctx_branch
    local skill mode phase phase_label completed notes preamble
    local worktree_root real_wt_root real_live_root reanchor_line

    input=$(cat)
    cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || return 0
    [ -n "$cwd" ] || cwd="$PWD"

    # Resolve git root — absent in non-git directories, which is fine
    root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || return 0

    # Current branch — absent on detached HEAD, which is fine
    branch=$(git -C "$cwd" branch --show-current 2>/dev/null) || return 0
    [ -n "$branch" ] || return 0

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

    # No-op gate: no checkpoint for this branch
    [ -f "$state_file" ] || return 0

    # Staleness gate: file older than 24h is deleted and skipped.
    # Only the current branch's file is removed; other branches manage their own.
    stale=$(find "$state_file" -mmin +1440 2>/dev/null)
    if [ -n "$stale" ]; then
        rm -f "$state_file"
        return 0
    fi

    # Schema version gate — only v1 understood; unknown versions are ignored
    version=$(jq -r '.version // empty' "$state_file" 2>/dev/null) || return 0
    [ "$version" = "1" ] || return 0

    # Branch-match gate — reject a checkpoint left by a different branch
    ctx_branch=$(jq -r '.context.branch // empty' "$state_file" 2>/dev/null) || return 0
    [ "$ctx_branch" = "$branch" ] || return 0

    # Read resume fields
    skill=$(jq -r '.skill // ""' "$state_file" 2>/dev/null) || return 0
    mode=$(jq -r '.mode // ""' "$state_file" 2>/dev/null) || return 0
    phase=$(jq -r '.phase // ""' "$state_file" 2>/dev/null) || return 0
    phase_label=$(jq -r '.phase_label // ""' "$state_file" 2>/dev/null) || return 0
    completed=$(jq -r 'if (.completed_phases | length) > 0 then .completed_phases | join(", ") else "none" end' \
        "$state_file" 2>/dev/null) || completed="none"
    notes=$(jq -r '.context.notes // ""' "$state_file" 2>/dev/null) || notes=""
    worktree_root=$(jq -r '.context.worktree_root // ""' "$state_file" 2>/dev/null) || worktree_root=""

    # Worktree re-anchor check: if the checkpoint recorded a worktree path that
    # differs from the live root, emit a nudge to call EnterWorktree before resuming.
    # Uses python3 realpath for portability (GNU realpath -m absent on macOS).
    reanchor_line=""
    if [ -n "$worktree_root" ]; then
        real_wt_root=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
            "$worktree_root" 2>/dev/null) || real_wt_root=""
        real_live_root=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
            "$root" 2>/dev/null) || real_live_root=""
        if [ -n "$real_wt_root" ] && [ -n "$real_live_root" ] \
           && [ "$real_wt_root" != "$real_live_root" ]; then
            reanchor_line="
WORKTREE RE-ANCHOR REQUIRED: Your checkpoint recorded work in a worktree at \`${worktree_root}\`, but this session resumed at \`${root}\`. Call \`EnterWorktree(path=${worktree_root})\` before resuming — do not cd-prefix."
        fi
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
