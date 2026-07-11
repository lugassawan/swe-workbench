"""Structural tests for agents/redundancy-assessor.md (issue #510)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "redundancy-assessor.md"


def _read() -> str:
    assert AGENT.exists(), "agents/redundancy-assessor.md must exist"
    return AGENT.read_text(encoding="utf-8")


def test_agent_file_exists():
    assert AGENT.exists()


def test_frontmatter_name_and_model():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    assert fm is not None
    assert fm.get("name") == "redundancy-assessor"
    assert fm.get("model") == "sonnet"


def test_description_ends_in_advisory_only_clause():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    description = fm.get("description", "")
    assert description, "frontmatter must have a description"
    assert "never" in description.lower(), "description must end in an advisory-only clause"


def test_no_color_field():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    assert "color" not in fm


def test_tools_are_advisory_only_no_edit_or_write():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    tools = fm.get("tools", "")
    for required in ("Read", "Grep", "Glob", "Bash", "Skill"):
        assert required in tools, f"tools: must include '{required}'"
    assert "Edit" not in tools, "redundancy-assessor is advisory only — must not have Edit"
    assert "Write" not in tools, "redundancy-assessor is advisory only — must not have Write"


def test_reachable_via_sync_check_redundancy_flag():
    body = _read()
    assert "**Reachable via:** `/swe-workbench:sync --check-redundancy`" in body


def test_advisory_guardrail_mirrors_conflict_resolver_opening():
    body = _read()
    assert "you are advisory only" in body.lower()
    assert "never edit a file" in body.lower() or "never edit" in body.lower()
    assert "git rm" in body
    assert "workflow-branch-sync" in body


def test_sentinel_line_formats_present():
    body = _read()
    assert "**Redundancy: AUTO-APPLY**" in body
    assert "**Redundancy: ESCALATE**" in body
    assert "**Redundancy: NONE**" in body


def test_sentinel_carries_candidate_id():
    body = _read()
    assert "id=<candidate-id>" in body or "id=<n>" in body or "id=" in body.split("## Output")[1]


def test_output_contract_is_per_finding_not_single_sentinel():
    """Departure from conflict-resolver: one invocation yields N findings, so
    exactly-one-sentinel is scoped per finding, not per invocation."""
    body = _read()
    assert "## Output" in body
    output = body.split("## Output")[1]
    assert "per finding" in output.lower() or "per-finding" in output.lower()
    assert "exactly one" in output.lower()


def test_cites_silence_rule_and_requires_explicit_none():
    body = _read()
    assert "severity-output-contract.md" in body
    assert "silence rule" in body.lower()
    assert "NONE" in body
    assert "never silently omit" in body.lower() or "never omit" in body.lower()


def test_escalate_requires_recommendation_and_evidence():
    body = _read()
    assert "## Output" in body
    output = body.split("## Output")[1]
    assert "ESCALATE" in output
    assert "recommendation" in output.lower()
    assert "remove" in output.lower() and "keep" in output.lower() and "edit" in output.lower()


def test_auto_apply_gated_to_whole_file_refs_zero():
    """Tier guardrail: AUTO-APPLY is permitted ONLY for a whole-file candidate
    with refs=0; any symbol-level or referenced removal must ESCALATE."""
    body = _read()
    assert "refs=0" in body
    assert "AUTO-APPLY" in body
    assert "symbol" in body.lower()
    assert "regardless of confidence" in body.lower()


def test_input_contract_references_redundancy_scope_records():
    body = _read()
    assert "## Input contract" in body
    input_contract = body.split("## Input contract")[1].split("## ")[0]
    assert "CANDIDATE" in input_contract
    assert "MAIN_ADD" in input_contract
    assert "redundancy-scope.sh" in input_contract


def test_includes_both_catalog_slices():
    body = _read()
    assert "@./shared/principles.md" in body
    assert "@./shared/languages.md" in body


def test_never_mutates_directly():
    body = _read()
    assert "never edit" in body.lower() or "never applies" in body.lower() or "you never" in body.lower()
