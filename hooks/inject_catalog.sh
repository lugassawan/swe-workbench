#!/usr/bin/env bash
# inject_catalog.sh — SessionStart(startup|resume|compact) hook
#
# Injects the principle/language rule catalog as additionalContext. Rule
# bodies live under rules/*.md as plain files, not skills, so there's no
# Skill-autoload mechanism to surface them — subagents get the catalog via
# the embedded @./shared/{principles,languages}.md includes in their own
# prompts, but the main thread receives no such include, so this hook is
# its only delivery path.
#
# Fail-open: exit 0 unconditionally. A broken hook must never block startup.
set -u

main() {
    local root principles languages catalog preamble

    root="${CLAUDE_PLUGIN_ROOT:-}"
    [ -n "$root" ] || return 0

    principles="$root/agents/shared/principles.md"
    languages="$root/agents/shared/languages.md"
    [ -f "$principles" ] && [ -f "$languages" ] || return 0

    catalog="$(cat "$principles" "$languages" 2>/dev/null)" || return 0
    [ -n "$catalog" ] || return 0

    preamble="[Rule catalog]

The principle-*/language-* entries below are plain \`.md\` rule files under \`rules/\`, not skills. When one applies to the current work, load its body with \`cat \"\$CLAUDE_PLUGIN_ROOT/rules/<name>.md\"\` via the Bash tool — do not invoke them with the Skill tool, they aren't registered as skills.

${catalog}"

    jq -cn --arg ctx "$preamble" \
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}' \
        || return 0
}

main
exit 0
