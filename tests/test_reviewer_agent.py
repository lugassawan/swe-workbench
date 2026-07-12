"""Structural tests for agents/reviewer.md (closes #472)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "reviewer.md"


def _read() -> str:
    assert AGENT.exists(), "agents/reviewer.md must exist"
    return AGENT.read_text()


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next real ## heading.

    Skips ## lines inside fenced code blocks.
    """
    marker = f"## {heading}"
    assert marker in body, f"reviewer.md must contain '{marker}'"
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
    assert AGENT.exists(), "agents/reviewer.md must exist"


def test_frontmatter_name_is_reviewer():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    assert fm is not None, "reviewer.md must have valid YAML frontmatter"
    assert fm.get("name") == "reviewer", "frontmatter 'name' must be 'reviewer'"


# ---------------------------------------------------------------------------
# Paired-guard symmetry heuristic
# ---------------------------------------------------------------------------


def test_process_section_mentions_paired_guard_symmetry():
    """The Process section must name the paired-guard symmetry heuristic."""
    body = _read()
    section = _section(body, "Process")
    assert "paired-guard symmetry" in section.lower(), (
        "'## Process' must contain a 'Paired-guard symmetry' step"
    )
    assert "sibling" in section.lower(), (
        "the paired-guard symmetry step must mention locating the sibling method"
    )
    assert "predicate" in section.lower(), (
        "the paired-guard symmetry step must mention comparing predicate sets"
    )


def test_paired_guard_step_mentions_grep_and_predicate_comparison():
    """The step must direct the reviewer to grep for the sibling and compare predicates."""
    body = _read()
    section = _section(body, "Process")
    idx = section.lower().find("paired-guard symmetry")
    assert idx != -1, "'Paired-guard symmetry' step not found in '## Process'"
    step_text = section[idx:].lower()
    assert "grep" in step_text, (
        "the paired-guard symmetry step must instruct grepping for the sibling method"
    )
    assert "predicate" in step_text, (
        "the paired-guard symmetry step must instruct comparing predicate sets"
    )


# ---------------------------------------------------------------------------
# Comment-quality backstop (#509)
# ---------------------------------------------------------------------------


def test_process_section_mentions_comment_quality_backstop():
    """The Process section must have a dedicated comment-quality-backstop step,
    scoped as Low/hygiene, in-diff '+' lines only, drop-or-simplify, never an
    auto-rewrite, never pre-existing comments."""
    body = _read()
    section = _section(body, "Process")
    idx = section.lower().find("comment-quality backstop")
    assert idx != -1, "'## Process' must contain a 'Comment-quality backstop' step"
    step_text = section[idx:].lower()
    assert "hygiene" in step_text, (
        "the comment-quality backstop step must be scoped as Low/hygiene severity"
    )
    assert "`+`" in section[idx:] or "in-diff" in step_text, (
        "the comment-quality backstop step must scope to in-diff '+' lines only"
    )
    assert "auto-rewrite" in step_text, (
        "the comment-quality backstop step must state it never auto-rewrites comments"
    )
    assert "pre-existing" in step_text, (
        "the comment-quality backstop step must state it never flags pre-existing comments"
    )
