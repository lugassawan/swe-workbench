"""Tests for the /swe-workbench:doctor command (closes #238)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
DOCTOR_CMD = COMMANDS_DIR / "doctor.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def test_doctor_command_file_exists():
    """commands/doctor.md must exist and have valid frontmatter with description."""
    assert DOCTOR_CMD.exists(), "commands/doctor.md must exist"
    text = DOCTOR_CMD.read_text()
    fm = validate.parse_frontmatter(DOCTOR_CMD, text=text)
    assert fm is not None, "doctor.md must have valid frontmatter"
    assert "description" in fm, "doctor.md frontmatter must have a description field"


def test_doctor_mentions_probe_targets():
    """commands/doctor.md must reference the probe script and each tool name."""
    assert DOCTOR_CMD.exists(), "commands/doctor.md must exist"
    text = DOCTOR_CMD.read_text()
    assert "runtime/doctor.sh" in text, "doctor.md must reference runtime/doctor.sh"
    for tool in ("gh", "git", "jq", "rimba", "claude"):
        assert tool in text, f"doctor.md must mention probe target '{tool}'"


def test_doctor_no_broken_skill_refs():
    """All swe-workbench: skill refs in doctor.md must resolve to skills/ or agents/ on disk."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    text = DOCTOR_CMD.read_text()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [
        sid for sid in set(pattern.findall(text))
        if not (skills_dir / sid).is_dir() and not (agents_dir / f"{sid}.md").is_file()
    ]
    assert not missing, f"doctor.md references non-existent skills or agents: {missing}"


def test_doctor_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:doctor in the Commands table."""
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:doctor" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:doctor in the Commands table"
    )


def test_doctor_in_readme():
    """README.md Commands bullet must include /swe-workbench:doctor."""
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "/swe-workbench:doctor" in text, (
        "README.md must mention /swe-workbench:doctor"
    )
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, (
        "README.md must have a '- **Commands**' bullet line"
    )
    assert "/swe-workbench:doctor" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:doctor"
    )


def test_doctor_invokes_script_portably():
    """doctor.md must invoke the script via $CLAUDE_PLUGIN_ROOT (portable for plugin installs, #328)."""
    text = DOCTOR_CMD.read_text()
    assert "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh" in text, (
        "doctor.md must invoke the script via $CLAUDE_PLUGIN_ROOT for plugin-install portability"
    )
    assert "bash scripts/doctor.sh" not in text, (
        "doctor.md must not invoke the script via a non-portable bare relative path"
    )
