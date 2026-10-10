# tests/test_workflow_pr_review_cta_suppression.py

"""Pin the address-feedback CTA eligibility contract for the shared posting core.

The CTA is offered only when the authenticated reviewer is the known PR author
and the review produced an actionable outcome. General, followup, and
specialist PR reviews all delegate to this one contract.
"""

import re
from pathlib import Path

import pytest

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


def test_cta_requires_known_matching_reviewer_and_pr_author():
    """The CTA must require a known authenticated reviewer who authored the PR."""
    block = _suppression_block(POST_CORE_SKILL.read_text())
    assert "both `CURRENT_USER` and `AUTHOR_LOGIN` are non-empty" in block
    assert "`CURRENT_USER == AUTHOR_LOGIN`" in block
    assert "exact, case-sensitive string equality" in block
    assert "Suppress silently when either identity is empty or when they differ" in block
    assert "repository `OWNER` is not an identity input" in block
    assert ".data.decision`, not `.data.event`" in block
    assert "under self-review `.data.event` is always `COMMENT`" in block


def test_cta_does_not_restore_outcome_only_gate():
    """The retired outcome-only rule must not contradict the identity gate."""
    block = _suppression_block(POST_CORE_SKILL.read_text())
    assert "Identity does NOT gate" not in block


def test_cta_outcome_axis_present():
    """The CTA emission block must reference the outcome axis conditions."""
    text = POST_CORE_SKILL.read_text()
    block = _suppression_block(text)
    assert ".data.decision = COMMENT" in block or ".data.decision=COMMENT" in block, (
        "CTA block must mention .data.decision = COMMENT as an actionable outcome — "
        "field reads moved from a shell $DECISION var to the .data.decision envelope path"
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


@pytest.mark.parametrize(
    ("path", "section"),
    (
        (ROOT / "skills" / "workflow-pr-review" / "SKILL.md", "### Step 6"),
        (ROOT / "commands" / "review.md", "## Specialist post sub-flow"),
    ),
)
def test_consumers_delegate_cta_with_both_identities(path: Path, section: str):
    """Each caller passes both identities at its shared-core invocation site."""
    text = path.read_text()
    delegation = text.split(section, maxsplit=1)[1]
    assert "swe-workbench:workflow-pr-review-post" in delegation
    assert "CURRENT_USER" in delegation
    assert "AUTHOR_LOGIN" in delegation
    assert "Want me to help address this feedback?" not in delegation
