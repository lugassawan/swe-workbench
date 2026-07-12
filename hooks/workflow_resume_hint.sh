#!/usr/bin/env bash
# workflow_resume_hint.sh — SessionStart(compact) hook
#
# Fires after auto-compaction. Detects a fresh, branch-matching workflow
# checkpoint and injects a resume preamble so the model re-enters the
# interrupted workflow at the correct phase.
#
# Fail-open: exit 0 unconditionally. A broken hook must never block startup.

# Emits a standalone re-anchor nudge when cwd is a linked worktree and no usable
# checkpoint exists for this branch (missing, stale, wrong version, or wrong
# branch — all "nothing to resume" cases). Relies on bash's dynamic scoping to
# read is_linked_worktree/root/branch from the calling main() invocation.
maybe_standalone_advisory() {
    [ "$is_linked_worktree" -eq 1 ] || return 0
    local advisory
    advisory="WORKTREE RE-ANCHOR ADVISORY: This session resumed inside a linked worktree at \`${root}\` (branch ${branch}) after compaction. No usable workflow checkpoint was found for this branch, but compaction may still have dropped EnterWorktree tracking even though your cwd is already correct. Call \`EnterWorktree(path=${root})\` now to be safe — this is idempotent and harmless if you are still anchored. A later \`ExitWorktree\` no-op is consistent with this, though not proof — cd-entry looks identical."
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

    # Linked-worktree probe (#497): --git-dir differs from --git-common-dir when
    # cwd is a linked worktree rather than the main checkout. Runs independently of
    # the sidecar gate below — a harness EnterWorktree session can be dropped by
    # compaction even though cwd never moved and no checkpoint exists to resume.
    # Uses python3 realpath for portability (GNU realpath -m absent on macOS);
    # os.path.join treats an absolute second argument as already-resolved, so this
    # also handles git returning an absolute --git-dir/--git-common-dir directly.
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

    # No sidecar checkpoint for this branch. Previously an unconditional no-op —
    # now, if cwd is a linked worktree, emit a standalone defensive nudge: there is
    # nothing to resume, but EnterWorktree tracking can still have been dropped.
    # Every other "no usable checkpoint" gate below (stale, malformed, wrong
    # version, wrong branch) is the same situation and gets the same nudge —
    # otherwise a stale/invalid sidecar would silently reintroduce the no-op
    # this hook exists to close.
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

    # Schema version gate — only v1 understood; unknown versions are ignored.
    # A jq failure here also means "no usable checkpoint" (malformed JSON).
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

    # Worktree re-anchor check: if the checkpoint recorded a worktree path that
    # differs from the live root, emit a nudge to call EnterWorktree before resuming.
    # Uses python3 realpath for portability (GNU realpath -m absent on macOS).
    # Comparison is case-insensitive (tr lowercase) to avoid false positives on
    # macOS APFS/HFS+ (case-insensitive filesystem) and bind-mount paths.
    #
    # Same-path case (#497): worktree_root matches the live root, but cwd is still
    # a linked worktree — the mismatch check above finds nothing, yet compaction can
    # drop EnterWorktree tracking without ever moving cwd. Fire a defensive advisory
    # (distinct wording from the REQUIRED mismatch nudge, so it never fires when
    # is_linked_worktree=0, e.g. plain non-worktree repos in tests).
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
WORKTREE RE-ANCHOR ADVISORY: Compaction may have dropped EnterWorktree tracking even though your cwd (\`${root}\`) already matches the recorded worktree_root. Call \`EnterWorktree(path=${root})\` to be safe — idempotent and harmless if you're still anchored. A later \`ExitWorktree\` no-op is consistent with this, though not proof — cd-entry looks identical.
"
        fi
    elif [ "$is_linked_worktree" -eq 1 ]; then
        reanchor_line="
WORKTREE RE-ANCHOR ADVISORY: Compaction may have dropped EnterWorktree tracking even though your cwd (\`${root}\`) is a linked worktree. Call \`EnterWorktree(path=${root})\` to be safe — idempotent and harmless if you're still anchored. A later \`ExitWorktree\` no-op is consistent with this, though not proof — cd-entry looks identical.
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
