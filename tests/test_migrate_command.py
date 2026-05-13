"""Tests for the /swe-workbench:migrate command (closes #173)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
MIGRATE_CMD = COMMANDS_DIR / "migrate.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def test_migrate_command_file_exists():
    """commands/migrate.md must exist, have valid frontmatter, and reference `migrator`."""
    assert MIGRATE_CMD.exists(), "commands/migrate.md must exist"
    text = MIGRATE_CMD.read_text()
    fm = validate.parse_frontmatter(MIGRATE_CMD, text=text)
    assert fm is not None, "migrate.md must have valid frontmatter"
    assert "description" in fm, "migrate.md frontmatter must have a description field"
    assert "`migrator`" in text, "migrate.md must reference the `migrator` subagent"


def test_migrate_command_invokes_ticket_context():
    """commands/migrate.md must reference `swe-workbench:ticket-context`."""
    assert MIGRATE_CMD.exists(), "commands/migrate.md must exist"
    text = MIGRATE_CMD.read_text()
    assert "`swe-workbench:ticket-context`" in text, (
        "migrate.md must reference `swe-workbench:ticket-context` "
        "(ticket-context fetch is acceptance criterion #2)"
    )


def test_migrate_skill_referenced_in_command():
    """All swe-workbench: skill refs in migrate.md must resolve to skills/ on disk."""
    skills_dir = ROOT / "skills"
    text = MIGRATE_CMD.read_text()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [sid for sid in set(pattern.findall(text)) if not (skills_dir / sid).is_dir()]
    assert not missing, f"migrate.md references non-existent skills: {missing}"


def test_migrate_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:migrate in the Commands table."""
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:migrate" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:migrate in the Commands table"
    )


def test_migrate_in_readme():
    """README.md Commands bullet must include /swe-workbench:migrate."""
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "/swe-workbench:migrate" in text, (
        "README.md must mention /swe-workbench:migrate"
    )
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, (
        "README.md must have a '- **Commands**' bullet line"
    )
    assert "/swe-workbench:migrate" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:migrate"
    )
    refactor_pos = commands_line.find("/swe-workbench:refactor")
    migrate_pos = commands_line.find("/swe-workbench:migrate")
    assert refactor_pos != -1 and migrate_pos > refactor_pos, (
        "README Commands bullet must list /swe-workbench:migrate after /swe-workbench:refactor"
    )
