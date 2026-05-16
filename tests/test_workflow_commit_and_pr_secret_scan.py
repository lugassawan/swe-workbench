"""Regression tests for the pre-commit gate: suspicious staged files (issue #203).

The gate scans staged filenames for patterns that commonly indicate secrets
before the commit preview runs. It is the commit-layer complement to #181's
write-time hook: #181 catches secrets the agent introduces via Write/Edit;
this gate catches secrets staged by anyone before commit.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL_PATH = ROOT / "skills" / "workflow-commit-and-pr" / "SKILL.md"

SECTION_HEADING = "## Pre-commit gate: suspicious staged files"

# Positive matrix: filenames that MUST be flagged
POSITIVE_FILENAMES = [
    ".env",
    ".env.local",
    ".env.production",
    "prod.env",
    "path/to/.env",
    "private.pem",
    "tls.key",
    "credentials.json",
    "secrets.yaml",
    "secrets.json",
    "secret.yml",
    "Secrets.yaml",  # case-insensitive
    "config/credentials.json",  # path-prefixed variant (tests (^|/) anchor)
    "certs/private.pem",
    "path/to/secrets.yaml",
    "my.sample.pem",  # .sample in prefix must NOT suppress .pem detection
]

# Negative matrix: filenames that must NOT be flagged
NEGATIVE_FILENAMES = [
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    ".env.EXAMPLE",   # case-insensitive exclusion must fire
    ".env.Sample",    # mixed-case variant
    "secrets.example.yaml",
    "secrets.sample.json",
    "README.md",
    "src/main.py",
    "package.json",
    "Cargo.lock",
    "Makefile",
]


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


def test_secret_scan_section_present_with_askuserquestion():
    """The pre-commit gate section must exist in SKILL.md with the correct shape.

    Asserts:
    1. Section heading exists.
    2. Body contains the scan command (git diff --staged --name-only).
    3. Body contains a fenced JSON AskUserQuestion block with "Cancel" as the last option.
    4. Body encodes the "don't auto-unstage" invariant ("NOT touched" or "untouched").
    5. Body cross-references issue #181 (the write-time hook complement).
    """
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' in skills/workflow-commit-and-pr/SKILL.md"
    )

    section = _section_body(body, SECTION_HEADING)

    assert "git diff --staged --name-only" in section, (
        "Pre-commit gate section must contain 'git diff --staged --name-only'"
    )

    aq_block = _extract_fenced_block(section, "json")
    assert aq_block is not None, (
        "Pre-commit gate section must contain a fenced JSON block for AskUserQuestion"
    )
    assert '"Cancel"' in aq_block, (
        "AskUserQuestion JSON block must include a 'Cancel' option"
    )
    commit_pos = aq_block.find('"Commit anyway"')
    cancel_pos = aq_block.find('"Cancel"')
    assert commit_pos != -1 and cancel_pos != -1 and cancel_pos > commit_pos, (
        "'Cancel' must appear after 'Commit anyway' in the AskUserQuestion block"
    )

    assert re.search(r"NOT touched|untouched", section), (
        "Pre-commit gate section must state staging is 'NOT touched' (or 'untouched') "
        "on Cancel — encoding the no-auto-unstage invariant"
    )

    assert re.search(r"PreToolUse|Write/Edit hook|authoring time", section), (
        "Pre-commit gate section must describe its write-time hook complement without "
        "baking in a repo-specific issue number (e.g. '#181')"
    )


def test_secret_scan_regex_matches_expected_positives_and_negatives():
    """The regex embedded in the skill must flag expected positives and spare negatives.

    Extracts the grep -iE (positive) and grep -vE (exclusion) patterns from
    the fenced bash block in the pre-commit gate section, then applies them to
    a hand-picked filename matrix.
    """
    body = SKILL_PATH.read_text()
    section = _section_body(body, SECTION_HEADING)

    assert section, f"Section '{SECTION_HEADING}' not found in SKILL.md"

    bash_block = _extract_fenced_block(section, "bash")
    assert bash_block is not None, (
        "Pre-commit gate section must contain a fenced bash block with the scan command"
    )

    pos_match = re.search(r"grep\s+-iE\s+'([^']+)'", bash_block)
    assert pos_match, "Could not extract grep -iE pattern from bash block"
    pos_pattern = pos_match.group(1)

    excl_match = re.search(r"grep\s+-i?vE\s+'([^']+)'", bash_block)
    assert excl_match, "Could not extract grep -vE pattern from bash block"
    excl_pattern = excl_match.group(1)

    def should_flag(filename: str) -> bool:
        if not re.search(pos_pattern, filename, re.IGNORECASE):
            return False
        if re.search(excl_pattern, filename, re.IGNORECASE):
            return False
        return True

    for fname in POSITIVE_FILENAMES:
        assert should_flag(fname), (
            f"Expected '{fname}' to be flagged as suspicious, but it was not.\n"
            f"  pos_pattern:  {pos_pattern!r}\n"
            f"  excl_pattern: {excl_pattern!r}"
        )

    for fname in NEGATIVE_FILENAMES:
        assert not should_flag(fname), (
            f"Expected '{fname}' NOT to be flagged, but it was.\n"
            f"  pos_pattern:  {pos_pattern!r}\n"
            f"  excl_pattern: {excl_pattern!r}"
        )
