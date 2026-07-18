#!/usr/bin/env bash
# PreToolUse:Bash hook — inject CLAUDE_PLUGIN_ROOT into Bash commands that
# reference it (issue #530).
#
# Claude Code injects CLAUDE_PLUGIN_ROOT for hooks/MCP/LSP but NOT into Bash
# tool calls, so a command like `bash "$CLAUDE_PLUGIN_ROOT/runtime/foo.sh"`
# resolves to an empty prefix and fails. This hook's OWN environment does
# have the authoritative value (proven by the fact that hooks.json invokes
# every hook via $CLAUDE_PLUGIN_ROOT/hooks/<script>), so it reads it and
# re-injects it into the command about to run.
#
# Surgical scope: only rewrites commands that reference CLAUDE_PLUGIN_ROOT
# and don't already assign it. Never blocks — exit 0 in every branch.
# Emits ONLY updatedInput, never permissionDecision, so bash_guard.sh's
# exit-2 block is untouched and composes cleanly with this hook.
set -u

root="${CLAUDE_PLUGIN_ROOT:-}"
[ -n "$root" ] || exit 0

input=$(cat)

# Cheap pre-check on the raw payload before paying the jq tax, mirroring
# bash_guard.sh's short-circuit for the common (non-matching) case.
case "$input" in
  *CLAUDE_PLUGIN_ROOT*) ;;
  *)                    exit 0 ;;
esac

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -n "$cmd" ] || exit 0

# Assignment check is anchored to an actual command-start position (start
# of a line — grep is line-oriented, so this also covers "after a newline"
# for free — or after a ; & | separator, optionally with leading
# whitespace) — NOT a bare word-boundary substring match. A word-boundary
# check alone still mis-fires on CLAUDE_PLUGIN_ROOT= appearing inside a URL
# query string or --data payload (e.g. `curl ".../?CLAUDE_PLUGIN_ROOT=x"`),
# which would wrongly read as "already assigned" and skip injection of a
# genuine $CLAUDE_PLUGIN_ROOT reference elsewhere in the same command —
# reproducing the exact #530 failure mode in that case. [;&|] alone covers
# && and || too, since each is still built from ; & | characters.
# Reference check requires an actual sigil ($ or ${) so a bare mention of
# the literal text (e.g. in an echo or comment, with no $) doesn't trigger
# an unnecessary rewrite.
# Out of scope: execution order — a reference BEFORE a later real
# assignment in the same command (e.g. `echo "$CLAUDE_PLUGIN_ROOT";
# CLAUDE_PLUGIN_ROOT=x`) is still treated as "already assigned" and
# skipped, since this hook does not parse shell execution order (same
# class of scope gap bash_guard.sh documents in its own header comment).
if printf '%s' "$cmd" | grep -Eq '(^|[;&|])[[:space:]]*(export[[:space:]]+)?CLAUDE_PLUGIN_ROOT='; then
  exit 0  # already assigns it — idempotent no-op
fi
if ! printf '%s' "$cmd" | grep -Eq '\$\{?CLAUDE_PLUGIN_ROOT([^A-Za-z0-9_]|$)'; then
  exit 0  # doesn't reference it — nothing to do
fi

jq -n --arg root "$root" --arg cmd "$cmd" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", updatedInput: {command: ("export CLAUDE_PLUGIN_ROOT=" + ($root|@sh) + "; " + $cmd)}}}' \
  2>/dev/null || exit 0

exit 0
