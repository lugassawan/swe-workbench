# tests/test_workflow_pr_review_no_address_cta.py

"""Pin the removal of the address-feedback CTA from PR review output.

A review ends once it is posted. Addressing feedback is a separate, explicit
/swe-workbench:address-feedback run, so no PR review mode offers it as a follow-up.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
POST_CORE_SKILL = ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md"
PR_REVIEW_SKILL = ROOT / "skills" / "workflow-pr-review" / "SKILL.md"
REVIEW_COMMAND = ROOT / "commands" / "review.md"
ADDRESS_FEEDBACK_COMMAND = ROOT / "commands" / "address-feedback.md"

CTA_QUESTION = "Want me to help address this feedback?"


def test_post_core_has_no_address_feedback_cta_step():
    """The posting core must not carry the retired Step 5 CTA section."""
    text = POST_CORE_SKILL.read_text()
    assert "Address-feedback CTA" not in text
    assert CTA_QUESTION not in text
    assert "Yes — address feedback" not in text


def test_post_core_never_prompts_the_user():
    """Step 5 was the core's only AskUserQuestion use; the review must not prompt."""
    assert "AskUserQuestion" not in POST_CORE_SKILL.read_text()


@pytest.mark.parametrize("path", (PR_REVIEW_SKILL, REVIEW_COMMAND))
def test_consumers_do_not_mention_the_cta(path: Path):
    """Callers must not describe or reference a CTA the core no longer offers."""
    text = path.read_text()
    assert CTA_QUESTION not in text
    assert "address-feedback CTA" not in text
    assert "Step 5 CTA" not in text
    assert not re.search(r"\bCTA\b", text)
    assert "address-feedback" not in text


@pytest.mark.parametrize(
    ("path", "section"),
    (
        (PR_REVIEW_SKILL, "### Step 6"),
        (REVIEW_COMMAND, "## Specialist post sub-flow"),
    ),
)
def test_consumers_delegate_with_both_identities(path: Path, section: str):
    """Each caller passes both identities at its shared-core invocation site.

    The self-review clamp still needs CURRENT_USER and AUTHOR_LOGIN.
    """
    delegation = path.read_text().split(section, maxsplit=1)[1]
    assert "swe-workbench:workflow-pr-review-post" in delegation
    assert "CURRENT_USER" in delegation
    assert "AUTHOR_LOGIN" in delegation


def test_address_feedback_command_remains_available():
    """Removing the CTA must not remove the explicit command."""
    assert ADDRESS_FEEDBACK_COMMAND.is_file()
