"""Tests for audit-codebase command Step 4 — emit-issues offer (#345)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
CMD_MD = ROOT / "commands" / "audit-codebase.md"


def test_command_references_emit_issues_skill():
    text = CMD_MD.read_text()
    assert "workflow-audit-emit-issues" in text, (
        "commands/audit-codebase.md must reference 'workflow-audit-emit-issues'"
    )


def test_command_has_yn_offer():
    text = CMD_MD.read_text()
    assert "(y/n)" in text, (
        "commands/audit-codebase.md must contain a '(y/n)' offer to file findings as issues"
    )


def test_command_has_step4_section():
    text = CMD_MD.read_text()
    assert "Step 4" in text, (
        "commands/audit-codebase.md must have a '## Step 4' section for the emit-issues offer"
    )


def test_command_invokes_skill():
    text = CMD_MD.read_text()
    assert "invoke" in text.lower() and "workflow-audit-emit-issues" in text, (
        "commands/audit-codebase.md must use an action verb to invoke workflow-audit-emit-issues"
    )


def test_command_invokes_skill_on_same_line():
    text = CMD_MD.read_text()
    matching = [
        line for line in text.splitlines()
        if "invoke" in line.lower() and "workflow-audit-emit-issues" in line
    ]
    assert matching, (
        "commands/audit-codebase.md must have 'invoke' and 'workflow-audit-emit-issues' on the same line"
    )


def test_command_offers_only_when_findings_exist():
    text = CMD_MD.read_text()
    assert "0 finding" in text or "If 0" in text or "if 0" in text or "≥1 finding" in text, (
        "commands/audit-codebase.md Step 4 must explicitly gate the offer on ≥1 finding"
    )


def test_command_stop_on_decline():
    text = CMD_MD.read_text().lower()
    assert "decline" in text or "stop" in text, (
        "commands/audit-codebase.md Step 4 must document what happens on decline"
    )
