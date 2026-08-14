"""Structural tests for the Jackson null-element collection foot-gun guidance (closes #599).

Acceptance criteria:
- AC1: skills/language-java/SKILL.md's '## Optional and null discipline' section names Jackson,
  shows a literal-null-element JSON payload (e.g. {"content":[null]}), and names a null filter.
- AC2: skills/language-java/SKILL.md's '## Streams and collections' section cross-references
  Optional and null discipline for externally-deserialized sources.
- AC3: skills/language-kotlin/SKILL.md's '## Null safety' section names Jackson and filterNotNull.
- AC4: skills/language-kotlin/SKILL.md's '## Avoid' section carries the anti-pattern line about
  trusting a declared non-null element type on a Jackson-deserialized collection.
- AC5: both skills name the `contentNulls` JsonSetter attribute (the correct fix for null
  *elements*, as opposed to `nulls`, which only handles an explicit null on the property itself)
  and neither contains the bare string "nulls = Nulls.SKIP" (a ratchet against the wrong attribute).
- AC6: both skill files stay within the 150-line cap enforced by scripts/validate.py.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent

JAVA_SKILL = ROOT / "skills" / "language-java" / "SKILL.md"
KOTLIN_SKILL = ROOT / "skills" / "language-kotlin" / "SKILL.md"


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next ## heading (skips fenced blocks).

    Returns "" when the heading is absent so callers can assert with their own message.
    """
    marker = f"## {heading}"
    if marker not in body:
        return ""
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


def test_java_skill_file_exists():
    assert JAVA_SKILL.exists(), "skills/language-java/SKILL.md must exist"


def test_kotlin_skill_file_exists():
    assert KOTLIN_SKILL.exists(), "skills/language-kotlin/SKILL.md must exist"


def test_java_optional_and_null_discipline_names_jackson_foot_gun():
    body = JAVA_SKILL.read_text()
    section = _section(body, "Optional and null discipline")
    assert section.strip(), (
        "skills/language-java/SKILL.md must contain a non-empty "
        "'## Optional and null discipline' section"
    )
    assert "Jackson" in section, (
        "'## Optional and null discipline' must name Jackson as the source of the foot-gun"
    )
    assert '"content":[null]' in section or '"content": [null]' in section, (
        "'## Optional and null discipline' must show a literal-null-element JSON payload "
        'such as {"content":[null]}'
    )
    assert "filter" in section.lower(), (
        "'## Optional and null discipline' must name a null filter as the consumer-side remedy"
    )


def test_java_streams_and_collections_cross_references_null_discipline():
    body = JAVA_SKILL.read_text()
    section = _section(body, "Streams and collections")
    assert section.strip(), (
        "skills/language-java/SKILL.md must contain a non-empty '## Streams and collections' section"
    )
    assert "Optional and null discipline" in section, (
        "'## Streams and collections' must cross-reference 'Optional and null discipline' "
        "so a reviewer reading a .map() pipeline lands on the Jackson null-element guidance"
    )


def test_kotlin_null_safety_names_jackson_and_filter_not_null():
    body = KOTLIN_SKILL.read_text()
    section = _section(body, "Null safety")
    assert section.strip(), (
        "skills/language-kotlin/SKILL.md must contain a non-empty '## Null safety' section"
    )
    assert "Jackson" in section, (
        "'## Null safety' must name Jackson as the source of the foot-gun"
    )
    assert "filterNotNull" in section, (
        "'## Null safety' must name filterNotNull() as the remedy — filter { it != null } "
        "leaves the type as List<Content?> and buys nothing"
    )


def test_kotlin_avoid_carries_jackson_anti_pattern():
    body = KOTLIN_SKILL.read_text()
    section = _section(body, "Avoid")
    assert section.strip(), "skills/language-kotlin/SKILL.md must contain a non-empty '## Avoid' section"
    assert "Jackson" in section, (
        "'## Avoid' must carry an anti-pattern line naming Jackson-deserialized collections"
    )
    assert "non-null" in section.lower() or "non null" in section.lower(), (
        "'## Avoid' must call out trusting a declared non-null element type"
    )


def test_java_and_kotlin_name_content_nulls_not_bare_nulls_skip():
    for skill in (JAVA_SKILL, KOTLIN_SKILL):
        body = skill.read_text()
        assert "contentNulls" in body, (
            f"{skill} must name the contentNulls JsonSetter attribute — nulls handles an "
            "explicit null on the property itself, contentNulls handles nulls inside the "
            "collection/map/array, which is the bug being documented"
        )
        assert "nulls = Nulls.SKIP" not in body, (
            f"{skill} must not contain the bare 'nulls = Nulls.SKIP' — that attribute handles "
            "an explicit null property value, not null collection elements, and would not fix "
            "the reported bug"
        )


def test_java_skill_stays_within_line_cap():
    body = JAVA_SKILL.read_text()
    line_count = len(body.splitlines())
    assert line_count <= 150, (
        f"skills/language-java/SKILL.md must stay within the 150-line cap "
        f"(scripts/validate.py); currently {line_count} lines"
    )


def test_kotlin_skill_stays_within_line_cap():
    body = KOTLIN_SKILL.read_text()
    line_count = len(body.splitlines())
    assert line_count <= 150, (
        f"skills/language-kotlin/SKILL.md must stay within the 150-line cap "
        f"(scripts/validate.py); currently {line_count} lines"
    )
