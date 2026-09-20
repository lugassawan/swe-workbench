"""Regression tests for the pre-commit gate: suspicious staged files (issue #203).

The gate scans staged filenames for patterns that commonly indicate secrets
before the commit preview runs. It is the commit-layer complement to #181's
write-time hook: #181 catches secrets the agent introduces via Write/Edit;
this gate catches secrets staged by anyone before commit.
"""
import importlib.util
import re
from importlib.machinery import SourceFileLoader
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
    2. Body delegates the scan to swe-workbench-preflight-commit behind a command -v guard.
    3. Body contains a fenced JSON AskUserQuestion block with "Cancel" as the last option.
    4. Body encodes the "don't auto-unstage" invariant ("NOT touched" or "untouched").
    5. Body cross-references issue #181 (the write-time hook complement).
    """
    body = SKILL_PATH.read_text()

    assert SECTION_HEADING in body, (
        f"Missing section '{SECTION_HEADING}' in skills/workflow-commit-and-pr/SKILL.md"
    )

    section = _section_body(body, SECTION_HEADING)

    assert "command -v swe-workbench-preflight-commit" in section, (
        "Pre-commit gate section must guard swe-workbench-preflight-commit with a "
        "command -v check before invoking it"
    )
    assert "command -v swe-workbench-result-check" in section, (
        "Pre-commit gate section must also guard swe-workbench-result-check — it's "
        "piped in to validate the envelope before $PREFLIGHT is trusted"
    )
    assert "swe-workbench-preflight-commit | swe-workbench-result-check swb.preflight-commit/1" in section, (
        "Pre-commit gate section must pipe swe-workbench-preflight-commit's output "
        "through swe-workbench-result-check swb.preflight-commit/1, matching the other "
        "two migrated envelope consumers (workflow-pr-review-post, workflow-cleanup-merged) "
        "rather than reading the raw producer output unvalidated"
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


def _load_preflight_commit_module():
    """Import bin/swe-workbench-preflight-commit as a module (issue #660), mirroring
    test_pr_review_submit_script.py's `_load_module()` precedent. This is a strict
    upgrade over the prior version of this test, which extracted the grep -iE / -vE
    patterns as strings out of the Markdown and re-ran them through Python `re` — not
    POSIX ERE, and not `grep | grep` pipeline semantics. This tests the real code."""
    script = ROOT / "bin" / "swe-workbench-preflight-commit"
    loader = SourceFileLoader("preflight_commit", str(script))
    spec = importlib.util.spec_from_file_location("preflight_commit", script, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_scan_regex_matches_expected_positives_and_negatives():
    """bin/swe-workbench-preflight-commit's is_suspicious() must flag expected
    positives and spare expected negatives — the same filename matrix the old
    Markdown-regex-extraction version of this test used, now run against the real
    ported function instead of a string that resembles code."""
    pc = _load_preflight_commit_module()

    for fname in POSITIVE_FILENAMES:
        assert pc.is_suspicious(fname), f"Expected '{fname}' to be flagged as suspicious, but it was not."

    for fname in NEGATIVE_FILENAMES:
        assert not pc.is_suspicious(fname), f"Expected '{fname}' NOT to be flagged, but it was."


def test_skill_does_not_reimplement_the_scan_inline():
    """The inlined grep|grep pipeline and MATCHED/TOTAL wc -l classification must not
    creep back into the skill now that both live in swe-workbench-preflight-commit —
    one snapshot of the staged set, not two independently-drifting shell pipelines."""
    body = SKILL_PATH.read_text()
    assert "grep -iE" not in body, "SKILL.md must not reimplement the secret scan's grep -iE pipeline inline"
    assert "wc -l" not in body, "SKILL.md must not reimplement the docs-only MATCHED/TOTAL count inline"
    assert "MATCHED" not in body, "SKILL.md must not reimplement the docs-only MATCHED/TOTAL count inline"

    no_ci_section = _section_body(body, "## Doc-only `[no ci]` rule")
    assert no_ci_section, "Missing '## Doc-only `[no ci]` rule' section in SKILL.md"
    assert ".data.docs_only" in no_ci_section, (
        "'## Doc-only [no ci] rule' must read `.data.docs_only` from the validated "
        "preflight envelope computed by the pre-commit gate above, not re-derive the "
        "classification"
    )
