"""Regression guard: no bare `/command` mentions outside `/swe-workbench:` (closes #482).

A bare `/command` mention can be misrouted to a same-named command from another
installed plugin. Every mention of a swe-workbench command in docs/skills/agents/
commands must be prefixed `/swe-workbench:<command>` to resolve unambiguously.

Scope: skills/, docs/, agents/, commands/, README.md. tests/ and scripts/ are
excluded — their bare mentions are filenames or routing-assertion strings, not
user-facing CTAs.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

COMMANDS = [
    "address-feedback",
    "architect",
    "audit-codebase",
    "capture",
    "cleanup-merged",
    "codebase-knowledge",
    "debug",
    "design",
    "doctor",
    "document",
    "extend",
    "implement",
    "migrate",
    "refactor",
    "report-issue",
    "review",
    "security-review",
    "test",
]

# Longest-first alternation is defensive only: every token is slash-anchored
# via the leading "/" so match order does not affect correctness.
_ALTERNATION = "|".join(sorted(COMMANDS, key=len, reverse=True))

BARE_MENTION_RE = re.compile(
    rf"(?<![A-Za-z0-9:_/-])/(?:{_ALTERNATION})(?![A-Za-z0-9_-])(?!\.\w)"
)

SCAN_DIRS = ["skills", "docs", "agents", "commands"]


def _md_files():
    for d in SCAN_DIRS:
        yield from (ROOT / d).rglob("*.md")
    readme = ROOT / "README.md"
    if readme.is_file():
        yield readme


def test_no_bare_command_mentions():
    offenders = []
    for path in _md_files():
        rel = path.relative_to(ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            for match in BARE_MENTION_RE.finditer(line):
                offenders.append(f"{rel}:{lineno}: {match.group(0)!r} in: {line.strip()}")

    assert offenders == [], (
        "Found bare /command mentions that must be prefixed /swe-workbench:<command>:\n"
        + "\n".join(offenders)
    )
