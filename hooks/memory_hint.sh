#!/usr/bin/env bash
# memory_hint.sh — SessionStart(startup|resume|compact) hook.
# Renders combined cross-harness memory via bin/swe-workbench-memory and injects
# it as additionalContext. Fail-open: exit 0 unconditionally, no output on any
# failure — memory injection must never block startup.

main() {
    local input cwd harness script_dir runtime result schema markdown
    input=$(cat)
    cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || return 0
    [ -n "$cwd" ] || cwd="$PWD"
    # Claude Code's hooks.json payload carries no harness field — default to claude.
    harness=$(printf '%s' "$input" | jq -r '.harness // empty' 2>/dev/null) || return 0
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) || return 0
    runtime="$script_dir/../bin/swe-workbench-memory"
    [ -x "$runtime" ] || return 0
    result=$(cd "$cwd" && "$runtime" render --as "${harness:-claude}" 2>/dev/null) || return 0
    schema=$(printf '%s' "$result" | jq -r '.schema // empty' 2>/dev/null) || return 0
    [ "$schema" = "swb.memory/1" ] || return 0
    markdown=$(printf '%s' "$result" | jq -r '.data.markdown // empty' 2>/dev/null) || return 0
    [ -n "$markdown" ] || return 0
    jq -cn --arg ctx "$markdown" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}' \
        || return 0
}

main
exit 0
