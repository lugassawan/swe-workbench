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
    """SKILL.md failure modes must document the stale commit_id all-422 retry."""
    text = SKILL_MD.read_text()
    assert "headRefOid" in text or "HEAD_SHA mismatch" in text, (
        "SKILL.md failure modes must document the stale commit_id retry: "
        "re-fetch HEAD_SHA via headRefOid when all POSTs return 422"
    )


def test_followup_skill_owner_repo_from_gh_repo_view():
    """OWNER and REPO must be derived from 'gh repo view' (not from headRepository or baseRepository)."""
    text = SKILL_MD.read_text()
    assert re.search(r"OWNER\s*=.*\$\(gh repo view[^\n]*owner", text), (
        "SKILL.md must derive OWNER via 'gh repo view --json owner' — "
        "gh pr view --json has no baseRepository field; gh repo view resolves the base remote correctly"
    )
    assert re.search(r"REPO\s*=.*\$\(gh repo view[^\n]*name", text), (
        "SKILL.md must derive REPO via 'gh repo view --json name' — "
        "gh pr view --json has no baseRepository field; gh repo view resolves the base remote correctly"
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
    """SKILL.md must include a guard clause that exits if OWNER or REPO cannot be determined."""
    text = SKILL_MD.read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "SKILL.md must include the guard-clause error message for missing OWNER/REPO "
        "so fork-PR failures produce an actionable error rather than silently misrouting API calls"
    )


# --- State-file cleanup assertions (issue #428) ---

def test_followup_skill_cleanup_deletes_followup_json():
    """Step 7 success-path subshell must invoke clean-state-files.sh with the followup state files."""
    text = SKILL_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "SKILL.md Step 7 must call runtime/clean-state-files.sh to remove per-run followup state files"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}-followup.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}-followup.json to clean-state-files.sh"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}-followup-threads.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}-followup-threads.json to clean-state-files.sh"
    )


def test_followup_skill_state_cleanup_inside_background_subshell():
    """clean-state-files.sh must appear inside the background ( ... ) & subshell."""
    text = SKILL_MD.read_text()
    subshell_match = re.search(r'\(\s*bash.*?clean-state-files\.sh.*?\)\s*&', text, re.DOTALL)
    assert subshell_match, (
        "SKILL.md Step 7 clean-state-files.sh call must be inside the background ( ... ) & subshell"
    )


def test_followup_skill_state_cleanup_has_or_true_guard():
    """clean-state-files.sh call must be followed by || true so set -e in the subshell cannot
    abort rimba remove when the state files are already absent or fail validation."""
    text = SKILL_MD.read_text()
    assert re.search(r'clean-state-files\.sh.*?\|\|\s*true', text, re.DOTALL), (
        "SKILL.md Step 7 clean-state-files.sh call must use '|| true' so a non-zero exit "
        "does not abort rimba remove via set -e propagation into the background subshell"
    )
