"""Structural tests — skills: frontmatter preload for unconditional principle
skills (issue #558).

Parametrized over the three (agent, skill) pairs that preload their
always-fire principle skill via frontmatter rather than a first-action
Skill() tool call.
"""

from pathlib import Path

import pytest

import validate

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"

PRELOAD_PAIRS = [
    ("reviewer", "principle-code-review"),
    ("test-writer", "principle-tdd"),
    ("refactorer", "principle-refactoring"),
]


def _agent_text(agent_name):
    path = AGENTS_DIR / f"{agent_name}.md"
    assert path.exists(), f"agents/{agent_name}.md does not exist"
    return path.read_text(encoding="utf-8")


def _skill_text(skill_id):
    path = SKILLS_DIR / skill_id / "SKILL.md"
    assert path.exists(), f"skills/{skill_id}/SKILL.md does not exist"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("agent_name,skill_id", PRELOAD_PAIRS)
def test_frontmatter_skills_list_contains_namespaced_entry(agent_name, skill_id):
    text = _agent_text(agent_name)
    fm = validate.parse_frontmatter(AGENTS_DIR / f"{agent_name}.md", text=text)
    assert fm is not None, f"agents/{agent_name}.md must have valid YAML frontmatter"
    entry = f"swe-workbench:{skill_id}"
    assert isinstance(fm.get("skills"), list), (
        f"agents/{agent_name}.md frontmatter 'skills:' must be a YAML block sequence"
    )
    assert entry in fm["skills"], (
        f"agents/{agent_name}.md frontmatter 'skills:' must list {entry!r}"
    )


@pytest.mark.parametrize("agent_name,skill_id", PRELOAD_PAIRS)
def test_backticked_body_reference_survives(agent_name, skill_id):
    """The body bullet must be retained even though the skill is preloaded —
    it's what keeps check_unwired_principle_skills' backticked-needle scan
    satisfied, and is load-bearing per issue #558's grill."""
    text = _agent_text(agent_name)
    assert f"`swe-workbench:{skill_id}`" in text, (
        f"agents/{agent_name}.md must retain a backticked '`swe-workbench:{skill_id}`' "
        "body reference alongside the frontmatter preload"
    )


@pytest.mark.parametrize("agent_name,skill_id", PRELOAD_PAIRS)
def test_skill_carries_preload_canary(agent_name, skill_id):
    """Checks presence only — position (immediately after frontmatter) is a
    documented convention in docs/skill-preload.md, not something this
    substring check (or check_preloaded_skills) enforces."""
    text = _skill_text(skill_id)
    canary = f"SWB-PRELOAD-{skill_id.upper()}"
    assert f"preload-canary: {canary}" in text, (
        f"skills/{skill_id}/SKILL.md must carry a '<!-- preload-canary: {canary} -->' comment"
    )


def test_check_preloaded_skills_passes_on_live_tree():
    validate.FAILURES.clear()
    validate.check_preloaded_skills()
    assert validate.FAILURES == []
