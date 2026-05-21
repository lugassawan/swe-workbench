"""Content-assertion tests for skills/workflow-delegated-implementation/SKILL.md (closes #261).

Acceptance criteria:
- frontmatter name == dir name; description references code-impl and subagent-driven-development.
- Required headings present.
- Grouping section contains a table (>=2 rows) using the commit-taxonomy axes.
- Parallelism section contains the safety-guardrail table.
- Result contract section contains "do not re-read" and the four statuses; no diff-return field.
- Skill body references code-impl.
"""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-delegated-implementation" / "SKILL.md"


def _read() -> str:
    assert SKILL.exists(), f"SKILL.md not found at {SKILL}"
    return SKILL.read_text()


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next real ## heading.

    Skips ## lines inside fenced code blocks.
    """
    marker = f"## {heading}"
    assert marker in body, f"SKILL.md must contain '{marker}'"
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
# Frontmatter
# ---------------------------------------------------------------------------


def test_frontmatter_name_matches_dir():
    body = _read()
    fm = validate.parse_frontmatter(SKILL, text=body)
    assert fm is not None, "SKILL.md must have valid YAML frontmatter"
    assert fm.get("name") == "workflow-delegated-implementation", (
        "frontmatter 'name' must be 'workflow-delegated-implementation' "
        "(must match directory name)"
    )


def test_frontmatter_description_references_code_impl():
    body = _read()
    fm = validate.parse_frontmatter(SKILL, text=body)
    assert fm is not None, "SKILL.md must have valid YAML frontmatter"
    assert "code-impl" in fm.get("description", ""), (
        "frontmatter 'description' must reference 'code-impl' "
        "so users know which sub-agent this skill dispatches to"
    )


def test_frontmatter_description_references_subagent_driven_development():
    body = _read()
    fm = validate.parse_frontmatter(SKILL, text=body)
    assert fm is not None, "SKILL.md must have valid YAML frontmatter"
    assert "subagent-driven-development" in fm.get("description", ""), (
        "frontmatter 'description' must reference 'subagent-driven-development' "
        "for differentiation from that sibling skill"
    )


# ---------------------------------------------------------------------------
# Required headings
# ---------------------------------------------------------------------------


def test_required_headings_present():
    body = _read()
    for heading in (
        "## When to invoke",
        "## When NOT to invoke",
        "## Grouping changes",
        "## Dispatch contract",
        "## Result contract",
        "## Parallelism",
        "## Absolute rules",
    ):
        assert heading in body, f"SKILL.md must contain '{heading}'"


# ---------------------------------------------------------------------------
# Grouping changes — commit-taxonomy axes + table
# ---------------------------------------------------------------------------


def test_grouping_section_references_commit_axes():
    """Grouping changes section must reference the four commit-taxonomy axes from workflow-development."""
    body = _read()
    section = _section(body, "Grouping changes")
    for axis in ("Infrastructure", "Core logic", "Tests", "Wiring"):
        assert axis in section, (
            f"'## Grouping changes' must reference the '{axis}' commit-taxonomy axis "
            "(reuses workflow-development SKILL.md:152-157)"
        )


def test_grouping_section_has_table():
    body = _read()
    section = _section(body, "Grouping changes")
    table_rows = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    assert len(table_rows) >= 2, (
        "'## Grouping changes' must contain a markdown table "
        "with at least a header row and one data row"
    )


# ---------------------------------------------------------------------------
# Parallelism — safety-guardrail table
# ---------------------------------------------------------------------------


def test_parallelism_section_has_safety_guardrail_table():
    body = _read()
    section = _section(body, "Parallelism")
    table_rows = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    assert len(table_rows) >= 2, (
        "'## Parallelism' must contain a safety-guardrail table "
        "(at least header + one data row)"
    )


def test_parallelism_section_covers_disjoint_and_dependency():
    """Safety table must address file-path disjoint and cross-group dependency conditions."""
    body = _read()
    section = _section(body, "Parallelism")
    assert "disjoint" in section.lower() or "overlap" in section.lower(), (
        "'## Parallelism' safety table must address file-path disjointness condition"
    )
    assert "depend" in section.lower(), (
        "'## Parallelism' safety table must address cross-group dependency depth condition"
    )


# ---------------------------------------------------------------------------
# Result contract — proxy for AC #3/#4/#6
# ---------------------------------------------------------------------------


def test_result_contract_has_four_statuses():
    body = _read()
    section = _section(body, "Result contract")
    for status in ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"):
        assert status in section, (
            f"'## Result contract' must declare the '{status}' status"
        )


def test_result_contract_instructs_no_re_read():
    """Result contract must tell the orchestrator NOT to re-read changed files.

    This is the token-saving mechanism (AC #3/#4): consuming a summary rather than
    re-reading full diffs keeps the orchestrator context lean.
    """
    body = _read()
    section = _section(body, "Result contract")
    assert "re-read" in section.lower() or "do not read" in section.lower(), (
        "'## Result contract' must instruct the orchestrator not to re-read changed files "
        "(the token-saving mechanism: consume the summary, not the diff)"
    )


def test_result_contract_no_diff_field():
    """Result contract must not introduce a diff-bearing return field."""
    body = _read()
    section = _section(body, "Result contract")
    for forbidden in ("`diff`", "diff field", "full diff", "`patch`", "patch field"):
        assert forbidden not in section.lower(), (
            f"'## Result contract' must not declare a diff-return field (found '{forbidden}'). "
            "Agents return summaries only."
        )


# ---------------------------------------------------------------------------
# Body references code-impl
# ---------------------------------------------------------------------------


def test_body_references_code_impl():
    body = _read()
    assert "code-impl" in body, (
        "SKILL.md body must reference 'code-impl' "
        "(the sub-agent this skill dispatches to)"
    )


# ---------------------------------------------------------------------------
# triggers.txt
# ---------------------------------------------------------------------------


def test_triggers_txt_exists_and_has_minimum_lines():
    triggers = ROOT / "skills" / "workflow-delegated-implementation" / "triggers.txt"
    assert triggers.exists(), (
        "skills/workflow-delegated-implementation/triggers.txt must exist"
    )
    lines = [
        ln.strip() for ln in triggers.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2, (
        f"triggers.txt must have at least 2 non-comment lines, got {len(lines)}"
    )
