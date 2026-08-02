# tests/test_workflow_pr_review_followup_mode.py

"""Tests for workflow-pr-review's followup mode (closes #218).

The standalone followup skill was folded into workflow-pr-review as a mode
(chore #565): first-pass and followup are now selected via `$MODE` and the
mode-resolution table in skills/workflow-pr-review/SKILL.md, rather than
being two separate skills. These tests retarget the original #218
regression assertions at the merged skill, checking for the followup-mode
values now expressed through the mode table (e.g. `${PR}-followup.json`
appears as the followup-mode value of the `STATE_SUFFIX` variable rather
than as a literal path)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-pr-review"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS_TXT = SKILL_DIR / "triggers.txt"


def test_pr_review_skill_file_exists_for_followup_mode():
    """skills/workflow-pr-review/SKILL.md must exist with valid frontmatter."""
    assert SKILL_MD.exists(), "skills/workflow-pr-review/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert "name" in fm, "SKILL.md frontmatter must have a name field"
    assert "description" in fm, "SKILL.md frontmatter must have a description field"
    assert fm.get("orchestrator") == "true", (
        "SKILL.md frontmatter must have orchestrator: true"
    )


def test_pr_review_triggers_txt_covers_followup_phrasing():
    """triggers.txt must exist and have at least 2 non-comment, non-blank lines."""
    assert TRIGGERS_TXT.exists(), "skills/workflow-pr-review/triggers.txt must exist"
    lines = [
        ln.strip()
        for ln in TRIGGERS_TXT.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2, (
        f"triggers.txt must have at least 2 non-comment lines, got {len(lines)}: {lines}"
    )


def test_followup_mode_requires_footer_instruction():
    """SKILL.md Step 4 must pass the footer instruction so the agent emits APPROVE|COMMENT
    — this applies identically in followup mode (Step 4 explicitly says so)."""
    text = SKILL_MD.read_text()
    assert "Review Decision: APPROVE" in text or "APPROVE|COMMENT" in text, (
        "SKILL.md must include the footer instruction so the reviewer agent emits "
        "**Review Decision: APPROVE|COMMENT** (required for Step 5 footer parsing)"
    )
    assert "REQUEST_CHANGES" in text, (
        "SKILL.md must mention REQUEST_CHANGES in the footer constraint (Never REQUEST_CHANGES)"
    )


def test_followup_mode_references_dedup_contract():
    """SKILL.md must reference the Jaccard ±5 dedup contract shared by both modes."""
    text = SKILL_MD.read_text()
    assert "Jaccard" in text, "SKILL.md must reference Jaccard dedup (word-token overlap)"
    assert re.search(r"[±≤].*5|5.*[±≤]|\b5\b.*line|\bline.*\b5\b", text), (
        "SKILL.md must reference the ±5-line fuzzy-match tolerance from the dedup contract"
    )


def test_followup_mode_delegates_to_reviewer_agent():
    """SKILL.md must delegate to the swe-workbench:reviewer agent."""
    text = SKILL_MD.read_text()
    assert "`swe-workbench:reviewer`" in text or "swe-workbench:reviewer" in text, (
        "SKILL.md must delegate to the swe-workbench:reviewer agent"
    )


def test_followup_mode_documents_stale_commit_retry():
    """The shared posting core's failure modes must document the stale commit_id
    all-422 retry (moved out of this skill by #499 — both modes delegate here)."""
    text = (ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md").read_text()
    assert "headRefOid" in text or "HEAD_SHA mismatch" in text, (
        "workflow-pr-review-post/SKILL.md failure modes must document the stale commit_id retry: "
        "re-fetch HEAD_SHA via headRefOid when all POSTs return 422"
    )


def test_followup_mode_no_invalid_json_field():
    """Step 1 gh pr view --json must NOT include baseRepository (it is not a valid gh CLI field)."""
    text = SKILL_MD.read_text()
    assert not re.search(r"gh pr view[^\n]*--json[^\n]*baseRepository", text), (
        "SKILL.md must not use baseRepository in gh pr view --json — "
        "that field is unsupported and causes gh to exit with 'Unknown JSON field'"
    )


def test_followup_mode_no_fragile_owner_extraction():
    """SKILL.md must not contain fragile Python-dict or headRepository-owner extraction patterns."""
    text = SKILL_MD.read_text()
    assert "['owner']['login']" not in text, (
        "SKILL.md must not contain Python-dict extraction ['owner']['login'] — "
        "this pattern threw KeyError on fork PRs where headRepository lacks an owner key"
    )
    assert not re.search(r"headRepository[^`\n]*owner[^`\n]*login", text), (
        "SKILL.md must not reference headRepository.owner.login — "
        "use gh repo view instead"
    )


def test_followup_mode_has_owner_repo_guard_clause():
    """preflight-pr must include a guard clause that exits if OWNER or REPO cannot be determined."""
    # Fix A moved the OWNER/REPO guard to bin/swe-workbench-preflight-pr
    text = (ROOT / "bin" / "swe-workbench-preflight-pr").read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "bin/swe-workbench-preflight-pr must include the guard-clause error message for missing "
        "OWNER/REPO so fork-PR failures produce an actionable error rather than silently misrouting "
        "API calls"
    )


# --- State-file cleanup assertions (issue #428) ---

def test_followup_mode_passes_caller_tag_followup():
    """The followup branch of the mode-resolution table must set CALLER_TAG=followup
    when invoking the posting core."""
    text = SKILL_MD.read_text()
    assert "CALLER_TAG=followup" in text, (
        "workflow-pr-review/SKILL.md mode table must set CALLER_TAG=followup for followup mode "
        "when invoking workflow-pr-review-post"
    )


def test_followup_mode_state_suffix_resolves_to_followup_json():
    """The followup branch of the mode-resolution table must set STATE_SUFFIX="-followup",
    so that the ${PR}${STATE_SUFFIX}.json state-file path expressed in Step 7 resolves to
    ${PR}-followup.json in followup mode (preserving the original #218/#428 regression:
    followup mode's own preflight state file must be reaped by name)."""
    text = SKILL_MD.read_text()
    assert 'STATE_SUFFIX="-followup"' in text, (
        'SKILL.md mode table must set STATE_SUFFIX="-followup" for followup mode'
    )
    assert "swe-workbench-clean-state-files" in text, (
        "SKILL.md Step 7 must call swe-workbench-clean-state-files to remove its own per-run state file"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json" in text, (
        "SKILL.md Step 7 must pass /tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json to "
        "swe-workbench-clean-state-files, so followup mode reaps ${PR}-followup.json"
    )


def test_followup_mode_state_cleanup_outside_background_subshell():
    """swe-workbench-clean-state-files must NOT appear inside the background ( ... ) & subshell.

    The reap must run in the foreground so failures surface immediately rather than being
    silently dropped by the backgrounded, output-suppressed worktree-teardown subshell.
    This is the inverse of the previous #428 assertion, which encoded the bug as correct.
    """
    text = SKILL_MD.read_text()
    subshell_match = re.search(r'\([^)]*swe-workbench-clean-state-files[^)]*\)\s*&', text)
    assert not subshell_match, (
        "SKILL.md Step 7 swe-workbench-clean-state-files call must NOT be inside the background ( ... ) & "
        "subshell — the reap must run foreground so failures are visible (recurrence of #428/#429)"
    )


def test_followup_mode_state_cleanup_no_suppression():
    """swe-workbench-clean-state-files call must have NO 2>/dev/null and NO || true guard.

    The reap runs foreground (fix for #428/#429 recurrence): suppression guards would re-hide
    the same silent-orphan path. A non-zero exit from swe-workbench-clean-state-files is a real failure.
    """
    text = SKILL_MD.read_text()
    lines_with_reap = [
        ln for ln in text.splitlines() if "swe-workbench-clean-state-files" in ln
    ]
    assert lines_with_reap, "SKILL.md must contain a swe-workbench-clean-state-files call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        f"swe-workbench-clean-state-files call must not carry 2>/dev/null (foreground reap must be visible):\n"
        + "\n".join(suppressed)
    )


def test_followup_mode_state_cleanup_has_post_check():
    """Step 7 must include a post-reap verification that reports each state file as reaped or not."""
    text = SKILL_MD.read_text()
    assert re.search(r'✓ state file reaped:', text), (
        "SKILL.md Step 7 must include a post-reap report line '✓ state file reaped: ...' "
        "so operators can verify cleanup completed without inspecting /tmp by hand"
    )
