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
DOCTOR_CMD = ROOT / "commands" / "doctor.md"

SKILLS_WITH_PREFLIGHT = [
    "workflow-pr-review",
    "workflow-pr-review-followup",
    "workflow-address-feedback",
    "workflow-audit-emit-issues",
    "workflow-cleanup-merged",
    "workflow-extend",
    "workflow-pr-review-post",
    "workflow-branch-sync",
]

_PREFLIGHT_RE = re.compile(r'command -v swe-workbench-[\w-]+ >/dev/null 2>&1')
_GUARD_STR = "not on PATH — reinstall or update the swe-workbench plugin"
_RT_DERIVATION = '_RT="$(cd "$(dirname "$(command -v swe-workbench-doctor)")/.." && pwd)"'


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
    """No skill may use ${CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)} anywhere.

    All runtime-script invocations must use bare `swe-workbench-<name>` commands so PATH
    resolution happens once, at plugin-load time, with no per-call path construction. Skills
    that need their own skill-local root (to resolve their skills/<name>/scripts/ helpers)
    now derive it from the resolved `swe-workbench-doctor` command instead — see
    test_rt_derived_from_doctor_command. There is no remaining exemption for this pattern.
    """
    for skill in SKILLS_WITH_PREFLIGHT:
        text = _skill_text(skill)
        raw_occurrences = [
            (i, ln.strip())
            for i, ln in enumerate(text.splitlines(), 1)
            if "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse" in ln
        ]
        assert not raw_occurrences, (
            f"skills/{skill}/SKILL.md has inline ${{CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)}} "
            f"— this pattern is retired; derive _RT from `command -v swe-workbench-doctor` instead:\n"
            + "\n".join(f"  line {no}: {ln}" for no, ln in raw_occurrences)
        )


def test_rt_derived_from_doctor_command():
    """Every _RT= assignment must derive the skill root from the resolved doctor command.

    Not every skill in SKILLS_WITH_PREFLIGHT binds _RT — only those with skill-local
    scripts/ helpers (e.g. workflow-branch-sync, workflow-cleanup-merged) do. For those that
    do, the RHS must be exactly the pinned form so every skill resolves its root identically.
    """
    for skill in SKILLS_WITH_PREFLIGHT:
        text = _skill_text(skill)
        assign_lines = [ln.strip() for ln in text.splitlines() if re.match(r'\s*_RT\s*=', ln)]
        for ln in assign_lines:
            assert ln == _RT_DERIVATION, (
                f"skills/{skill}/SKILL.md defines _RT via an unexpected form: {ln!r} — "
                f"expected {_RT_DERIVATION!r}"
            )


def _bash_blocks(text: str) -> list[list[str]]:
    """Extract fenced ```bash ... ``` blocks, allowing leading indentation on the fence."""
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if re.match(r'^\s*```bash\s*$', lines[i]):
            start = i + 1
            j = start
            while j < len(lines) and lines[j].strip() != "```":
                j += 1
            blocks.append(lines[start:j])
            i = j + 1
        else:
            i += 1
    return blocks


def test_rt_defined_in_every_block_that_uses_it():
    """Each Bash tool call is a fresh shell — a block referencing $_RT/$_SCRIPTS must define
    _RT itself, not rely on a prior block's assignment having "stuck"."""
    for skill in SKILLS_WITH_PREFLIGHT:
        text = _skill_text(skill)
        for block in _bash_blocks(text):
            block_text = "\n".join(block)
            if not re.search(r'\$_RT\b|\$_SCRIPTS\b', block_text):
                continue
            assert re.search(r'^\s*_RT\s*=', block_text, re.MULTILINE), (
                f"skills/{skill}/SKILL.md has a bash block referencing $_RT/$_SCRIPTS "
                f"without defining _RT in the same block:\n{block_text}"
            )


# ──────────────────────────────────────────────
# doctor.md guard (static)
# ──────────────────────────────────────────────


class TestDoctorGuard:
    def test_doctor_has_hard_fail_guard(self):
        text = DOCTOR_CMD.read_text()
        assert "command -v swe-workbench-doctor" in text, (
            "doctor.md must contain the hard-fail guard checking swe-workbench-doctor is on PATH"
        )
        assert "swe-workbench-doctor" in text, (
            "doctor.md must invoke the bare swe-workbench-doctor command after the guard"
        )


# ──────────────────────────────────────────────
# SKILL.md bin/ script reference checks
# ──────────────────────────────────────────────


def test_preflight_pr_referenced_in_pr_review_skill():
    """workflow-pr-review SKILL.md Step 1 must use swe-workbench-preflight-pr (not raw inline gh/jq)."""
    text = (ROOT / "skills" / "workflow-pr-review" / "SKILL.md").read_text()
    assert "swe-workbench-preflight-pr" in text, (
        "workflow-pr-review SKILL.md Step 1 must invoke swe-workbench-preflight-pr — "
        "the consolidated pre-flight replaces the ~20-line inline gh/jq block"
    )
    assert 'eval "$(' in text, (
        "workflow-pr-review SKILL.md must use eval \"$(...)\" to source swe-workbench-preflight-pr output "
        "into the current shell (KEY=VALUE contract)"
    )


def test_preflight_pr_referenced_in_pr_review_followup_skill():
    """workflow-pr-review-followup SKILL.md Step 1 must use swe-workbench-preflight-pr."""
    text = (ROOT / "skills" / "workflow-pr-review-followup" / "SKILL.md").read_text()
    assert "swe-workbench-preflight-pr" in text, (
        "workflow-pr-review-followup SKILL.md Step 1 must invoke swe-workbench-preflight-pr"
    )
    assert 'eval "$(' in text, (
        "workflow-pr-review-followup SKILL.md must use eval \"$(...)\" to source preflight output"
    )


def test_preflight_pr_referenced_in_address_feedback_skill():
    """workflow-address-feedback SKILL.md Phase 1 must use swe-workbench-preflight-pr."""
    text = (ROOT / "skills" / "workflow-address-feedback" / "SKILL.md").read_text()
    assert "swe-workbench-preflight-pr" in text, (
        "workflow-address-feedback SKILL.md Phase 1 must invoke swe-workbench-preflight-pr"
    )
    assert 'eval "$(' in text, (
        "workflow-address-feedback SKILL.md must use eval \"$(...)\" to source preflight output"
    )


def test_reply_and_resolve_referenced_in_address_feedback_skill():
    """workflow-address-feedback SKILL.md must invoke swe-workbench-reply-and-resolve in Phase 5."""
    text = (ROOT / "skills" / "workflow-address-feedback" / "SKILL.md").read_text()
    assert "swe-workbench-reply-and-resolve" in text, (
        "workflow-address-feedback SKILL.md Phase 5 must invoke swe-workbench-reply-and-resolve"
    )
