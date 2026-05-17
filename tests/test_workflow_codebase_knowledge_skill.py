"""Content-assertion tests for skills/workflow-codebase-knowledge/SKILL.md.

Acceptance criteria (issue #245):
- Required headings present.
- Description + When NOT to invoke section references both sibling surfaces:
  workflow-codebase-audit (defect-finding) and /swe-workbench:document / tech-writer
  (prose-doc generation).
- Diagram-guidelines section contains the signal-to-noise use/skip table.
- 5-section rendering template lists all required section names.
- Absolute rules section is present.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-codebase-knowledge" / "SKILL.md"


def _read() -> str:
    assert SKILL.exists(), f"SKILL.md not found at {SKILL}"
    return SKILL.read_text()


def _section(body: str, heading: str) -> str:
    """Extract the body of a top-level ## heading, stopping at the next real ## heading.

    Skips ## lines that appear inside fenced code blocks (``` or ~~~~), so
    example headers inside a rendering template do not truncate the section.
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
# Required headings
# ---------------------------------------------------------------------------


def test_required_headings_present():
    body = _read()
    for heading in (
        "## When to invoke",
        "## When NOT to invoke",
        "## Rendering template",
        "## Diagram guidelines",
        "## Absolute rules",
    ):
        assert heading in body, f"SKILL.md must contain '{heading}'"


# ---------------------------------------------------------------------------
# Differentiation contract — must mention both sibling surfaces
# ---------------------------------------------------------------------------


def test_description_references_workflow_codebase_audit():
    """description: frontmatter must reference workflow-codebase-audit to
    distinguish this skill (understanding) from defect detection.
    """
    body = _read()
    assert body.startswith("---"), "SKILL.md must have YAML frontmatter"
    fm_end = body.index("\n---\n", 3) + 1
    frontmatter = body[:fm_end]
    assert "workflow-codebase-audit" in frontmatter, (
        "SKILL.md description: must reference 'workflow-codebase-audit' "
        "to clarify this skill is distinct from defect detection"
    )


def test_when_not_to_invoke_references_audit():
    """`## When NOT to invoke` must tell users to use workflow-codebase-audit
    for defect/finding-oriented work.
    """
    body = _read()
    section = _section(body, "When NOT to invoke")
    assert "workflow-codebase-audit" in section, (
        "'## When NOT to invoke' must reference 'workflow-codebase-audit' "
        "so users know where to go for defect detection"
    )


def test_when_not_to_invoke_references_document_or_tech_writer():
    """`## When NOT to invoke` must tell users to use /swe-workbench:document
    or the tech-writer subagent for generating new prose docs.
    """
    body = _read()
    section = _section(body, "When NOT to invoke")
    references_doc = (
        "/swe-workbench:document" in section
        or "tech-writer" in section
    )
    assert references_doc, (
        "'## When NOT to invoke' must reference '/swe-workbench:document' or "
        "'tech-writer' to distinguish knowledge-presentation from prose-doc generation"
    )


def test_description_or_not_invoke_references_tech_writer_or_document():
    """Either the frontmatter description or the ## When NOT to invoke section
    must reference the /swe-workbench:document command or tech-writer subagent.
    """
    body = _read()
    fm_end = body.index("\n---\n", 3) + 1
    frontmatter = body[:fm_end]
    section = _section(body, "When NOT to invoke")
    combined = frontmatter + section
    assert (
        "tech-writer" in combined
        or "/swe-workbench:document" in combined
    ), (
        "SKILL.md must mention '/swe-workbench:document' or 'tech-writer' "
        "in the description or ## When NOT to invoke to complete the differentiation contract"
    )


# ---------------------------------------------------------------------------
# Diagram guidelines — signal-to-noise table
# ---------------------------------------------------------------------------


def test_diagram_guidelines_section_present():
    body = _read()
    assert "## Diagram guidelines" in body, (
        "SKILL.md must contain '## Diagram guidelines' section"
    )


def test_diagram_guidelines_contains_signal_to_noise_table():
    """The diagram-guidelines section must contain a use/skip table so future
    contributors can apply the signal-to-noise rule without ambiguity.
    """
    body = _read()
    section = _section(body, "Diagram guidelines")
    has_use = "Use" in section or "use" in section
    has_skip = "Skip" in section or "Omit" in section or "skip" in section or "omit" in section
    assert has_use and has_skip, (
        "'## Diagram guidelines' must contain a signal-to-noise table "
        "with 'Use' and 'Skip'/'Omit' columns"
    )
    table_rows = [line for line in section.splitlines() if line.strip().startswith("|")]
    assert len(table_rows) >= 2, (
        "'## Diagram guidelines' must have a markdown table with at least a header row "
        "and one data row (the signal-to-noise rule)"
    )


# ---------------------------------------------------------------------------
# Rendering template — 5-section layout
# ---------------------------------------------------------------------------


def test_rendering_template_has_all_five_sections():
    """The ## Rendering template must list all 5 knowledge-document sections
    from the issue #245 spec: Overview, Module map, Architecture diagram,
    Public API surfaces, Patterns & conventions.
    """
    body = _read()
    assert "## Rendering template" in body, (
        "SKILL.md must contain '## Rendering template' section"
    )
    template_block = _section(body, "Rendering template")

    for section_name in (
        "Overview",
        "Module map",
        "Architecture diagram",
        "Public API",
        "Patterns",
    ):
        assert section_name in template_block, (
            f"Rendering template must include '{section_name}' section "
            f"(required by issue #245 spec)"
        )
