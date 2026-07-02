"""Structural tests for the Go code-generation / google/wire convention (closes #477).

Acceptance criteria:
- skills/language-go/SKILL.md has a '## Code generation' section, non-empty.
- The section mentions wire.go, wire_gen.go, and a DO NOT EDIT / generated signal.
- The section references regeneration via `go generate` (and/or `wire ./...`).
- The section states the source-of-truth rule: edit wire.go, not wire_gen.go.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

GO_SKILL = ROOT / "skills" / "language-go" / "SKILL.md"


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


def test_go_skill_file_exists():
    assert GO_SKILL.exists(), "skills/language-go/SKILL.md must exist"


def test_has_code_generation_section():
    body = GO_SKILL.read_text()
    section = _section(body, "Code generation")
    assert section.strip(), (
        "skills/language-go/SKILL.md must contain a non-empty '## Code generation' section"
    )


def test_code_generation_mentions_wire_files():
    body = GO_SKILL.read_text()
    section = _section(body, "Code generation")
    assert section.strip(), "'## Code generation' section is empty or missing"
    assert "wire.go" in section, (
        "'## Code generation' must reference 'wire.go' as the editable injector source"
    )
    assert "wire_gen.go" in section, (
        "'## Code generation' must reference 'wire_gen.go' as the generated output"
    )


def test_code_generation_mentions_generated_signal():
    body = GO_SKILL.read_text()
    section = _section(body, "Code generation")
    assert section.strip(), "'## Code generation' section is empty or missing"
    assert re.search(r"DO NOT EDIT", section, re.IGNORECASE), (
        "'## Code generation' must call out the literal 'DO NOT EDIT' generated-file signal"
    )


def test_code_generation_mentions_regeneration_command():
    body = GO_SKILL.read_text()
    section = _section(body, "Code generation")
    assert section.strip(), "'## Code generation' section is empty or missing"
    assert re.search(r"go generate|wire\s+\./\.\.\.", section), (
        "'## Code generation' must reference regenerating via `go generate` or `wire ./...`"
    )


def test_code_generation_states_source_of_truth_rule():
    body = GO_SKILL.read_text()
    section = _section(body, "Code generation")
    assert section.strip(), "'## Code generation' section is empty or missing"
    assert re.search(r"wire\.go.{0,80}never.{0,40}wire_gen\.go", section, re.IGNORECASE | re.DOTALL), (
        "'## Code generation' must state, in one place, the rule: edit wire.go, never wire_gen.go"
    )
