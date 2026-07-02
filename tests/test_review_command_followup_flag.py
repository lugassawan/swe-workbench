# tests/test_review_command_followup_flag.py

"""Tests for the --check-followup flag added to commands/review.md (closes #218)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
REVIEW_CMD = ROOT / "commands" / "review.md"
SKILL_DIR = ROOT / "skills"


def test_review_command_recognizes_check_followup_flag():
    """commands/review.md Step 1 argument parsing must recognize --check-followup."""
    assert REVIEW_CMD.exists(), "commands/review.md must exist"
    text = REVIEW_CMD.read_text()
    assert "--check-followup" in text, (
        "commands/review.md must recognize the --check-followup flag in argument parsing"
    )


def test_review_command_followup_delegates_to_followup_skill():
    """commands/review.md must delegate --check-followup to swe-workbench:workflow-pr-review-followup."""
    assert REVIEW_CMD.exists(), "commands/review.md must exist"
    text = REVIEW_CMD.read_text()
    assert "swe-workbench:workflow-pr-review-followup" in text, (
        "commands/review.md must reference swe-workbench:workflow-pr-review-followup "
        "as the delegation target for --check-followup"
    )


def test_review_command_argument_hint_includes_followup_flag():
    """commands/review.md frontmatter argument-hint must document --check-followup."""
    assert REVIEW_CMD.exists(), "commands/review.md must exist"
    text = REVIEW_CMD.read_text()
    fm = validate.parse_frontmatter(REVIEW_CMD, text=text)
    assert fm is not None, "review.md must have valid frontmatter"
    assert "argument-hint" in fm, "review.md frontmatter must have an argument-hint field"
    assert "--check-followup" in fm["argument-hint"], (
        "review.md frontmatter argument-hint must document the --check-followup flag"
    )
