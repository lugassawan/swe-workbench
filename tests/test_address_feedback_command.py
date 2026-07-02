# tests/test_address_feedback_command.py

"""Tests for the /swe-workbench:address-feedback command (closes #218)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
ADDRESS_FEEDBACK_CMD = COMMANDS_DIR / "address-feedback.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def test_address_feedback_command_file_exists():
    """commands/address-feedback.md must exist, have valid frontmatter with description and argument-hint."""
    assert ADDRESS_FEEDBACK_CMD.exists(), "commands/address-feedback.md must exist"
    text = ADDRESS_FEEDBACK_CMD.read_text()
    fm = validate.parse_frontmatter(ADDRESS_FEEDBACK_CMD, text=text)
    assert fm is not None, "address-feedback.md must have valid frontmatter"
    assert "description" in fm, "address-feedback.md frontmatter must have a description field"
    assert "argument-hint" in fm, "address-feedback.md frontmatter must have an argument-hint field"
    assert "PR" in fm["argument-hint"] or "pr" in fm["argument-hint"].lower(), (
        "argument-hint must reference a PR number"
    )


def test_address_feedback_command_invokes_ticket_context():
    """commands/address-feedback.md must reference `swe-workbench:ticket-context`."""
    assert ADDRESS_FEEDBACK_CMD.exists(), "commands/address-feedback.md must exist"
    text = ADDRESS_FEEDBACK_CMD.read_text()
    assert "`swe-workbench:ticket-context`" in text, (
        "address-feedback.md must reference `swe-workbench:ticket-context`"
    )


def test_address_feedback_skill_refs_resolve():
    """All swe-workbench: skill refs in address-feedback.md must resolve to skills/ or agents/ on disk."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    text = ADDRESS_FEEDBACK_CMD.read_text()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [
        sid for sid in set(pattern.findall(text))
        if not (skills_dir / sid).is_dir() and not (agents_dir / f"{sid}.md").is_file()
    ]
    assert not missing, f"address-feedback.md references non-existent skills or agents: {missing}"


def test_address_feedback_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:address-feedback in the Commands table."""
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:address-feedback" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:address-feedback"
    )


def test_address_feedback_in_readme():
    """README.md Commands bullet must include /swe-workbench:address-feedback."""
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "/swe-workbench:address-feedback" in text, (
        "README.md must mention /swe-workbench:address-feedback"
    )
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, "README.md must have a '- **Commands**' bullet line"
    assert "/swe-workbench:address-feedback" in commands_line, (
        "The '- **Commands**' bullet line must include /swe-workbench:address-feedback"
    )
