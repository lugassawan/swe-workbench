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

# Validates $state_file as a usable checkpoint for $branch; returns 0 if so
# and sets checked_scope/checked_skill. A run-scoped file
# (`<safe_branch>--<scope>.json`) must use the documented scope charset and
# record the same scope in `context.run_scope`. The `<safe_branch>--*.json`
# glob can also match another branch's files (branch `a` sees branch `a--b`'s
# `a--b.json`), so a stale file is deleted only after its branch and scope
# are confirmed as ours — except the exact unscoped `<safe_branch>.json`,
# which is ours by name and is swept even when malformed.
# Reads state_file/safe_branch/branch via dynamic scoping.
validate_checkpoint() {
    local base file_scope fields version ctx_branch ctx_scope ctx_skill stale
    # Path-containment guard: a glob match is a direct child of state_dir by
    # construction, so refusing symlinks keeps it inside the directory.
    [ -f "$state_file" ] && [ ! -L "$state_file" ] || return 1

    base="${state_file##*/}"
    base="${base%.json}"
    file_scope=""
    if [ "$base" != "$safe_branch" ]; then
        file_scope="${base#"${safe_branch}--"}"
        case "$file_scope" in ''|*[!A-Za-z0-9._-]*) return 1 ;; esac
    fi

    # Staleness: file older than 24h is deleted and skipped (see above).
    stale=$(find "$state_file" -mmin +1440 2>/dev/null)
    if [ -n "$stale" ] && [ -z "$file_scope" ]; then
        rm -f "$state_file"
        return 1
    fi

    # One jq pass; \u001f (non-whitespace IFS) keeps empty fields in place.
    # jq failure means malformed JSON.
    fields=$(jq -r '[.version, .context.branch, .context.run_scope, .skill]
        | map(. // "" | tostring) | join("\u001f")' "$state_file" 2>/dev/null) || return 1
    IFS=$'\x1f' read -r version ctx_branch ctx_scope ctx_skill <<<"$fields"

    # Branch-match gate — reject a checkpoint left by a different branch.
    [ "$ctx_branch" = "$branch" ] || return 1
    # Scope-match gate — filename scope and recorded scope must agree.
    [ "$ctx_scope" = "$file_scope" ] || return 1

    if [ -n "$stale" ]; then
        rm -f "$state_file"
        return 1
    fi

    # Schema version gate — only v1 understood.
    [ "$version" = "1" ] || return 1

    checked_scope="$ctx_scope"
    checked_skill="$ctx_skill"
    return 0
}

# Prints one list line describing checkpoint $1, falling back to the bare
# path so a field jq can't render never drops a run from the list.
describe_checkpoint() {
    jq -r --arg f "$1" '"- run scope `\(.context.run_scope // "" | tostring | if . == "" then "(unscoped)" else . end)`: \(.skill // "?" | tostring) — Phase \(.phase // "?" | tostring)\(if (.phase_label // "") != "" then " — " + (.phase_label | tostring) else "" end)\(if (.context.worktree_root // "") != "" then " — worktree_root `" + (.context.worktree_root | tostring) + "`" else "" end) (`\($f)`)"' \
        "$1" 2>/dev/null || printf -- '- `%s`\n' "$1"
}

# Several concurrent runs on this branch each left a checkpoint. Never pick
# one — a wrong resume is worse than no resume — so list them and ask.
# Reads valid_files/branch/root/is_linked_worktree/preamble_* via dynamic scoping.
emit_ambiguous_preamble() {
    local f listing="" advisory=""
    for f in "${valid_files[@]}"; do
        listing="${listing}$(describe_checkpoint "$f")
"
    done
    if [ "$is_linked_worktree" -eq 1 ]; then
        advisory="
$(format_advisory "is a linked worktree")
"
    fi
    # Backticks below are literal markdown ticks, not command substitution.
    # shellcheck disable=SC2016
    jq -cn --arg ctx "${preamble_header}

${preamble_intro} Multiple workflow checkpoints were found for branch: ${branch} (concurrent runs):

${listing}
Ask the user which run this session belongs to before resuming. Resume, update, and delete only that run's checkpoint file — never another run's. If the chosen run records a worktree_root other than this session's root (\`${root}\`), call \`EnterWorktree(path=<that worktree_root>)\` before resuming — do not cd-prefix.
${advisory}" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
}

main() {
    local input cwd root branch safe_branch state_dir state_file
    local run_scope others_block checked_scope checked_skill pick others i
    local -a valid_files valid_scopes valid_skills
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

    # Candidates: the unscoped per-branch file plus any run-scoped
    # `<branch>--<run_scope>.json` siblings (issue #823 — concurrent runs on
    # one branch, e.g. parallel PR reviews from the main checkout).
    valid_files=()
    valid_scopes=()
    valid_skills=()
    for state_file in "${state_dir}/${safe_branch}.json" "${state_dir}/${safe_branch}--"*.json; do
        if validate_checkpoint; then
            valid_files+=("$state_file")
            valid_scopes+=("$checked_scope")
            valid_skills+=("$checked_skill")
        fi
    done

    # No usable checkpoint (missing/stale/malformed/wrong version/wrong
    # branch/wrong scope) still gets the standalone nudge if cwd is linked.
    if [ "${#valid_files[@]}" -eq 0 ]; then
        maybe_standalone_advisory
        return 0
    fi

    # Several checkpoints: auto-resume only when the single unscoped one
    # (always first in the glob order above) belongs to a different skill
    # than every run-scoped one — e.g. a workflow-development run on main
    # alongside PR reviews from the same checkout. Mention the others so a
    # session that is one of those runs can still find its own file.
    pick=0
    others=""
    if [ "${#valid_files[@]}" -gt 1 ]; then
        pick=-1
        if [ -z "${valid_scopes[0]}" ]; then
            pick=0
            for i in "${!valid_files[@]}"; do
                [ "$i" -eq 0 ] && continue
                if [ "${valid_skills[$i]}" = "${valid_skills[0]}" ]; then
                    pick=-1
                    break
                fi
                others="${others}$(describe_checkpoint "${valid_files[$i]}")
"
            done
        fi
        if [ "$pick" -lt 0 ]; then
            emit_ambiguous_preamble
            return 0
        fi
    fi

    state_file="${valid_files[$pick]}"
    run_scope="${valid_scopes[$pick]}"

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

    others_block=""
    if [ -n "$others" ]; then
        others_block="

Other concurrent runs also have checkpoints on this branch. If this session is one of them instead, resume that run from its own file; never update or delete another run's checkpoint:
${others}"
    fi

    # Build preamble
    preamble="${preamble_header}

${preamble_intro} A workflow checkpoint was found for branch: ${branch}.

Skill:            ${skill}
${run_scope:+Run scope:        ${run_scope}
}Checkpoint file:  ${state_file}
Current phase:    Phase ${phase}${phase_label:+ — ${phase_label}}${mode:+ (Mode ${mode})}
Completed phases: ${completed}
${notes:+Notes: ${notes}
}
Resume from Phase ${phase}${phase_label:+ (${phase_label})} — do NOT restart from Phase 1 or re-run completed phases.
${reanchor_line}
If the recorded state contradicts current repo reality (wrong branch, missing files, unexpected git state), stop and ask the user how to proceed before resuming.${others_block}"

    # Use jq to build the full JSON envelope — avoids any shell format-string risk
    # from characters in $preamble (%, \n, quotes, etc.).
    jq -cn --arg ctx "$preamble" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}' \
        || return 0
}

main
exit 0
