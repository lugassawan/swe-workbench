"""Tests for the /swe-workbench:document command (closes #176)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
DOCUMENT_CMD = COMMANDS_DIR / "document.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def test_document_command_file_exists():
    """commands/document.md must exist, have valid frontmatter, and reference `tech-writer`."""
    assert DOCUMENT_CMD.exists(), "commands/document.md must exist"
    text = DOCUMENT_CMD.read_text()
    fm = validate.parse_frontmatter(DOCUMENT_CMD, text=text)
    assert fm is not None, "document.md must have valid frontmatter"
    assert "description" in fm, "document.md frontmatter must have a description field"
    assert "`tech-writer`" in text, "document.md must reference the `tech-writer` subagent"


def test_document_command_invokes_ticket_context():
    """commands/document.md must reference `swe-workbench:ticket-context`."""
    assert DOCUMENT_CMD.exists(), "commands/document.md must exist"
    text = DOCUMENT_CMD.read_text()
    assert "`swe-workbench:ticket-context`" in text, (
        "document.md must reference `swe-workbench:ticket-context` "
        "(ticket-context fetch is acceptance criterion #2)"
    )


def test_document_skill_referenced_in_command():
    """All swe-workbench: skill refs in document.md must resolve to skills/ or agents/ on disk."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    text = DOCUMENT_CMD.read_text()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [
        sid for sid in set(pattern.findall(text))
        if not (skills_dir / sid).is_dir() and not (agents_dir / f"{sid}.md").is_file()
    ]
    assert not missing, f"document.md references non-existent skills or agents: {missing}"


def test_document_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:document in the Commands table."""
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:document" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:document in the Commands table"
    )


def test_document_in_readme():
    """README.md Commands bullet must include /swe-workbench:document."""
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "/swe-workbench:document" in text, (
        "README.md must mention /swe-workbench:document"
    )
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, (
        "README.md must have a '- **Commands**' bullet line"
    )
    assert "/swe-workbench:document" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:document"
    )
