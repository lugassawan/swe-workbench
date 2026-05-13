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
