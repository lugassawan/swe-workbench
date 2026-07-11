"""Cross-file contract tests for the worker→orchestrator design-fork consult (closes #498).

`debugger` (and every other worker subagent) holds no `Agent` tool, so it cannot
itself "consult senior-engineer" the way the original #498 report assumed. The
real fix is a documented contract: a worker *surfaces* a design fork in its
output; the orchestrator — which does hold `Agent` — owns the `senior-engineer`
consult. This module pins that contract at its two homes:

- `skills/workflow-development/SKILL.md` — the canonical, fleet-wide statement
  (Phase 2: Implement).
- `commands/debug.md` — the orchestrator-side note giving `/swe-workbench:debug`
  parity with the equivalent note already in `commands/implement.md`.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-development" / "SKILL.md"
DEBUG_COMMAND = ROOT / "commands" / "debug.md"


def _skill_body() -> str:
    assert SKILL.is_file(), "skills/workflow-development/SKILL.md must exist"
    return SKILL.read_text(encoding="utf-8")


def _debug_body() -> str:
    assert DEBUG_COMMAND.is_file(), "commands/debug.md must exist"
    return DEBUG_COMMAND.read_text(encoding="utf-8")


def _phase_2_section(body: str) -> str:
    assert "### Phase 2: Implement" in body, (
        "SKILL.md must have a '### Phase 2: Implement' section to anchor the "
        "design-fork consult contract"
    )
    return body.split("### Phase 2: Implement")[1].split("### Phase 3")[0]


# ---------------------------------------------------------------------------
# skills/workflow-development/SKILL.md — canonical contract
# ---------------------------------------------------------------------------


def test_skill_phase_2_states_workers_hold_no_agent_tool():
    section = _phase_2_section(_skill_body())
    assert "no `Agent` tool" in section or "hold no `Agent` tool" in section, (
        "Phase 2 must state the structural fact that worker subagents hold no "
        "`Agent` tool — this is why a worker cannot consult a peer subagent itself"
    )


def test_skill_phase_2_states_worker_surfaces_fork():
    section = _phase_2_section(_skill_body())
    assert "surface" in section.lower() and "design fork" in section.lower(), (
        "Phase 2 must state that a worker surfaces a design fork in its output "
        "rather than attempting to consult a subagent itself"
    )


def test_skill_phase_2_names_orchestrator_owns_senior_engineer_consult():
    section = _phase_2_section(_skill_body())
    assert "senior-engineer" in section, (
        "Phase 2 must name `senior-engineer` as the consult the orchestrator "
        "owns once a worker has surfaced a design fork"
    )
    assert "orchestrator" in section.lower(), (
        "Phase 2 must attribute ownership of the senior-engineer consult to "
        "the orchestrator, not the worker"
    )


# ---------------------------------------------------------------------------
# commands/debug.md — orchestrator-side parity with commands/implement.md:30
# ---------------------------------------------------------------------------


def test_debug_command_names_senior_engineer_for_design_fork():
    body = _debug_body()
    assert "senior-engineer" in body, (
        "commands/debug.md must name `senior-engineer` as the orchestrator-owned "
        "consult target for a design fork surfaced by the debugger, at parity "
        "with commands/implement.md's mid-implementation-fork note"
    )
    assert "design fork" in body.lower(), (
        "commands/debug.md must reference 'design fork' so the note is "
        "discoverable and consistent with agents/debugger.md's Output contract "
        "and the SKILL.md canonical contract"
    )
