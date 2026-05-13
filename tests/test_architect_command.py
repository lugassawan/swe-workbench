"""Tests for the /swe-workbench:architect command (closes #174)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
ARCHITECT_CMD = COMMANDS_DIR / "architect.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def test_architect_command_file_exists():
    """commands/architect.md must exist, have valid frontmatter, and reference `architect`."""
    assert ARCHITECT_CMD.exists(), "commands/architect.md must exist"
    text = ARCHITECT_CMD.read_text()
    fm = validate.parse_frontmatter(ARCHITECT_CMD, text=text)
    assert fm is not None, "architect.md must have valid frontmatter"
    assert "description" in fm, "architect.md frontmatter must have a description field"
    # `name` is intentionally absent: commands are auto-discovered by filename; validate.py only requires `description`.
    assert "`architect`" in text, "architect.md must reference the `architect` subagent"


def test_architect_command_invokes_ticket_context():
    """commands/architect.md must reference `swe-workbench:ticket-context`."""
    assert ARCHITECT_CMD.exists(), "commands/architect.md must exist"
    text = ARCHITECT_CMD.read_text()
    assert "`swe-workbench:ticket-context`" in text, (
        "architect.md must reference `swe-workbench:ticket-context` "
        "(ticket-context fetch is acceptance criterion #2)"
    )


def test_architect_skill_referenced_in_command():
    """All swe-workbench: skill refs in architect.md must resolve to skills/ or agents/ on disk."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    text = ARCHITECT_CMD.read_text()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [
        sid for sid in set(pattern.findall(text))
        if not (skills_dir / sid).is_dir() and not (agents_dir / f"{sid}.md").is_file()
    ]
    assert not missing, f"architect.md references non-existent skills or agents: {missing}"


def test_architect_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:architect in the Commands table."""
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:architect" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:architect in the Commands table"
    )


def test_architect_in_readme():
    """README.md Commands bullet must include /swe-workbench:architect."""
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "/swe-workbench:architect" in text, (
        "README.md must mention /swe-workbench:architect"
    )
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, (
        "README.md must have a '- **Commands**' bullet line"
    )
    assert "/swe-workbench:architect" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:architect"
    )
