"""Tests for workflow-bug-triage label discovery (#247)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL_MD = ROOT / "skills" / "workflow-bug-triage" / "SKILL.md"


def test_bug_triage_runs_gh_label_list():
    """SKILL.md must call `gh label list` during template discovery (Phase 4)."""
    text = SKILL_MD.read_text()
    assert "gh label list" in text, (
        "skills/workflow-bug-triage/SKILL.md must call `gh label list`"
    )


def test_bug_triage_default_label_is_bug():
    """The default label for bug-triage-filed issues must be `bug`."""
    text = SKILL_MD.read_text()
    assert '--label "bug"' in text or "--label 'bug'" in text, (
        'skills/workflow-bug-triage/SKILL.md must show --label "bug" '
        "in the example gh issue create command"
    )


def test_bug_triage_preview_documents_label_override():
    """Preview gate must mention the user can override the chosen label."""
    text = SKILL_MD.read_text().lower()
    assert "label" in text and ("override" in text or "change" in text), (
        "SKILL.md must tell the user how to override the chosen label"
    )
