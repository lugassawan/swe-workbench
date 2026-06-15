"""Structural tests for agents/debugger.md (closes #404)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "debugger.md"


def _read() -> str:
    assert AGENT.exists(), "agents/debugger.md must exist"
    return AGENT.read_text()


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next real ## heading.

    Skips ## lines inside fenced code blocks.
    """
    marker = f"## {heading}"
    assert marker in body, f"debugger.md must contain '{marker}'"
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
# Existence + frontmatter
# ---------------------------------------------------------------------------


def test_agent_file_exists():
    assert AGENT.exists(), "agents/debugger.md must exist"


def test_frontmatter_name_is_debugger():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    assert fm is not None, "debugger.md must have valid YAML frontmatter"
    assert fm.get("name") == "debugger", (
        "frontmatter 'name' must be 'debugger'"
    )


def test_tools_includes_edit_and_skill():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    tools = fm.get("tools", "")
    assert "Edit" in tools, "tools: must include 'Edit' (agent writes fix files)"
    assert "Skill" in tools, "tools: must include 'Skill' (agent consults principles)"


# ---------------------------------------------------------------------------
# Placement guidance
# ---------------------------------------------------------------------------


def test_absolute_rules_mention_sibling_convention():
    """Absolute rules must mention scanning sibling files for new type placement."""
    body = _read()
    section = _section(body, "Absolute rules")
    assert "sibling" in section.lower(), (
        "'## Absolute rules' must mention scanning sibling files for new type placement "
        "so the agent follows the package structure discipline when a fix introduces a new type"
    )


def test_minimal_fix_line_notes_placement_choice():
    """The Minimal-fix output-contract line must mention placement choice."""
    body = _read()
    section = _section(body, "Output contract")
    lines = section.splitlines()
    minimal_fix_line = next(
        (ln for ln in lines if "minimal fix" in ln.lower()), ""
    )
    assert "placement" in minimal_fix_line.lower(), (
        "The 'Minimal fix' output-contract line must mention placement choice "
        "so reviewers know where a new type introduced by the fix was placed"
    )


def test_principle_clean_architecture_referenced():
    """agents/debugger.md must reference swe-workbench:principle-clean-architecture."""
    body = _read()
    assert "swe-workbench:principle-clean-architecture" in body, (
        "agents/debugger.md must reference 'swe-workbench:principle-clean-architecture' "
        "for the placement fallback when sibling structure is incoherent"
    )
