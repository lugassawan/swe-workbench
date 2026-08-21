"""Structural tests: authoring flow wires comment-quality caps (closes #509).

Acceptance criteria: the primary enforcement path (authoring, not just review)
must reference `swe-workbench:principle-clean-code`'s Comment discipline caps *as a stated
rule*, not merely as an incidental co-occurring string, so new comments comply
on the first pass rather than relying solely on the review backstop.
"""

from pathlib import Path

import pytest

from helpers import sentinel_block

ROOT = Path(__file__).parent.parent
COMMENT_SCAN_SRC = ROOT / "shared" / "agents" / "comment-scan.md"

TECH_WRITER_AGENT = ROOT / "agents" / "tech-writer.md"
CODE_IMPL_AGENT = ROOT / "agents" / "code-impl.md"

CAPS_TOKENS = ("comment discipline", "comment cap", "comment quality")

# Agents wired to the comment-scan gate via the inlined comment-scan.md sentinel block.
SCAN_WIRED_AGENTS = {
    "code-impl": CODE_IMPL_AGENT,
    "debugger": ROOT / "agents" / "debugger.md",
    "refactorer": ROOT / "agents" / "refactorer.md",
    "test-writer": ROOT / "agents" / "test-writer.md",
}


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


def test_comment_scan_shared_include_exists():
    path = ROOT / "shared" / "agents" / "comment-scan.md"
    assert path.exists(), "shared/agents/comment-scan.md must exist"


@pytest.mark.parametrize("name", sorted(SCAN_WIRED_AGENTS))
def test_agent_references_comment_scan_include(name):
    path = SCAN_WIRED_AGENTS[name]
    assert path.exists(), f"agents/{name}.md must exist"
    body = path.read_text()
    block = sentinel_block(body, "comment-scan.md")
    assert block is not None, (
        f"agents/{name}.md is missing the "
        "'<!-- BEGIN shared/agents/comment-scan.md -->' sentinel block in its verify "
        "step so the comment-scan gate is invoked on the first pass"
    )
    source = COMMENT_SCAN_SRC.read_text(encoding="utf-8")
    assert block == source, (
        f"agents/{name}.md's comment-scan block has drifted from "
        "shared/agents/comment-scan.md — run python3 scripts/sync-shared-blocks.py --write"
    )
