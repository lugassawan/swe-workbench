#!/usr/bin/env bash
# inject_plugin_root_subagent.sh — SubagentStart hook (matcher: ^swe-workbench:.*$)
#
# $CLAUDE_PLUGIN_ROOT does not reliably resolve as a live shell variable inside
# a dispatched subagent's own Bash tool calls — inject_plugin_root.sh only
# rewrites commands whose OWN triggering process has the var set, which holds
# for the main/orchestrator session but not for a subagent's Bash calls
# (confirmed empirically: two independent subagent dispatches both saw an
# empty $CLAUDE_PLUGIN_ROOT). Instead of asking every subagent to resolve the
# var itself, this hook fires at dispatch time — in the orchestrator's own
# environment, where the var IS reliably set — and hands the subagent the
# already-resolved literal path via additionalContext, with an explicit
# instruction to substitute it wherever its own prompt says
# "$CLAUDE_PLUGIN_ROOT" rather than relying on shell expansion.
#
# Fail-open: exit 0 unconditionally. A broken hook must never block dispatch.
# If $CLAUDE_PLUGIN_ROOT is unset here too (the one unverified assumption in
# this design — SubagentStart's own process may or may not inherit it), this
# hook silently emits nothing and the subagent's bare `$CLAUDE_PLUGIN_ROOT`
# references fail loud (empty path, file-not-found) rather than silently —
# catchable in testing/review, not a masked failure.
set -u

main() {
    local root ctx

    root="${CLAUDE_PLUGIN_ROOT:-}"
    [ -n "$root" ] || return 0

    ctx="Plugin root for this session: \`${root}\`. \$CLAUDE_PLUGIN_ROOT is NOT reliably set as a live shell variable inside your own Bash tool calls — wherever your instructions say \"\$CLAUDE_PLUGIN_ROOT\", substitute this literal path instead. Example: \`cat \"${root}/rules/<name>.md\"\`, not \`cat \"\$CLAUDE_PLUGIN_ROOT/rules/<name>.md\"\`."

    jq -cn --arg ctx "$ctx" \
        '{"hookSpecificOutput":{"hookEventName":"SubagentStart","additionalContext":$ctx}}' \
        || return 0
}

main
exit 0
