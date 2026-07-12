# tests/test_workflow_pr_review_cta_suppression.py

"""Pin the address-feedback CTA suppression contract for the shared PR-review
posting core.

Bug: IS_SELF_REVIEW caused the CTA to be silently dropped when the user ran
/implement -> /review on their own PR, even when findings were posted. The fix
removes the identity axis from the CTA gate -- only the outcome axis gates it.

Since #499, the CTA lives in workflow-pr-review-post/SKILL.md (Step 5) --
it used to be duplicated verbatim in workflow-pr-review/SKILL.md and
workflow-pr-review-followup/SKILL.md; both now delegate to the shared core
instead, so this contract is pinned once against the single source of truth.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
POST_CORE_SKILL = ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md"


def _suppression_block(text: str) -> str:
    """Extract the paragraph(s) making up the CTA step."""
    match = re.search(
        r"## Step 5 — Address-feedback CTA \(conditional\).*?(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not locate the '## Step 5 — Address-feedback CTA (conditional)' section. "
        "The CTA section header was renamed or removed — update the regex in _suppression_block."
    )
    return match.group(0)


def test_cta_no_identity_suppression():
    """The CTA suppression block must NOT gate on CURRENT_USER == AUTHOR_LOGIN."""
    text = POST_CORE_SKILL.read_text()
    block = _suppression_block(text)
    assert "CURRENT_USER == AUTHOR_LOGIN" not in block, (
        "workflow-pr-review-post/SKILL.md still suppresses the CTA based on author identity. "
        "Remove the identity axis — suppression should be outcome-only."
    )


def test_cta_no_self_review_suppression():
    """The CTA suppression block must NOT reference IS_SELF_REVIEW or self-review."""
    text = POST_CORE_SKILL.read_text()
    block = _suppression_block(text)
    assert "IS_SELF_REVIEW" not in block, (
        "CTA block must not gate on IS_SELF_REVIEW — outcome axis only. "
        "IS_SELF_REVIEW belongs on the GitHub-submission gate, not the CTA."
    )
    assert not re.search(r"(?i)self.?review", block), (
        "CTA block must not mention self-review as a suppression trigger."
    )


def test_cta_outcome_axis_present():
    """The CTA emission block must reference the outcome axis conditions."""
    text = POST_CORE_SKILL.read_text()
    block = _suppression_block(text)
    assert "DECISION = COMMENT" in block or "DECISION=COMMENT" in block, (
        "CTA block must mention DECISION = COMMENT as an actionable outcome"
    )
    assert "posted > 0" in block, "CTA block must mention posted > 0 as an actionable outcome"
    assert "deduped > 0" in block, "CTA block must mention deduped > 0 as an actionable outcome"


def test_cta_clean_approval_suppression_preserved():
    """The clean-approval suppression (APPROVE + no findings) must remain."""
    text = POST_CORE_SKILL.read_text()
    block = _suppression_block(text)
    assert "APPROVE" in block, "CTA block must still suppress on clean APPROVE"
    assert "posted = 0" in block, "CTA block must still reference posted = 0 in suppression"
    assert "deduped = 0" in block, "CTA block must still reference deduped = 0 in suppression"


def test_cta_uses_ask_user_question():
    """The CTA section must call AskUserQuestion with a valid schema, not free-text prose."""
    import json as _json
    text = POST_CORE_SKILL.read_text()
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


def test_consumers_delegate_cta_not_duplicate_it():
    """workflow-pr-review and workflow-pr-review-followup must NOT re-duplicate
    the CTA mechanism — they delegate to the core instead (issue #499)."""
    for skill_name in ("workflow-pr-review", "workflow-pr-review-followup"):
        text = (ROOT / "skills" / skill_name / "SKILL.md").read_text()
        assert "swe-workbench:workflow-pr-review-post" in text, (
            f"{skill_name}/SKILL.md must invoke swe-workbench:workflow-pr-review-post "
            "instead of re-implementing the CTA/dedup/submit mechanism inline."
        )
        assert "AskUserQuestion" not in text, (
            f"{skill_name}/SKILL.md must not duplicate the AskUserQuestion CTA block — "
            "that mechanism now lives solely in workflow-pr-review-post/SKILL.md."
        )
