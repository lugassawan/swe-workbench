"""Assert Fix B: each of the 6 PR-workflow skills binds _RT once + hard-fails if scripts missing.

Root cause #2: skills resolved the plugin root inline, per-call, via
${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}. When CLAUDE_PLUGIN_ROOT is unset and
cwd is an ephemeral worktree, the fallback resolves to the worktree root — runtime/ scripts
don't exist there, the call fails, and (with errors suppressed) the operator falls back to
inline gh/jq silently.

Fix: bind _RT once before worktree entry; add a hard-fail guard so a missing runtime/ is loud.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

SKILLS_WITH_RT = [
    "workflow-pr-review",
    "workflow-pr-review-followup",
    "workflow-address-feedback",
    "workflow-audit-emit-issues",
    "workflow-cleanup-merged",
    "workflow-extend",
]

_RT_BINDING_RE = re.compile(r'_RT\s*=.*\$\{CLAUDE_PLUGIN_ROOT:-\$\(git rev-parse')
_GUARD_STR = "runtime scripts not found"


def _skill_text(skill_name: str) -> str:
    return (ROOT / "skills" / skill_name / "SKILL.md").read_text()


def test_rt_binding_exists_in_each_skill():
    """Each of the 6 skills must have exactly one _RT= binding capturing the plugin root."""
    for skill in SKILLS_WITH_RT:
        text = _skill_text(skill)
        matches = _RT_BINDING_RE.findall(text)
        assert len(matches) >= 1, (
            f"skills/{skill}/SKILL.md must contain a _RT= binding "
            f"(_RT=\"${{CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}}\") — "
            "this binds the plugin root before any worktree entry so the correct runtime/ is used"
        )


def test_hard_fail_guard_exists_in_each_skill():
    """Each skill must contain the hard-fail guard string so missing runtime/ aborts loudly."""
    for skill in SKILLS_WITH_RT:
        text = _skill_text(skill)
        assert _GUARD_STR in text, (
            f"skills/{skill}/SKILL.md must contain the hard-fail guard message "
            f"'{_GUARD_STR}' — missing runtime scripts must abort with a clear error, "
            "not silently fall back to inline gh/jq"
        )


def test_no_inline_root_resolution_at_script_call_sites():
    """No skill may use ${CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)} at a script call site.

    Only the single _RT= binding line is allowed to contain this pattern.
    All script invocations must use ${{_RT}}/runtime/... so the root is resolved once,
    before worktree entry, and reused consistently.
    """
    for skill in SKILLS_WITH_RT:
        text = _skill_text(skill)
        # Find all occurrences of the raw inline pattern
        raw_occurrences = [
            (i, ln.strip())
            for i, ln in enumerate(text.splitlines(), 1)
            if "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse" in ln
        ]
        # The _RT= binding line is allowed; all others are violations
        violations = [
            (lineno, ln) for lineno, ln in raw_occurrences
            if not re.match(r'\s*_RT\s*=', ln)
            and not ln.lstrip().startswith("#")
        ]
        assert not violations, (
            f"skills/{skill}/SKILL.md has inline ${{CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)}} "
            f"at script call sites (only the _RT= binding is allowed):\n"
            + "\n".join(f"  line {no}: {ln}" for no, ln in violations)
        )
