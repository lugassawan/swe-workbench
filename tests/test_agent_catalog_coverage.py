"""Structural test — agent-to-docs coverage.

Mirrors the T5a pattern in test_agent_language_catalog.py::test_language_skill_in_catalog,
but for agents/*.md instead of skills/language-*: every top-level agent must be
discoverable from both docs/catalog.md (canonical reference table) and README.md
(roster bullet). Prevents a shipped agent from going undocumented, as happened with
e2e-test-verifier, e2e-test-writer, and redundancy-assessor.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
README_MD = ROOT / "README.md"
CATALOG_MD = ROOT / "docs" / "catalog.md"


def _agent_names():
    """Top-level agents/*.md files only — excludes agents/shared/ include fragments."""
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


def _readme_subagents_bullet() -> str:
    text = README_MD.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("- **Subagents**"):
            return line
    raise AssertionError("README.md is missing a '- **Subagents**' bullet")


@pytest.mark.parametrize("agent_name", _agent_names())
def test_agent_in_catalog(agent_name):
    """Every top-level agent must have a row marker in docs/catalog.md."""
    catalog_text = CATALOG_MD.read_text(encoding="utf-8")
    row_marker = f"| `{agent_name}` |"
    assert row_marker in catalog_text, (
        f"docs/catalog.md is missing a row for '{agent_name}'. "
        "Add the agent to the Subagents table."
    )


@pytest.mark.parametrize("agent_name", _agent_names())
def test_agent_in_readme(agent_name):
    """Every top-level agent must be backtick-wrapped in README.md's Subagents bullet."""
    bullet = _readme_subagents_bullet()
    marker = f"`{agent_name}`"
    assert marker in bullet, (
        f"README.md's Subagents bullet is missing '{agent_name}'. "
        "Add it to the roster."
    )
