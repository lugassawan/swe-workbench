"""Structural tests for agents/debugger.md (closes #404, #498)."""

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


# ---------------------------------------------------------------------------
# Design-fork escalation (closes #498)
# ---------------------------------------------------------------------------


def test_design_flaw_rule_surfaces_not_consults():
    """The design-flaw rule must use surface/output wording, not 'consult'."""
    body = _read()
    section = _section(body, "Absolute rules")
    lines = section.splitlines()
    design_flaw_line = next(
        (ln for ln in lines if "design flaw" in ln.lower()), ""
    )
    assert design_flaw_line, "'## Absolute rules' must have a design-flaw rule"
    assert "surface" in design_flaw_line.lower(), (
        "the design-flaw rule must tell the agent to surface the fork in its "
        "output, not to consult a peer subagent it has no tool access to"
    )
    assert "design fork" in design_flaw_line.lower(), (
        "the design-flaw rule must name the concept 'design fork' so it lines "
        "up with the Output-contract slot and the orchestrator-side contract"
    )


def test_design_flaw_rule_states_no_agent_tool():
    """The design-flaw rule must state the debugger cannot consult subagents itself."""
    body = _read()
    section = _section(body, "Absolute rules")
    lines = section.splitlines()
    design_flaw_line = next(
        (ln for ln in lines if "design flaw" in ln.lower()), ""
    )
    assert "`Agent`" in design_flaw_line or "Agent tool" in design_flaw_line, (
        "the design-flaw rule must state the structural fact that the debugger "
        "does not hold the Agent tool"
    )
    assert "cannot consult" in design_flaw_line.lower(), (
        "the design-flaw rule must state the debugger cannot consult other "
        "subagents itself — deciding/running a consult is the orchestrator's job"
    )


def test_output_contract_has_design_fork_slot():
    """The Output contract must carry a 'Design fork' slot."""
    body = _read()
    section = _section(body, "Output contract")
    assert "design fork" in section.lower(), (
        "'## Output contract' must include a 'Design fork' line so orchestrators "
        "know to look for a surfaced fork in the debugger's output"
    )


def test_debugger_never_names_senior_engineer():
    """Regression guard: debugger.md must never name senior-engineer at all.

    The debugger has no `Agent` tool and cannot invoke subagents. Naming
    senior-engineer anywhere in this file — as a consult target, an "escalate
    to" pointer, or a bare reference — re-opens the impossible worker->peer
    consult that issue #498 reports. Only the orchestrator (commands/debug.md,
    SKILL.md) may name senior-engineer as a consult target.
    """
    body = _read()
    assert "senior-engineer" not in body.lower(), (
        "agents/debugger.md must not name senior-engineer anywhere — "
        "the debugger has no Agent tool; only the orchestrator may own that consult"
    )
