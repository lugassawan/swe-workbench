"""Structural tests — language-skill under-selection fix.

T1: Every code-touching agent body contains @./shared/languages.md.
T2: Every code-touching agent body directly contains a mandatory language-skill
    gate marker (`language-*`) in its consultation section, signalling required
    (not optional) language-skill loading.
T4: Every principle-*/language-* SKILL.md description field contains
    'Auto-load when'.

Tests T1 and T2 fail today (before implementation). T4 fails for
principle-communication and principle-data-modeling.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"

# Agents that review, write, or diagnose code — must consult language skills.
# product-manager is excluded (files GitHub issues; never touches source).
CODE_TOUCHING_AGENTS = [
    "accessibility-auditor",
    "architect",
    "auditor",
    "code-impl",
    "contributor-auditor",
    "debugger",
    "dependency-auditor",
    "migrator",
    "performance-tuner",
    "refactorer",
    "reviewer",
    "security-auditor",
    "senior-engineer",
    "tech-writer",
    "test-reviewer",
    "test-writer",
]


def _agent_text(name: str) -> str:
    path = AGENTS_DIR / f"{name}.md"
    assert path.exists(), f"agents/{name}.md does not exist"
    return path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# T1 — @./shared/languages.md present in every code-touching agent
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", CODE_TOUCHING_AGENTS)
def test_agent_has_languages_catalog_include(agent_name):
    """T1: code-touching agent body must contain @./shared/languages.md."""
    text = _agent_text(agent_name)
    assert "@./shared/languages.md" in text, (
        f"agents/{agent_name}.md is missing '@./shared/languages.md'. "
        "All code-touching agents must include the language-skill catalog."
    )


# ──────────────────────────────────────────────────────────────
# T2 — mandatory language-skill gate present in consultation section
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", CODE_TOUCHING_AGENTS)
def test_agent_has_mandatory_language_gate(agent_name):
    """T2: consultation section must gate on language-* (required, not optional)."""
    text = _agent_text(agent_name)
    # The mandatory gate paragraph uses `language-*` (with the asterisk) to
    # indicate the required invocation pattern. This is the specific signal
    # added by the fix; it is NOT present in the @./shared/languages.md include.
    assert "language-*" in text, (
        f"agents/{agent_name}.md is missing a mandatory language-skill gate "
        "('language-*'). Add a required consultation paragraph that instructs "
        "the agent to detect the language and invoke the matching language-* skill."
    )


# ──────────────────────────────────────────────────────────────
# T4 — 'Auto-load when' present in every principle-*/language-* SKILL.md
# ──────────────────────────────────────────────────────────────


def _skill_dirs_with_prefix(prefix: str):
    return [p for p in SKILLS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]


@pytest.mark.parametrize(
    "skill_dir",
    _skill_dirs_with_prefix("principle-") + _skill_dirs_with_prefix("language-"),
    ids=lambda p: p.name,
)
def test_skill_description_has_autoload_clause(skill_dir):
    """T4: every principle-*/language-* SKILL.md description must contain 'Auto-load when'."""
    skill_md = skill_dir / "SKILL.md"
    assert skill_md.exists(), f"{skill_dir.name}/SKILL.md does not exist"
    text = skill_md.read_text(encoding="utf-8")
    # The 'Auto-load when' clause lives in the YAML frontmatter description field.
    # Match it case-insensitively to tolerate minor capitalisation variation.
    assert re.search(r"auto-load when", text, re.IGNORECASE), (
        f"skills/{skill_dir.name}/SKILL.md description is missing an "
        "'Auto-load when ...' clause. Add it to the description: field in the "
        "YAML frontmatter so users and agents know when the skill activates."
    )
