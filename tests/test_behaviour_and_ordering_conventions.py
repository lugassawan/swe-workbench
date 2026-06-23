"""Structural tests for tell-don't-ask + member-ordering conventions (closes #459).

Acceptance criteria:
- skills/principle-ddd/SKILL.md body names both 'tell' (don't-ask) and 'anemic' domain.
- skills/principle-clean-code/SKILL.md has a '## Member ordering' section that states
  'public → protected → private' and mentions modifier-less languages (Go, Rust, or Python).
- agents/reviewer.md Principle consultation list references swe-workbench:principle-ddd.
- agents/code-impl.md Principle consultation list references swe-workbench:principle-ddd.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

DDD_SKILL = ROOT / "skills" / "principle-ddd" / "SKILL.md"
CLEAN_CODE_SKILL = ROOT / "skills" / "principle-clean-code" / "SKILL.md"
REVIEWER_AGENT = ROOT / "agents" / "reviewer.md"
CODE_IMPL_AGENT = ROOT / "agents" / "code-impl.md"


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next ## heading (skips fenced blocks)."""
    marker = f"## {heading}"
    assert marker in body, f"Expected '{marker}' section not found"
    start = body.index(marker) + len(marker)
    rest = body[start:]
    fence_open = False
    lines = []
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~~"):
            fence_open = not fence_open
        if not fence_open and line.startswith("## "):
            break
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AC 1 — principle-ddd names tell-don't-ask and anemic domain
# ---------------------------------------------------------------------------


def test_ddd_skill_file_exists():
    assert DDD_SKILL.exists(), "skills/principle-ddd/SKILL.md must exist"


def test_ddd_skill_names_tell_dont_ask():
    """Entity subsection must explicitly use 'tell' (covering tell-don't-ask)."""
    body = DDD_SKILL.read_text()
    assert "tell" in body.lower(), (
        "skills/principle-ddd/SKILL.md must mention 'tell' (tell-don't-ask principle) "
        "so reviewers and implementers can surface the anti-pattern"
    )


def test_ddd_skill_names_anemic_domain():
    """Skill body must explicitly name 'anemic' domain model as an anti-pattern."""
    body = DDD_SKILL.read_text()
    assert "anemic" in body.lower(), (
        "skills/principle-ddd/SKILL.md must mention 'anemic' (anemic domain model) "
        "so reviewers and implementers can surface the anti-pattern"
    )


# ---------------------------------------------------------------------------
# AC 2 — principle-clean-code has a Member ordering section
# ---------------------------------------------------------------------------


def test_clean_code_skill_file_exists():
    assert CLEAN_CODE_SKILL.exists(), "skills/principle-clean-code/SKILL.md must exist"


def test_clean_code_has_member_ordering_section():
    body = CLEAN_CODE_SKILL.read_text()
    assert "## Member ordering" in body, (
        "skills/principle-clean-code/SKILL.md must contain a '## Member ordering' section "
        "so the convention has a canonical normative home"
    )


def test_member_ordering_states_public_protected_private():
    """The section must name the canonical order: public → protected → private."""
    body = CLEAN_CODE_SKILL.read_text()
    section = _section(body, "Member ordering")
    # Accept arrow variants and plain text describing the order
    has_order = (
        "public" in section.lower()
        and "protected" in section.lower()
        and "private" in section.lower()
    )
    assert has_order, (
        "'## Member ordering' must state the ordering of public, protected, and private members"
    )


def test_member_ordering_mentions_modifier_less_languages():
    """The section must acknowledge languages without access modifiers (Go, Rust, or Python)."""
    body = CLEAN_CODE_SKILL.read_text()
    section = _section(body, "Member ordering")
    section_lower = section.lower()
    has_modifier_less = (
        bool(re.search(r"\bgo\b", section_lower))
        or bool(re.search(r"\brust\b", section_lower))
        or bool(re.search(r"\bpython\b", section_lower))
    )
    assert has_modifier_less, (
        "'## Member ordering' must mention at least one modifier-less language "
        "(Go, Rust, or Python) so the rule is clear for those ecosystems"
    )


# ---------------------------------------------------------------------------
# AC 3 — agents/reviewer.md Principle consultation references principle-ddd
# ---------------------------------------------------------------------------


def test_reviewer_agent_file_exists():
    assert REVIEWER_AGENT.exists(), "agents/reviewer.md must exist"


def test_reviewer_references_principle_ddd():
    body = REVIEWER_AGENT.read_text()
    assert "swe-workbench:principle-ddd" in body, (
        "agents/reviewer.md Principle consultation must reference 'swe-workbench:principle-ddd' "
        "so the reviewer catches anemic domain models and tell-don't-ask violations"
    )


# ---------------------------------------------------------------------------
# AC 4 — agents/code-impl.md Principle consultation references principle-ddd
# ---------------------------------------------------------------------------


def test_code_impl_agent_file_exists():
    assert CODE_IMPL_AGENT.exists(), "agents/code-impl.md must exist"


def test_code_impl_references_principle_ddd():
    body = CODE_IMPL_AGENT.read_text()
    assert "swe-workbench:principle-ddd" in body, (
        "agents/code-impl.md Principle consultation must reference 'swe-workbench:principle-ddd' "
        "so implementers place behaviour on entities and avoid anemic models"
    )
