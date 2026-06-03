"""Structural tests for agents/code-impl.md (closes #261).

Acceptance criteria:
- agents/code-impl.md exists with required frontmatter (name, description).
- tools: includes Edit and Skill.
- At least one slice-catalog ref is present (@./shared/principles.md etc.).
- **Reachable via:** references workflow-delegated-implementation.
- Output-contract section forbids pushing/opening PRs.
- Output-contract section declares a summary return — not diffs.
- Registered in docs/catalog.md Subagents table.
- Registered in README.md Subagents bullet.
"""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "code-impl.md"
CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"

_SLICE_REFS = {
    "@./shared/principles.md",
    "@./shared/languages.md",
    "@./shared/workflows.md",
}


def _read() -> str:
    assert AGENT.exists(), "agents/code-impl.md must exist"
    return AGENT.read_text()


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next real ## heading.

    Skips ## lines inside fenced code blocks.
    """
    marker = f"## {heading}"
    assert marker in body, f"code-impl.md must contain '{marker}'"
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
    assert AGENT.exists(), "agents/code-impl.md must exist"


def test_frontmatter_has_required_fields():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    assert fm is not None, "code-impl.md must have valid YAML frontmatter"
    assert "name" in fm, "frontmatter must have 'name' field"
    assert "description" in fm, "frontmatter must have 'description' field"
    assert "model" in fm, "frontmatter must have 'model' field"
    assert fm["name"] == "code-impl", (
        "frontmatter 'name' must be 'code-impl'"
    )


def test_tools_includes_edit_and_skill():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    tools = fm.get("tools", "")
    assert "Edit" in tools, "tools: must include 'Edit' (agent writes files)"
    assert "Skill" in tools, "tools: must include 'Skill' (agent consults principles)"


# ---------------------------------------------------------------------------
# Slice-catalog reference (validate.py:422-426)
# ---------------------------------------------------------------------------


def test_slice_catalog_ref_present():
    body = _read()
    assert any(ref in body for ref in _SLICE_REFS), (
        "code-impl.md must reference at least one slice catalog "
        "(@./shared/principles.md, @./shared/languages.md, or @./shared/workflows.md)"
    )


# ---------------------------------------------------------------------------
# Reachable-via annotation
# ---------------------------------------------------------------------------


def test_reachable_via_references_workflow_delegated_implementation():
    body = _read()
    assert "workflow-delegated-implementation" in body, (
        "code-impl.md must contain '**Reachable via:**' referencing "
        "'workflow-delegated-implementation'"
    )
    reachable_line = next(
        (ln for ln in body.splitlines() if "Reachable via" in ln),
        None,
    )
    assert reachable_line is not None, (
        "code-impl.md must have a '**Reachable via:**' line"
    )
    assert "workflow-delegated-implementation" in reachable_line, (
        "'**Reachable via:**' line must reference 'workflow-delegated-implementation'"
    )


# ---------------------------------------------------------------------------
# Output contract — proxy tests for AC #3/#4/#6
# ---------------------------------------------------------------------------


def test_output_contract_section_present():
    body = _read()
    assert "## Output contract" in body, (
        "code-impl.md must contain '## Output contract' section"
    )


def test_output_contract_has_four_statuses():
    body = _read()
    section = _section(body, "Output contract")
    for status in ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"):
        assert status in section, (
            f"'## Output contract' must declare the '{status}' status"
        )


def test_output_contract_no_diff_field():
    """The output contract must not introduce a diff-bearing return field."""
    body = _read()
    section = _section(body, "Output contract")
    for forbidden in ("diff:", "`diff`", "full diff", "patch:", "`patch`"):
        assert forbidden not in section.lower(), (
            f"'## Output contract' must not contain a diff-return field (found '{forbidden}'). "
            "Agents return summaries, not diffs."
        )


def test_output_contract_returns_summary():
    body = _read()
    section = _section(body, "Output contract")
    assert "summary" in section.lower(), (
        "'## Output contract' must describe a summary return, not a diff"
    )


# ---------------------------------------------------------------------------
# Absolute rules — no push, no PR
# ---------------------------------------------------------------------------


def test_absolute_rules_forbid_push_and_pr():
    body = _read()
    assert "## Absolute rules" in body, (
        "code-impl.md must contain '## Absolute rules' section"
    )
    section = _section(body, "Absolute rules")
    assert "push" in section.lower(), (
        "'## Absolute rules' must forbid pushing "
        "(delivery stays with the orchestrator)"
    )
    assert "pr" in section.lower(), (
        "'## Absolute rules' must forbid opening PRs "
        "(delivery stays with the orchestrator)"
    )


# ---------------------------------------------------------------------------
# Skill refs resolve on disk
# ---------------------------------------------------------------------------


def test_swe_workbench_skill_refs_resolve():
    """All swe-workbench: skill refs in code-impl.md must resolve to skills/ on disk."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    body = _read()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [
        sid for sid in set(pattern.findall(body))
        if not (skills_dir / sid).is_dir() and not (agents_dir / f"{sid}.md").is_file()
    ]
    assert not missing, (
        f"code-impl.md references non-existent skills or agents: {missing}"
    )


# ---------------------------------------------------------------------------
# Registration checks
# ---------------------------------------------------------------------------


def test_registered_in_catalog_subagents_table():
    assert CATALOG.exists(), "docs/catalog.md must exist"
    text = CATALOG.read_text()
    assert "code-impl" in text, (
        "docs/catalog.md must contain a row for 'code-impl' in the Subagents table"
    )


def test_registered_in_readme_subagents_bullet():
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "code-impl" in text, (
        "README.md must mention 'code-impl' in the Subagents bullet"
    )
    subagents_line = next(
        (ln for ln in text.splitlines() if ln.strip().startswith("- **Subagents**")),
        None,
    )
    assert subagents_line is not None, (
        "README.md must have a '- **Subagents**' bullet line"
    )
    assert "code-impl" in subagents_line, (
        "README.md '- **Subagents**' bullet must include 'code-impl'"
    )


# ---------------------------------------------------------------------------
# Placement guidance
# ---------------------------------------------------------------------------


def test_process_scans_sibling_files_before_placing_type():
    """Process must instruct the agent to scan sibling files before placing a new type."""
    body = _read()
    section = _section(body, "Process")
    # Look for words indicating sibling-file scanning combined with package/convention context
    has_sibling = "sibling" in section.lower()
    has_grep_or_glob = "grep" in section.lower() or "glob" in section.lower()
    has_package_or_convention = "package" in section.lower() or "convention" in section.lower()
    assert has_sibling or (has_grep_or_glob and has_package_or_convention), (
        "'## Process' must instruct the agent to scan/read sibling files "
        "(look for 'sibling', or 'Grep'/'Glob' combined with 'package'/'convention') "
        "before placing a new type"
    )
    # Positional guard: scan mention must precede the placement instruction
    scan_idx = section.lower().find("sibling") if has_sibling else (
        section.lower().find("grep") if has_grep_or_glob else -1
    )
    place_idx = section.lower().find("place")
    assert scan_idx != -1 and (place_idx == -1 or scan_idx < place_idx), (
        "Sibling scan instruction must appear before placement instruction in '## Process'"
    )


def test_output_contract_has_placement_field():
    """The output contract fenced block must include a placement: field."""
    body = _read()
    section = _section(body, "Output contract")
    assert "placement:" in section, (
        "'## Output contract' fenced code block must include a 'placement:' field "
        "so the agent records where a new type was placed"
    )


def test_principle_clean_architecture_referenced():
    """agents/code-impl.md must reference swe-workbench:principle-clean-architecture."""
    body = _read()
    assert "swe-workbench:principle-clean-architecture" in body, (
        "agents/code-impl.md must reference 'swe-workbench:principle-clean-architecture' "
        "so implementers apply layer/boundary discipline when placing types"
    )


def test_process_covers_nested_and_inner_types():
    """Process must mention nested or inner type handling."""
    body = _read()
    section = _section(body, "Process")
    assert "nested" in section.lower() or "inner" in section.lower(), (
        "'## Process' must mention nested or inner types so the agent knows "
        "how to handle type definitions that belong inside an existing class/module"
    )
