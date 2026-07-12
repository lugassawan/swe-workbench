"""Structural tests: authoring flow wires comment-quality caps (closes #509).

Acceptance criteria: the primary enforcement path (authoring, not just review)
must reference `principle-clean-code`'s Comment discipline caps *as a stated
rule*, not merely as an incidental co-occurring string, so new comments comply
on the first pass rather than relying solely on the review backstop.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent

TECH_WRITER_AGENT = ROOT / "agents" / "tech-writer.md"
CODE_IMPL_AGENT = ROOT / "agents" / "code-impl.md"

CAPS_TOKENS = ("comment discipline", "comment cap", "comment quality")


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next real ## heading.

    Skips ## lines inside fenced code blocks.
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


def _rule_mentions_caps(section: str) -> bool:
    lowered = section.lower()
    return "principle-clean-code" in lowered and any(token in lowered for token in CAPS_TOKENS)


def test_tech_writer_agent_file_exists():
    assert TECH_WRITER_AGENT.exists(), "agents/tech-writer.md must exist"


def test_tech_writer_absolute_rules_reference_comment_caps():
    body = TECH_WRITER_AGENT.read_text()
    section = _section(body, "Absolute rules")
    assert section, "agents/tech-writer.md must have an '## Absolute rules' section"
    assert _rule_mentions_caps(section), (
        "agents/tech-writer.md '## Absolute rules' must reference principle-clean-code's "
        "comment caps as a stated rule, so inline comments it writes comply on the first pass"
    )


def test_code_impl_agent_file_exists():
    assert CODE_IMPL_AGENT.exists(), "agents/code-impl.md must exist"


def test_code_impl_absolute_rules_reference_comment_caps():
    body = CODE_IMPL_AGENT.read_text()
    section = _section(body, "Absolute rules")
    assert section, "agents/code-impl.md must have an '## Absolute rules' section"
    assert _rule_mentions_caps(section), (
        "agents/code-impl.md '## Absolute rules' must reference principle-clean-code's "
        "comment caps as a stated rule, so implementation comments comply on the first pass"
    )
