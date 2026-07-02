# tests/test_workflow_pr_review_cta_suppression.py

"""Pin the address-feedback CTA suppression contract for both pr-review skills.

Bug: IS_SELF_REVIEW caused the CTA to be silently dropped when the user ran
/implement → /review on their own PR, even when findings were posted. The fix
removes the identity axis from the CTA gate — only the outcome axis gates it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PR_REVIEW_SKILL = ROOT / "skills" / "workflow-pr-review" / "SKILL.md"
PR_REVIEW_FOLLOWUP_SKILL = ROOT / "skills" / "workflow-pr-review-followup" / "SKILL.md"


def _suppression_block(text: str) -> str:
    """Extract the paragraph(s) immediately following the CTA quote block."""
    match = re.search(
        r"Address-feedback CTA \(conditional\):.*?(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not locate 'Address-feedback CTA (conditional):' section. "
        "The CTA section header was renamed or removed — update the regex in _suppression_block."
    )
    return match.group(0)


# ── workflow-pr-review/SKILL.md ───────────────────────────────────────────────


def test_pr_review_cta_no_identity_suppression():
    """The CTA suppression block must NOT gate on CURRENT_USER == AUTHOR_LOGIN."""
    text = PR_REVIEW_SKILL.read_text()
    block = _suppression_block(text)
    assert "CURRENT_USER == AUTHOR_LOGIN" not in block, (
        "workflow-pr-review/SKILL.md still suppresses the CTA based on author identity. "
        "Remove the identity axis — suppression should be outcome-only."
    )


def test_pr_review_cta_no_self_review_suppression():
    """The CTA suppression block must NOT reference IS_SELF_REVIEW or self-review."""
    text = PR_REVIEW_SKILL.read_text()
    block = _suppression_block(text)
    assert "IS_SELF_REVIEW" not in block, (
        "CTA block must not gate on IS_SELF_REVIEW — outcome axis only. "
        "IS_SELF_REVIEW belongs on the GitHub-submission gate, not the CTA."
    )
    assert not re.search(r"(?i)self.?review", block), (
        "CTA block must not mention self-review as a suppression trigger."
    )


def test_pr_review_cta_outcome_axis_present():
    """The CTA emission block must reference the outcome axis conditions."""
    text = PR_REVIEW_SKILL.read_text()
    block = _suppression_block(text)
    assert "DECISION = COMMENT" in block or "DECISION=COMMENT" in block, (
        "CTA block must mention DECISION = COMMENT as an actionable outcome"
    )
    assert "posted > 0" in block, "CTA block must mention posted > 0 as an actionable outcome"
    assert "deduped > 0" in block, "CTA block must mention deduped > 0 as an actionable outcome"


def test_pr_review_cta_clean_approval_suppression_preserved():
    """The clean-approval suppression (APPROVE + no findings) must remain."""
    text = PR_REVIEW_SKILL.read_text()
    block = _suppression_block(text)
    assert "APPROVE" in block, "CTA block must still suppress on clean APPROVE"
    assert "posted = 0" in block, "CTA block must still reference posted = 0 in suppression"
    assert "deduped = 0" in block, "CTA block must still reference deduped = 0 in suppression"


# ── workflow-pr-review-followup/SKILL.md ─────────────────────────────────────


def test_pr_review_followup_cta_no_identity_suppression():
    """The CTA suppression block must NOT gate on CURRENT_USER == AUTHOR_LOGIN."""
    text = PR_REVIEW_FOLLOWUP_SKILL.read_text()
    block = _suppression_block(text)
    assert "CURRENT_USER == AUTHOR_LOGIN" not in block, (
        "workflow-pr-review-followup/SKILL.md still suppresses the CTA on author identity. "
        "Remove the identity axis — suppression should be outcome-only."
    )


def test_pr_review_followup_cta_no_self_review_suppression():
    """The CTA suppression block must NOT reference IS_SELF_REVIEW or self-review."""
    text = PR_REVIEW_FOLLOWUP_SKILL.read_text()
    block = _suppression_block(text)
    assert "IS_SELF_REVIEW" not in block, (
        "CTA block (followup) must not gate on IS_SELF_REVIEW — outcome axis only. "
        "IS_SELF_REVIEW belongs on the GitHub-submission gate, not the CTA."
    )
    assert not re.search(r"(?i)self.?review", block), (
        "CTA block (followup) must not mention self-review as a suppression trigger."
    )


def test_pr_review_followup_cta_outcome_axis_present():
    """The CTA emission block must reference the outcome axis conditions."""
    text = PR_REVIEW_FOLLOWUP_SKILL.read_text()
    block = _suppression_block(text)
    assert "DECISION = COMMENT" in block or "DECISION=COMMENT" in block, (
        "CTA block (followup) must mention DECISION = COMMENT as an actionable outcome"
    )
    assert "posted > 0" in block, "CTA block (followup) must mention posted > 0"
    assert "deduped > 0" in block, "CTA block (followup) must mention deduped > 0"


def test_pr_review_followup_cta_clean_approval_suppression_preserved():
    """The clean-approval suppression (APPROVE + no findings) must remain."""
    text = PR_REVIEW_FOLLOWUP_SKILL.read_text()
    block = _suppression_block(text)
    assert "APPROVE" in block, "CTA block (followup) must still suppress on clean APPROVE"
    assert "posted = 0" in block, "CTA block (followup) must still reference posted = 0"
    assert "deduped = 0" in block, "CTA block (followup) must still reference deduped = 0"


# ── AskUserQuestion contract ──────────────────────────────────────────────────


def test_pr_review_cta_uses_ask_user_question():
    """The CTA section must call AskUserQuestion with a valid schema, not free-text prose."""
    import json as _json
    text = PR_REVIEW_SKILL.read_text()
    block = _suppression_block(text)
    assert "AskUserQuestion" in block, (
        "CTA section must reference the AskUserQuestion tool — not a free-text 'reply yes' prompt."
    )
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", block, re.DOTALL)
    assert json_match, "CTA section must contain a fenced JSON block for AskUserQuestion"
    parsed = _json.loads(json_match.group(1))
    assert "questions" in parsed and parsed["questions"], (
        "AskUserQuestion JSON block must have a non-empty 'questions' array"
    )


def test_pr_review_followup_cta_uses_ask_user_question():
    """The CTA section (followup) must call AskUserQuestion with a valid schema."""
    import json as _json
    text = PR_REVIEW_FOLLOWUP_SKILL.read_text()
    block = _suppression_block(text)
    assert "AskUserQuestion" in block, (
        "CTA section (followup) must reference AskUserQuestion — not a free-text prompt."
    )
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", block, re.DOTALL)
    assert json_match, "CTA section (followup) must contain a fenced JSON block for AskUserQuestion"
    parsed = _json.loads(json_match.group(1))
    assert "questions" in parsed and parsed["questions"], (
        "AskUserQuestion JSON block (followup) must have a non-empty 'questions' array"
    )
