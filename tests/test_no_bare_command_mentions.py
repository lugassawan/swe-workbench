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
    "converge",
    "debug",
    "design",
    "doctor",
    "document",
    "extend",
    "hotfix",
    "handoff",
    "implement",
    "migrate",
    "refactor",
    "report-issue",
    "review",
    "security-review",
    "sync",
    "test",
]

# Longest-first alternation is defensive only: every token is slash-anchored
# via the leading "/" so match order does not affect correctness.
_ALTERNATION = "|".join(sorted(COMMANDS, key=len, reverse=True))

BARE_MENTION_RE = re.compile(
    rf"(?<![A-Za-z0-9:_/-])/(?:{_ALTERNATION})(?![A-Za-z0-9_-])(?!\.\w)"
)

SCAN_DIRS = ["skills", "docs", "agents", "commands"]

# The one sanctioned exception: on the Pi Coding Agent, prompt templates are published under
# their flat basename — the handoff template IS `/handoff` there, and its receiver instruction
# must carry exactly that name. Bare `/handoff` is therefore allowed only in the files that
# document the Pi receiver surface; everywhere else the /swe-workbench: prefix rule applies
# unchanged (misrouting on Claude Code is the failure this test exists to prevent).
_PI_TEMPLATE_NAME_ALLOWED_IN = {
    Path("commands/handoff.md"),
    Path("docs/cross-harness-handoff.md"),
    Path("docs/plugin-platform-decisions.md"),
    Path("docs/superpowers/plans/2026-08-30-cross-harness-handoff.md"),
    Path("docs/superpowers/specs/2026-08-30-cross-harness-handoff-design.md"),
}


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
                if match.group(0) == "/handoff" and rel in _PI_TEMPLATE_NAME_ALLOWED_IN:
                    continue
                offenders.append(f"{rel}:{lineno}: {match.group(0)!r} in: {line.strip()}")

    assert offenders == [], (
        "Found bare /command mentions that must be prefixed /swe-workbench:<command>:\n"
        + "\n".join(offenders)
    )
