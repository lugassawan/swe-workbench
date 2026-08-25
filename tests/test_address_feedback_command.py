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
SKILL_MD = ROOT / "skills" / "workflow-address-feedback" / "SKILL.md"


def _skill_phase_number(title_fragment: str) -> str:
    """Phase number whose SKILL.md heading matches `title_fragment` (em-dash separated)."""
    m = re.search(rf"^#+ Phase (\d+) — {re.escape(title_fragment)}", SKILL_MD.read_text(), re.M)
    assert m is not None, f"SKILL.md must have a 'Phase N — {title_fragment}' heading"
    return m.group(1)


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


def test_address_feedback_command_drops_retired_worktree_form():
    """commands/address-feedback.md must not describe the retired throwaway-task-branch worktree flow."""
    text = ADDRESS_FEEDBACK_CMD.read_text()
    assert "pr:$PR" not in text, (
        "address-feedback.md still references the retired 'pr:$PR' rimba task form"
    )
    assert '--task "address-feedback-$PR"' not in text, (
        "address-feedback.md still references the retired throwaway task-branch flag"
    )


def test_address_feedback_command_cites_current_worktree_phases():
    """commands/address-feedback.md must cite SKILL.md's actual Worktree/Cleanup phase numbers."""
    text = ADDRESS_FEEDBACK_CMD.read_text()
    worktree_phase = f"Phase {_skill_phase_number('Worktree')}"
    cleanup_phase = f"Phase {_skill_phase_number('Cleanup')}"
    assert worktree_phase in text, (
        f"address-feedback.md must cite '{worktree_phase}' for worktree setup"
    )
    assert cleanup_phase in text, (
        f"address-feedback.md must cite '{cleanup_phase}' for cleanup"
    )


def test_address_feedback_command_describes_pr_branch_worktree():
    """commands/address-feedback.md must pin the current PR-branch worktree create form."""
    text = ADDRESS_FEEDBACK_CMD.read_text()
    assert 'rimba add "$PR_BRANCH" --source "origin/$PR_BRANCH"' in text, (
        "address-feedback.md must describe worktree creation on the PR branch itself"
    )


def test_address_feedback_catalog_row_has_no_stale_cleanup_claim():
    """docs/catalog.md's workflow-address-feedback row must not claim 'no auto-cleanup'."""
    text = DOCS_CATALOG.read_text()
    lines = text.splitlines()
    row = next(
        (ln for ln in lines if "swe-workbench:workflow-address-feedback" in ln),
        None,
    )
    assert row is not None, "docs/catalog.md must have a row for swe-workbench:workflow-address-feedback"
    assert "no auto-cleanup" not in row, (
        "docs/catalog.md workflow-address-feedback row still claims 'no auto-cleanup'"
    )
