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
# Four-Axis Review Lens
# ---------------------------------------------------------------------------


def test_correctness_bullet_mentions_paired_guard_predicate_gaps():
    """The Correctness axis bullet must name paired-guard predicate gaps."""
    body = _read()
    section = _section(body, "Four-Axis Review Lens")
    bullets = _axis_bullet_lines(section)
    correctness_line = next(
        (line for line in bullets if line.strip().startswith("- **Correctness**")),
        "",
    )
    assert correctness_line, "Four-Axis Review Lens must have a '- **Correctness**' bullet"
    lowered = correctness_line.lower()
    assert "predicate" in lowered, (
        "the Correctness bullet must mention predicate gaps between paired guard methods"
    )
    assert "sibling" in lowered or "paired" in lowered, (
        "the Correctness bullet must reference sibling/paired guard methods"
    )


def test_four_axis_framing_still_has_exactly_four_axes():
    """The 'four axes' framing must remain accurate after the Correctness edit."""
    body = _read()
    section = _section(body, "Four-Axis Review Lens")
    bullets = _axis_bullet_lines(section)
    assert len(bullets) == 4, (
        "'## Four-Axis Review Lens' must have exactly four '- **Axis**' bullets, "
        f"found {len(bullets)}"
    )
    assert "every review covers four axes" in section.lower(), (
        "the four-axes framing sentence must remain in place"
    )
