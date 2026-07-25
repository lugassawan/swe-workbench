"""Structural tests — skills: frontmatter preload for principle skills.

Parametrized over every (agent, skill) pair discovered live from each
agent's `skills:` frontmatter — not a hand-maintained list, so it can't
drift out of sync as agents gain or lose preloaded skills.
"""

from pathlib import Path

import pytest

import validate

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"


def _discover_preload_pairs():
    pairs = []
    for agent_md in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(agent_md)
        if fm is None:
            continue
        entries = fm.get("skills")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if entry.startswith("swe-workbench:"):
                pairs.append((agent_md.stem, entry.split(":", 1)[1]))
    return pairs


PRELOAD_PAIRS = _discover_preload_pairs()


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


def test_preload_pairs_were_discovered():
    """Guards against PRELOAD_PAIRS silently discovering zero pairs (e.g. a
    parse_frontmatter regression) — an empty parametrize list would make
    every test above vacuously not-run rather than fail."""
    assert len(PRELOAD_PAIRS) >= 20, (
        f"expected at least 20 (agent, skill) preload pairs across the live tree, "
        f"found {len(PRELOAD_PAIRS)} — check_preloaded_skills discovery may be broken"
    )
