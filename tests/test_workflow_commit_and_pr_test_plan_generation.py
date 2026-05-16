"""Structural tests for the test-plan generation section (issue #201).

Asserts that skills/workflow-commit-and-pr/SKILL.md documents:
  1. A '## Test plan generation' section.
  2. A type→focus table covering every commit type from the enforcing regex.
  3. The precedence ladder (breaking → feat → fix → perf).
  4. The append-under-subheading seeding invariant (mutates body BEFORE gh pr create).
  5. The heredoc-fallback path (replace <verification steps> placeholder).
  6. A cross-reference to swe-workbench:principle-testing.

Pattern mirrors tests/test_workflow_commit_and_pr_secret_scan.py.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL_PATH = ROOT / "skills" / "workflow-commit-and-pr" / "SKILL.md"

SECTION_HEADING = "## Test plan generation"


def _section_body(text: str, heading: str) -> str:
    """Return text from heading to the next ## heading (exclusive)."""
    start = text.find(heading)
    if start == -1:
        return ""
    end = text.find("\n## ", start + len(heading))
    return text[start:end] if end != -1 else text[start:]


def _extract_fenced_block(text: str, fence_info: str) -> str | None:
    """Return the content of the first ```{fence_info} ... ``` block in text."""
    pattern = re.compile(
        r"```" + re.escape(fence_info) + r"[ \t]*\n(.*?)```",
        re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else None


def _parse_commit_types_from_skill(text: str) -> list[str]:
    """Extract the commit types listed inside the fenced regex block in SKILL.md.

    Looks for the bare fenced block that contains the enforcing regex, e.g.:
        ```
        ^\\[(feat|fix|refactor|...)\\] .+
        ```
    Returns the alternation as a list of strings.
    """
    # Find fenced block (no language tag) containing the enforcing regex
    bare_fence = re.compile(r"```\s*\n(.*?)```", re.DOTALL)
    for m in bare_fence.finditer(text):
        content = m.group(1).strip()
        # Must look like the commit-msg enforcing regex
        alt_match = re.search(r"\\\[\\?\(?([a-z|]+)\)?\\?\\\]", content)
        if alt_match:
            return alt_match.group(1).split("|")
    return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_test_plan_generation_section_present():
    """'## Test plan generation' heading must exist in SKILL.md."""
    body = SKILL_PATH.read_text()
    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' in skills/workflow-commit-and-pr/SKILL.md"
    )


def test_table_covers_all_commit_types():
    """The type→focus entries must mention every commit type from the enforcing regex."""
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' — cannot check table coverage"
    )

    # Parse the 10 commit types from the same regex block the skill enforces
    commit_types = _parse_commit_types_from_skill(body)
    assert commit_types, (
        "Could not parse commit types from the enforcing regex fenced block in SKILL.md"
    )

    section = _section_body(body, SECTION_HEADING)

    missing = []
    for t in commit_types:
        if f"`{t}`" not in section:
            missing.append(t)

    assert not missing, (
        f"Type→focus table in '{SECTION_HEADING}' is missing rows for: {missing}. "
        f"Expected all 10 types from the enforcing regex to appear as `type` in the table."
    )


def test_precedence_ladder_documented():
    """The precedence ladder must document breaking → feat → fix → perf in that order."""
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' — cannot check precedence ladder"
    )

    section = _section_body(body, SECTION_HEADING)

    # All four anchor types must appear as whole words
    for t in ("breaking", "feat", "fix", "perf"):
        assert re.search(rf"\b{re.escape(t)}\b", section), (
            f"Precedence ladder in '{SECTION_HEADING}' must mention '{t}' as a whole word"
        )

    # Order constraint: breaking < feat < fix < perf (first whole-word occurrence)
    positions = {
        t: re.search(rf"\b{re.escape(t)}\b", section).start()
        for t in ("breaking", "feat", "fix", "perf")
    }
    ordered = sorted(positions, key=lambda t: positions[t])
    expected_order = ["breaking", "feat", "fix", "perf"]
    assert ordered[:4] == expected_order, (
        f"Precedence ladder must appear in order breaking→feat→fix→perf, "
        f"but found order: {ordered[:4]}"
    )


def test_seeding_strategy_is_append_under_subheading():
    """Seeding must append under '### Type-tailored checks' BEFORE gh pr create runs.

    Asserts:
    1. Sub-heading '### Type-tailored checks' is mentioned.
    2. Section encodes the mutability invariant: body is mutated before gh pr create /
       --body-file / $TMP.
    3. Section says 'do not' or 'never' near 'strip' or 'replace' for host bullets.
    """
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' — cannot check seeding strategy"
    )

    section = _section_body(body, SECTION_HEADING)

    # 1. Sub-heading present
    assert "### Type-tailored checks" in section, (
        "Seeding section must mention '### Type-tailored checks' sub-heading "
        "(used to append type bullets without overwriting host bullets)"
    )

    # 2. Mutability invariant: seed happens BEFORE gh pr create / --body-file / $TMP
    has_before = re.search(r"\bBEFORE\b|\bbefore\b", section)
    has_gh_ref = re.search(r"gh pr create|--body-file|\$TMP", section)
    assert has_before and has_gh_ref, (
        "Seeding section must state that the body is mutated BEFORE 'gh pr create' "
        "/ '--body-file' / '$TMP' — encoding the immutability-after-create invariant"
    )

    # 3. Host-bullet preservation
    assert re.search(r"(?:do not|never|Do not|Never)\b.{0,80}(?:strip|replace)", section), (
        "Seeding section must explicitly say 'do not' or 'never' strip/replace host bullets "
        "(append-only invariant)"
    )


def test_heredoc_fallback_path_documented():
    """The heredoc-fallback path (replace <verification steps> placeholder) must be documented."""
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' — cannot check heredoc fallback"
    )

    section = _section_body(body, SECTION_HEADING)

    assert re.search(r"heredoc|<verification steps>", section, re.IGNORECASE), (
        "Seeding section must document the heredoc-fallback path, including how the "
        "'<verification steps>' placeholder is handled when no PR template is detected"
    )


def test_principle_testing_cross_reference():
    """The section must cross-reference swe-workbench:principle-testing."""
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' — cannot check cross-reference"
    )

    section = _section_body(body, SECTION_HEADING)

    assert "swe-workbench:principle-testing" in section, (
        "Test-plan generation section must link to 'swe-workbench:principle-testing' "
        "for deeper test-design guidance"
    )
