#!/usr/bin/env bash
# workflow_resume_hint.sh — SessionStart(startup|resume|compact) hook
#
# Fires on cold launch, session continuation (--continue/--resume), and
# auto-compaction. Detects a fresh, branch-matching workflow checkpoint and
# injects a resume preamble so the model re-enters the interrupted workflow
# at the correct phase. Wording is conditioned on the SessionStart `.source`
# field so a non-compaction resume never falsely claims "this session was
# compacted".
#
# Fail-open: exit 0 unconditionally. A broken hook must never block startup.

# Sets advisory_lead/preamble_header/preamble_intro from $session_source.
# Reads $session_source and writes into main()'s locals via dynamic scoping.
set_framing() {
    case "$session_source" in
        compact)
            advisory_lead="WORKTREE RE-ANCHOR ADVISORY: Compaction may have dropped EnterWorktree tracking"
            preamble_header="[Workflow auto-resume after compaction]"
            preamble_intro="This session was compacted."
            ;;
        resume)
            advisory_lead="WORKTREE RE-ANCHOR ADVISORY: Resuming this session may have dropped EnterWorktree tracking"
            preamble_header="[Workflow auto-resume after continuation]"
            preamble_intro="This session was resumed/continued."
            ;;
        startup)
            advisory_lead="WORKTREE RE-ANCHOR ADVISORY: This session is not EnterWorktree-anchored"
            preamble_header="[Workflow auto-resume on startup]"
            preamble_intro="This is a fresh session start."
            ;;
        *)
            advisory_lead="WORKTREE RE-ANCHOR ADVISORY: EnterWorktree tracking may not be active"
            preamble_header="[Workflow auto-resume]"
            preamble_intro="This session resumed."
            ;;
    esac
}

# Shared advisory wording; $1 is the clause explaining why cwd is suspect.
# Reads $advisory_lead/$root via dynamic scoping from main().
format_advisory() {
    local clause="$1"
    # Backticks below are literal markdown ticks, not command substitution.
    # shellcheck disable=SC2016
    printf '%s even though your cwd (`%s`) %s. Call `EnterWorktree(path=%s)` to be safe — idempotent and harmless if you'"'"'re still anchored. A later `ExitWorktree` no-op is consistent with this, though not proof — cd-entry looks identical.' \
        "$advisory_lead" "$root" "$clause" "$root"
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

# Validates $state_file as a usable checkpoint for $branch; returns 0 if so.
# A run-scoped file (`<safe_branch>--<scope>.json`) must also record the same
# scope in `context.run_scope`. Stale files (>24h) are deleted — only this
# branch's own files are ever considered, so other branches manage their own.
# Reads state_file/state_dir/real_dir/safe_branch/branch via dynamic scoping.
validate_checkpoint() {
    local real_state version ctx_branch ctx_scope file_scope base
    [ -f "$state_file" ] || return 1

    # Path-containment guard: state_file must resolve inside state_dir.
    # Uses python3 for portability (GNU realpath -m unavailable on macOS without coreutils).
    real_state=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
        "$state_file" 2>/dev/null) || return 1
    case "$real_state" in "$real_dir/"*) ;; *) return 1 ;; esac

    # Staleness gate: file older than 24h is deleted and skipped.
    if [ -n "$(find "$state_file" -mmin +1440 2>/dev/null)" ]; then
        rm -f "$state_file"
        return 1
    fi

    # Schema version gate — only v1 understood; jq failure means malformed JSON.
    version=$(jq -r '.version // empty' "$state_file" 2>/dev/null) || return 1
    [ "$version" = "1" ] || return 1

    # Branch-match gate — reject a checkpoint left by a different branch
    ctx_branch=$(jq -r '.context.branch // empty' "$state_file" 2>/dev/null) || return 1
    [ "$ctx_branch" = "$branch" ] || return 1

    # Scope-match gate — filename scope and recorded scope must agree.
    base="${state_file##*/}"
    base="${base%.json}"
    file_scope=""
    [ "$base" = "$safe_branch" ] || file_scope="${base#"${safe_branch}--"}"
    ctx_scope=$(jq -r '.context.run_scope // ""' "$state_file" 2>/dev/null) || return 1
    [ "$ctx_scope" = "$file_scope" ] || return 1
    return 0
}

# Several concurrent runs on this branch each left a checkpoint. Never pick
# one — a wrong resume is worse than no resume — so list them and ask.
# Reads valid_files/branch/is_linked_worktree/preamble_* via dynamic scoping.
emit_ambiguous_preamble() {
    local f listing="" line advisory=""
    for f in "${valid_files[@]}"; do
        line=$(jq -r '"- run scope `\(.context.run_scope // "" | if . == "" then "(unscoped)" else . end)`: \(.skill // "?") — Phase \(.phase // "?")\(if (.phase_label // "") != "" then " — " + .phase_label else "" end)"' \
            "$f" 2>/dev/null) || continue
        listing="${listing}${line} (\`${f}\`)
"
    done
    if [ "$is_linked_worktree" -eq 1 ]; then
        advisory="
$(format_advisory "is a linked worktree")
"
    fi
    jq -cn --arg ctx "${preamble_header}

${preamble_intro} Multiple workflow checkpoints were found for branch: ${branch} (concurrent runs):

${listing}
Ask the user which run this session belongs to before resuming. Resume, update, and delete only that run's checkpoint file — never another run's.
${advisory}" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
}

main() {
    local input cwd root branch safe_branch state_dir state_file
    local real_dir run_scope
    local -a valid_files
    local skill mode phase phase_label completed notes preamble
    local worktree_root real_wt_root real_live_root cmp_wt_root cmp_live_root reanchor_line
    local git_dir git_common_dir real_git_dir real_common_dir cmp_git_dir cmp_common_dir
    local is_linked_worktree
    local session_source advisory_lead preamble_header preamble_intro

    input=$(cat)
    cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || return 0
    [ -n "$cwd" ] || cwd="$PWD"
    session_source=$(printf '%s' "$input" | jq -r '.source // empty' 2>/dev/null) || session_source=""
    set_framing

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
    real_dir=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" \
        "$state_dir" 2>/dev/null) || return 0

    # Candidates: the unscoped per-branch file plus any run-scoped
    # `<branch>--<run_scope>.json` siblings (issue #823 — concurrent runs on
    # one branch, e.g. parallel PR reviews from the main checkout).
    valid_files=()
    for state_file in "${state_dir}/${safe_branch}.json" "${state_dir}/${safe_branch}--"*.json; do
        if validate_checkpoint; then
            valid_files+=("$state_file")
        fi
    done

    # No usable checkpoint (missing/stale/malformed/wrong version/wrong
    # branch/wrong scope) still gets the standalone nudge if cwd is linked.
    if [ "${#valid_files[@]}" -eq 0 ]; then
        maybe_standalone_advisory
        return 0
    fi

    if [ "${#valid_files[@]}" -gt 1 ]; then
        emit_ambiguous_preamble
        return 0
    fi

    state_file="${valid_files[0]}"
    run_scope=$(jq -r '.context.run_scope // ""' "$state_file" 2>/dev/null) || run_scope=""

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
    preamble="${preamble_header}

${preamble_intro} A workflow checkpoint was found for branch: ${branch}.

Skill:            ${skill}
${run_scope:+Run scope:        ${run_scope}
}Current phase:    Phase ${phase}${phase_label:+ — ${phase_label}}${mode:+ (Mode ${mode})}
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
