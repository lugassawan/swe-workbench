"""Structural tests for skills/principle-code-review/SKILL.md (closes #472)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "principle-code-review" / "SKILL.md"


def _read() -> str:
    assert SKILL.exists(), "skills/principle-code-review/SKILL.md must exist"
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


def _axis_bullet_lines(section: str) -> list[str]:
    return [
        line
        for line in section.splitlines()
        if line.strip().startswith("- **")
    ]


# ---------------------------------------------------------------------------
# Five-Axis Review Lens
# ---------------------------------------------------------------------------


def test_correctness_bullet_mentions_paired_guard_predicate_gaps():
    """The Correctness axis bullet must name paired-guard predicate gaps."""
    body = _read()
    section = _section(body, "Five-Axis Review Lens")
    bullets = _axis_bullet_lines(section)
    correctness_line = next(
        (line for line in bullets if line.strip().startswith("- **Correctness**")),
        "",
    )
    assert correctness_line, "Five-Axis Review Lens must have a '- **Correctness**' bullet"
    lowered = correctness_line.lower()
    assert "predicate" in lowered, (
        "the Correctness bullet must mention predicate gaps between paired guard methods"
    )
    assert "sibling" in lowered or "paired" in lowered, (
        "the Correctness bullet must reference sibling/paired guard methods"
    )


def test_five_axis_framing_has_exactly_five_axes():
    """The 'five axes' framing must remain accurate after the Comment quality addition."""
    body = _read()
    section = _section(body, "Five-Axis Review Lens")
    bullets = _axis_bullet_lines(section)
    assert len(bullets) == 5, (
        "'## Five-Axis Review Lens' must have exactly five '- **Axis**' bullets, "
        f"found {len(bullets)}"
    )
    assert "every review covers five axes" in section.lower(), (
        "the five-axes framing sentence must be in place"
    )


def test_comment_quality_axis_present():
    """The Comment quality axis must define scope (hygiene, in-diff only, no auto-rewrite)."""
    body = _read()
    section = _section(body, "Five-Axis Review Lens")
    bullets = _axis_bullet_lines(section)
    comment_line = next(
        (line for line in bullets if line.strip().startswith("- **Comment quality**")),
        "",
    )
    assert comment_line, "Five-Axis Review Lens must have a '- **Comment quality**' bullet"
    lowered = comment_line.lower()
    assert "hygiene" in lowered, "the Comment quality bullet must be scoped as hygiene-tier"
    assert "in-diff" in lowered or "`+`" in comment_line, (
        "the Comment quality bullet must scope to in-diff (+) lines only"
    )
    assert "auto-rewrite" in lowered, (
        "the Comment quality bullet must state it never auto-rewrites"
    )
    assert "principle-clean-code" in lowered, (
        "the Comment quality bullet must point to principle-clean-code for the caps"
    )
