# tests/test_workflow_address_feedback_skill.py

"""Tests for the workflow-address-feedback skill (closes #218)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-address-feedback"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS_TXT = SKILL_DIR / "triggers.txt"


def test_address_feedback_skill_file_exists():
    """skills/workflow-address-feedback/SKILL.md must exist with valid frontmatter."""
    assert SKILL_MD.exists(), "skills/workflow-address-feedback/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert "name" in fm, "SKILL.md frontmatter must have a name field"
    assert "description" in fm, "SKILL.md frontmatter must have a description field"
    assert fm.get("orchestrator") == "true", (
        "SKILL.md frontmatter must have orchestrator: true"
    )


def test_address_feedback_triggers_txt():
    """triggers.txt must exist and have at least 2 non-comment, non-blank lines."""
    assert TRIGGERS_TXT.exists(), "skills/workflow-address-feedback/triggers.txt must exist"
    lines = [
        ln.strip()
        for ln in TRIGGERS_TXT.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2, (
        f"triggers.txt must have at least 2 non-comment lines, got {len(lines)}: {lines}"
    )


def test_address_feedback_skill_references_reply_rest_endpoint():
    """SKILL.md must reference the per-thread reply REST endpoint for inline replies."""
    text = SKILL_MD.read_text()
    assert re.search(r"pulls/.*comments/.*replies", text), (
        "SKILL.md must reference the REST reply endpoint pattern: "
        "pulls/{N}/comments/{id}/replies"
    )


def test_address_feedback_skill_references_resolve_mutation():
    """SKILL.md must reference the resolveReviewThread GraphQL mutation."""
    text = SKILL_MD.read_text()
    assert "resolveReviewThread" in text, (
        "SKILL.md must reference the resolveReviewThread GraphQL mutation"
    )


def test_address_feedback_skill_uses_three_way_triage():
    """SKILL.md must define the ADDRESSED / CLARIFIED / DEFERRED three-way triage."""
    text = SKILL_MD.read_text()
    assert "ADDRESSED" in text, "SKILL.md must reference ADDRESSED triage state"
    assert "CLARIFIED" in text, "SKILL.md must reference CLARIFIED triage state"
    assert "DEFERRED" in text, "SKILL.md must reference DEFERRED triage state"
