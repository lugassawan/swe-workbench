"""Assert Fix B: each PR-workflow skill confirms runtime commands are on PATH + hard-fails if missing.

Root cause #2 (original, pre-#560): skills resolved the plugin root inline, per-call, via
${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}. When CLAUDE_PLUGIN_ROOT is unset and
cwd is an ephemeral worktree, the fallback resolves to the worktree root — runtime/ scripts
don't exist there, the call fails, and (with errors suppressed) the operator falls back to
inline gh/jq silently.

#560 replaced $CLAUDE_PLUGIN_ROOT-based path construction with bare `swe-workbench-<name>`
commands (bin/ is on PATH while the plugin is enabled). The guard now checks the command is
reachable via `command -v`, once, before worktree entry, rather than checking a resolved path.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

SKILLS_WITH_PREFLIGHT = [
    "workflow-pr-review",
    "workflow-pr-review-followup",
    "workflow-address-feedback",
    "workflow-audit-emit-issues",
    "workflow-cleanup-merged",
    "workflow-extend",
    "workflow-pr-review-post",
]

_PREFLIGHT_RE = re.compile(r'command -v swe-workbench-[\w-]+ >/dev/null 2>&1')
_GUARD_STR = "not on PATH — reinstall or update the swe-workbench plugin"


def _skill_text(skill_name: str) -> str:
    return (ROOT / "skills" / skill_name / "SKILL.md").read_text()


def test_preflight_check_exists_in_each_skill():
    """Each skill must contain at least one command -v swe-workbench-<name> preflight."""
    for skill in SKILLS_WITH_PREFLIGHT:
        text = _skill_text(skill)
        matches = _PREFLIGHT_RE.findall(text)
        assert len(matches) >= 1, (
            f"skills/{skill}/SKILL.md must contain a 'command -v swe-workbench-<name> "
            f">/dev/null 2>&1' preflight — this confirms the plugin's runtime commands "
            "are on PATH before any worktree entry"
        )


def test_hard_fail_guard_exists_in_each_skill():
    """Each skill must contain the hard-fail guard string so a missing command aborts loudly."""
    for skill in SKILLS_WITH_PREFLIGHT:
        text = _skill_text(skill)
        assert _GUARD_STR in text, (
            f"skills/{skill}/SKILL.md must contain the hard-fail guard message "
            f"'{_GUARD_STR}' — a missing runtime command must abort with a clear error, "
            "not silently fall back to inline gh/jq"
        )


def test_no_inline_root_resolution_at_script_call_sites():
    """No skill may use ${CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)} at a runtime-script call site.

    All runtime-script invocations must use bare `swe-workbench-<name>` commands so PATH
    resolution happens once, at plugin-load time, with no per-call path construction. A
    remaining `_RT=` assignment line is allowed — some skills (e.g. workflow-cleanup-merged)
    still bind the plugin root to resolve their own skill-local scripts/ helpers, which are
    unrelated to runtime/ and out of #560's scope.
    """
    for skill in SKILLS_WITH_PREFLIGHT:
        text = _skill_text(skill)
        raw_occurrences = [
            (i, ln.strip())
            for i, ln in enumerate(text.splitlines(), 1)
            if "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse" in ln
        ]
        violations = [
            (lineno, ln) for lineno, ln in raw_occurrences
            if not re.match(r'\s*_RT\s*=', ln)
        ]
        assert not violations, (
            f"skills/{skill}/SKILL.md has inline ${{CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)}} "
            f"at a runtime-script call site — invoke the bare swe-workbench-<name> command instead:\n"
            + "\n".join(f"  line {no}: {ln}" for no, ln in violations)
        )
