# tests/test_workflow_pr_review_followup_skill.py

"""Tests for the workflow-pr-review-followup skill (closes #218)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-pr-review-followup"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS_TXT = SKILL_DIR / "triggers.txt"


def test_followup_skill_file_exists():
    """skills/workflow-pr-review-followup/SKILL.md must exist with valid frontmatter."""
    assert SKILL_MD.exists(), "skills/workflow-pr-review-followup/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert "name" in fm, "SKILL.md frontmatter must have a name field"
    assert "description" in fm, "SKILL.md frontmatter must have a description field"
    assert fm.get("orchestrator") == "true", (
        "SKILL.md frontmatter must have orchestrator: true"
    )


def test_followup_triggers_txt():
    """triggers.txt must exist and have at least 2 non-comment, non-blank lines."""
    assert TRIGGERS_TXT.exists(), "skills/workflow-pr-review-followup/triggers.txt must exist"
    lines = [
        ln.strip()
        for ln in TRIGGERS_TXT.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2, (
        f"triggers.txt must have at least 2 non-comment lines, got {len(lines)}: {lines}"
    )


def test_followup_skill_requires_footer_instruction():
    """SKILL.md Step 4 must pass the footer instruction so the agent emits APPROVE|COMMENT."""
    text = SKILL_MD.read_text()
    assert "Review Decision: APPROVE" in text or "APPROVE|COMMENT" in text, (
        "SKILL.md must include the footer instruction so the reviewer agent emits "
        "**Review Decision: APPROVE|COMMENT** (required for Step 5 footer parsing)"
    )
    assert "REQUEST_CHANGES" in text, (
        "SKILL.md must mention REQUEST_CHANGES in the footer constraint (Never REQUEST_CHANGES)"
    )


def test_followup_skill_references_dedup_contract():
    """SKILL.md must reference the Jaccard ±5 dedup contract from workflow-pr-review."""
    text = SKILL_MD.read_text()
    assert "Jaccard" in text, "SKILL.md must reference Jaccard dedup (word-token overlap)"
    assert re.search(r"[±≤].*5|5.*[±≤]|\b5\b.*line|\bline.*\b5\b", text), (
        "SKILL.md must reference the ±5-line fuzzy-match tolerance from the dedup contract"
    )


def test_followup_skill_delegates_to_reviewer_agent():
    """SKILL.md must delegate to the swe-workbench:reviewer agent."""
    text = SKILL_MD.read_text()
    assert "`swe-workbench:reviewer`" in text or "swe-workbench:reviewer" in text, (
        "SKILL.md must delegate to the swe-workbench:reviewer agent"
    )


def test_followup_skill_documents_stale_commit_retry():
    """The shared posting core's failure modes must document the stale commit_id
    all-422 retry (moved out of this skill by #499 — both consumers delegate here)."""
    text = (ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md").read_text()
    assert "headRefOid" in text or "HEAD_SHA mismatch" in text, (
        "workflow-pr-review-post/SKILL.md failure modes must document the stale commit_id retry: "
        "re-fetch HEAD_SHA via headRefOid when all POSTs return 422"
    )



def test_followup_skill_no_invalid_json_field():
    """Step 1 gh pr view --json must NOT include baseRepository (it is not a valid gh CLI field)."""
    text = SKILL_MD.read_text()
    assert not re.search(r"gh pr view[^\n]*--json[^\n]*baseRepository", text), (
        "SKILL.md must not use baseRepository in gh pr view --json — "
        "that field is unsupported and causes gh to exit with 'Unknown JSON field'"
    )


def test_followup_skill_no_fragile_owner_extraction():
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


def test_followup_skill_has_owner_repo_guard_clause():
    """preflight-pr.sh must include a guard clause that exits if OWNER or REPO cannot be determined."""
    # Fix A moved the OWNER/REPO guard to runtime/preflight-pr.sh
    text = (ROOT / "runtime" / "preflight-pr.sh").read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "runtime/preflight-pr.sh must include the guard-clause error message for missing OWNER/REPO "
        "so fork-PR failures produce an actionable error rather than silently misrouting API calls"
    )


# --- State-file cleanup assertions (issue #428) ---

def test_followup_skill_cleanup_deletes_followup_json():
    """Step 7 success-path must invoke clean-state-files.sh with this skill's own
    preflight state file. The threads-cache file moved to workflow-pr-review-post's
    own reap (#499) — it owns a distinct ${PR}-post-threads.json, not this file's job."""
    text = SKILL_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "SKILL.md Step 7 must call runtime/clean-state-files.sh to remove its own per-run state file"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}-followup.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}-followup.json to clean-state-files.sh"
    )


def test_followup_skill_state_cleanup_outside_background_subshell():
    """clean-state-files.sh must NOT appear inside the background ( ... ) & subshell.

    The reap must run in the foreground so failures surface immediately rather than being
    silently dropped by the backgrounded, output-suppressed worktree-teardown subshell.
    This is the inverse of the previous #428 assertion, which encoded the bug as correct.
    """
    text = SKILL_MD.read_text()
    subshell_match = re.search(r'\([^)]*clean-state-files\.sh[^)]*\)\s*&', text)
    assert not subshell_match, (
        "SKILL.md Step 7 clean-state-files.sh call must NOT be inside the background ( ... ) & "
        "subshell — the reap must run foreground so failures are visible (recurrence of #428/#429)"
    )


def test_followup_skill_state_cleanup_no_suppression():
    """clean-state-files.sh call must have NO 2>/dev/null and NO || true guard.

    The reap runs foreground (fix for #428/#429 recurrence): suppression guards would re-hide
    the same silent-orphan path. A non-zero exit from clean-state-files.sh is a real failure.
    """
    text = SKILL_MD.read_text()
    lines_with_reap = [
        ln for ln in text.splitlines() if "clean-state-files.sh" in ln
    ]
    assert lines_with_reap, "SKILL.md must contain a clean-state-files.sh call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        f"clean-state-files.sh call must not carry 2>/dev/null (foreground reap must be visible):\n"
        + "\n".join(suppressed)
    )


def test_followup_skill_state_cleanup_has_post_check():
    """Step 7 must include a post-reap verification that reports each state file as reaped or not."""
    text = SKILL_MD.read_text()
    assert re.search(r'✓ state file reaped:', text), (
        "SKILL.md Step 7 must include a post-reap report line '✓ state file reaped: ...' "
        "so operators can verify cleanup completed without inspecting /tmp by hand"
    )
