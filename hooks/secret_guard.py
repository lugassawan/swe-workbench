#!/usr/bin/env python3
"""PreToolUse hook: block Write/Edit when content contains a hardcoded secret.

Failure posture (deliberately opposite of bash_guard.sh):
  - FAIL OPEN  on parse / interpreter error → exit 0 (no stderr)
  - FAIL CLOSED only on a confirmed pattern match → exit 2 + "BLOCKED: …"

Rationale: a secret guard that failed closed on a malformed payload would
block every file edit — a self-inflicted DoS. This is a guardrail against
*accidental* leaks by a cooperative agent, not an adversarial control.

Input:  JSON on stdin from Claude Code hook runtime.
Block:  write "BLOCKED: …" to stderr, exit 2.
Allow:  exit 0, empty stderr.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ── Filename allowlist ────────────────────────────────────────────────────────
# Whole-file exemptions. Keep narrow and explicit; never use broad globs.
_ALLOWLIST_BASENAMES = frozenset({".gitignore"})
_ALLOWLIST_SUFFIXES = frozenset({
    str(Path(__file__).resolve().parent.parent / "tests" / "test_secret_guard.py"),
})

# ── Pattern definitions ───────────────────────────────────────────────────────
# Each entry: (name, compiled_regex, needs_context: bool)
# HIGH tier  (needs_context=False): block anywhere in a non-suppressed line.
# NEEDS-CONTEXT tier (needs_context=True): skip lines that contain an
#   environment-variable reference (os.environ, os.getenv, process.env, ENV[,
#   getenv). Checked in _scan rather than embedded in the regex so that the
#   reference guard operates on the *full* line without lookahead positioning
#   issues (a mid-pattern lookahead sees only the remaining suffix, not the
#   part already consumed by earlier alternates).
#
# `# nosecret` suppression: checked via plain string containment on each line
# before pattern matching. Intentional for the cooperative-agent threat model;
# documented in docs/secret-detection.md.

_REF_PATTERN = re.compile(
    r"os\.environ|os\.getenv|process\.env|ENV\[|\bgetenv\b"
)
_NOSECRET_PAT = re.compile(r"#\s*nosecret\b")

_PATTERNS: list[tuple[str, re.Pattern, bool]] = [
    # HIGH – prefixed tokens distinctive enough to block without context
    ("github-pat",
     re.compile(r"ghp_[A-Za-z0-9]{36}"),
     False),
    ("github-fine-grained-pat",
     re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
     False),
    ("aws-access-key-id",
     re.compile(r"AKIA[0-9A-Z]{16}"),
     False),

    # NEEDS-CONTEXT – require a key name + literal value structure
    ("aws-secret-access-key",
     re.compile(r"(?i)aws_secret\w*\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}[\"']?"),
     True),
    ("generic-api-key",
     re.compile(r"(?i)\bAPI_KEY\s*=\s*[\"'][^\"']{16,}[\"']"),
     True),
    ("generic-secret",
     re.compile(r"(?i)\b(?:SECRET|PASSWORD|PASSWD|TOKEN)\s*=\s*[\"'][^\"']{8,}[\"']"),
     True),
    ("dotenv-assignment",
     re.compile(r"^(?:SECRET|API_KEY|TOKEN|PASSWORD|PASSWD)=[^\s]{8,}"),  # ^ anchors on each split line, not full content
     True),
]


def _is_allowlisted(file_path: str) -> bool:
    p = Path(file_path)
    if p.name in _ALLOWLIST_BASENAMES:
        return True
    try:
        if str(p.resolve()) in _ALLOWLIST_SUFFIXES:
            return True
    except OSError:
        pass
    return False


def _scan(content: str) -> tuple[str, int] | None:
    """Return (pattern_name, 1-based line_number) for the first match, or None."""
    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        if _NOSECRET_PAT.search(line):
            continue
        is_ref = bool(_REF_PATTERN.search(line))
        for name, pattern, needs_context in _PATTERNS:
            if needs_context and is_ref:
                continue
            if pattern.search(line):
                return name, lineno
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input")

    if not isinstance(tool_input, dict):
        sys.exit(0)

    if tool_name == "Write":
        content = tool_input.get("content", "")
        file_path = tool_input.get("file_path", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")
        file_path = tool_input.get("file_path", "")
    else:
        sys.exit(0)

    if not isinstance(content, str) or not content:
        sys.exit(0)

    if _is_allowlisted(file_path):
        sys.exit(0)

    match = _scan(content)
    if match is None:
        sys.exit(0)

    pattern_name, lineno = match
    print(
        f"BLOCKED: hardcoded secret detected (pattern: {pattern_name}, "
        f"line {lineno}, file: {file_path or '<unknown>'})\n"
        f"Replace the literal with an environment-variable reference "
        f"(e.g. os.environ[...]), or add `# nosecret` on that line "
        f"if this is an intentional fixture/example.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
