"""Assert Fix B: each PR-workflow skill confirms runtime commands are on PATH + hard-fails if missing.

Root cause #2 (original, pre-#560): skills resolved the plugin root inline, per-call, via
${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}. When CLAUDE_PLUGIN_ROOT is unset and
cwd is an ephemeral worktree, the fallback resolves to the worktree root — runtime/ scripts
don't exist there, the call fails, and (with errors suppressed) the operator falls back to
inline gh/jq silently.

#560 replaced $CLAUDE_PLUGIN_ROOT-based path construction with bare `swe-workbench-<name>`
commands (bin/ is on PATH while the plugin is enabled). The guard now checks the command is
reachable via `command -v`, once, before worktree entry, rather than checking a resolved path.

Root cause #3 (#569, fixed by #578 + this change): skills with their own `scripts/` helpers
(workflow-cleanup-merged, workflow-branch-sync) still needed *some* way to resolve a skill-local
path. #578 replaced the retired `$CLAUDE_PLUGIN_ROOT` preamble with a doctor-anchor derivation
(`_RT="$(cd "$(dirname "$(command -v swe-workbench-doctor)")/.." && pwd)"`) repeated at every call
site — itself a 10-occurrence duplication, and still path construction in skill prose. This was
replaced with `bin/swe-workbench-skill-script <skill> <script> [args...]`, a single dispatcher
that owns root resolution; skill prose now invokes it as a bare command with no `_RT`/`_SCRIPTS`
variables anywhere.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCTOR_CMD = ROOT / "commands" / "doctor.md"

SKILLS_WITH_PREFLIGHT = [
    "workflow-pr-review",
    "workflow-address-feedback",
    "workflow-audit-emit-issues",
    "workflow-cleanup-merged",
    "workflow-extend",
    "workflow-pr-review-post",
    "workflow-branch-sync",
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
    """No skill may use ${CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)} anywhere.

    All runtime-script invocations must use bare `swe-workbench-<name>` commands so PATH
    resolution happens once, at plugin-load time, with no per-call path construction. Skills
    that need to invoke their own skill-local scripts/ helpers do so via
    `swe-workbench-skill-script <skill> <script>` — see test_no_path_resolution_in_skill_prose
    and test_skill_local_scripts_invoked_via_dispatcher. There is no remaining exemption for
    this pattern.
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
            f"— this pattern is retired; use `swe-workbench-skill-script` instead:\n"
            + "\n".join(f"  line {no}: {ln}" for no, ln in raw_occurrences)
        )


_PATH_RESOLUTION_RE = re.compile(r'_RT\s*=|\$\(dirname "\$\(command -v')

_SKILL_DIRS = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())

_SKILLS_WITH_LOCAL_SCRIPTS = sorted(
    p.name for p in (ROOT / "skills").iterdir() if (p / "scripts").is_dir()
)


def test_no_path_resolution_in_skill_prose():
    """No SKILL.md may construct a path to a skill-local script itself.

    #578 replaced the retired $CLAUDE_PLUGIN_ROOT preamble with a doctor-anchor _RT=
    derivation repeated at every call site — still path construction in skill prose, just a
    different RHS. `bin/swe-workbench-skill-script` now owns all of that resolution; no
    SKILL.md should ever assign `_RT=` or derive a root via `dirname "$(command -v ...)"`.
    """
    assert _SKILL_DIRS, "no skills found under skills/ — fixture list must not be empty"
    for skill in _SKILL_DIRS:
        text = _skill_text(skill)
        offenders = [
            (i, ln.strip())
            for i, ln in enumerate(text.splitlines(), 1)
            if _PATH_RESOLUTION_RE.search(ln)
        ]
        assert not offenders, (
            f"skills/{skill}/SKILL.md constructs a path instead of using "
            "swe-workbench-skill-script:\n" + "\n".join(f"  line {no}: {ln}" for no, ln in offenders)
        )


def test_skill_local_scripts_invoked_via_dispatcher():
    """Every skill-local scripts/*.sh helper must be invoked via the dispatcher, by name.

    Skills with their own scripts/ dir (workflow-cleanup-merged, workflow-branch-sync) must
    reference each helper as `swe-workbench-skill-script <skill> <script>`, never a
    constructed path — this is the replacement for the retired _RT/_SCRIPTS pattern. A skill
    may satisfy this from a companion `reference/*.md` file instead of SKILL.md itself when
    the invocation lives in content extracted there (e.g. workflow-cleanup-merged's Worktree
    Removal Strategies), so this check searches SKILL.md plus any reference/ markdown.
    """
    assert _SKILLS_WITH_LOCAL_SCRIPTS, "no skills with a scripts/ dir found — fixture list must not be empty"
    for skill in _SKILLS_WITH_LOCAL_SCRIPTS:
        text = _skill_text(skill)
        reference_dir = ROOT / "skills" / skill / "reference"
        if reference_dir.is_dir():
            text += "\n".join(p.read_text() for p in sorted(reference_dir.glob("*.md")))
        script_names = sorted(p.name for p in (ROOT / "skills" / skill / "scripts").glob("*.sh"))
        assert script_names, f"skills/{skill}/scripts/ has no .sh files"
        for name in script_names:
            pattern = re.compile(rf'swe-workbench-skill-script {re.escape(skill)} {re.escape(name)}\b')
            assert pattern.search(text), (
                f"skills/{skill}/SKILL.md (or a skills/{skill}/reference/*.md companion) must "
                f"invoke skills/{skill}/scripts/{name} via 'swe-workbench-skill-script {skill} {name}'"
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


def test_preflight_pr_referenced_in_pr_review_followup_mode():
    """The standalone followup skill was folded into workflow-pr-review as a mode (#565);
    its Step 1 (shared by both first-pass and followup) must use swe-workbench-preflight-pr."""
    text = (ROOT / "skills" / "workflow-pr-review" / "SKILL.md").read_text()
    assert "swe-workbench-preflight-pr" in text, (
        "workflow-pr-review SKILL.md Step 1 must invoke swe-workbench-preflight-pr"
    )
    assert 'eval "$(' in text, (
        "workflow-pr-review SKILL.md must use eval \"$(...)\" to source preflight output"
    )


def test_preflight_pr_referenced_in_address_feedback_skill():
    """workflow-address-feedback SKILL.md Phase 1 must reach swe-workbench-preflight-pr
    (now transitively, via swe-workbench-address-feedback-fetch) and consume
    its output through the standard envelope + swe-workbench-result-check contract, not
    eval "$(...)" sourcing (retired along with the direct preflight-pr call)."""
    text = (ROOT / "skills" / "workflow-address-feedback" / "SKILL.md").read_text()
    assert "swe-workbench-preflight-pr" in text, (
        "workflow-address-feedback SKILL.md Phase 1 must reference swe-workbench-preflight-pr"
    )
    assert "swe-workbench-address-feedback-fetch" in text, (
        "workflow-address-feedback SKILL.md Phase 1 must invoke swe-workbench-address-feedback-fetch"
    )
    assert "swe-workbench-result-check swb.address-feedback-fetch/1" in text, (
        "workflow-address-feedback SKILL.md must validate the fetch envelope via "
        "swe-workbench-result-check swb.address-feedback-fetch/1"
    )


def test_reply_and_resolve_referenced_in_address_feedback_skill():
    """workflow-address-feedback SKILL.md must invoke swe-workbench-reply-and-resolve in Phase 5."""
    text = (ROOT / "skills" / "workflow-address-feedback" / "SKILL.md").read_text()
    assert "swe-workbench-reply-and-resolve" in text, (
        "workflow-address-feedback SKILL.md Phase 5 must invoke swe-workbench-reply-and-resolve"
    )
