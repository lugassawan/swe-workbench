"""Tests for /swe-workbench:capture command (issue #428 state-file cleanup)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
CAPTURE_MD = ROOT / "commands" / "capture.md"


def test_capture_has_required_frontmatter():
    """commands/capture.md must have description: and argument-hint: frontmatter."""
    text = CAPTURE_MD.read_text()
    fm = validate.parse_frontmatter(CAPTURE_MD, text=text)
    assert fm is not None, "commands/capture.md must have valid frontmatter"
    assert "description" in fm, (
        "commands/capture.md must include a 'description:' frontmatter field"
    )
    assert "argument-hint" in fm, (
        "commands/capture.md must include an 'argument-hint:' frontmatter field"
    )


def test_capture_step9_deletes_temp_files():
    """commands/capture.md step 9 must invoke clean-state-files.sh on success."""
    text = CAPTURE_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "commands/capture.md step 9 must call runtime/clean-state-files.sh "
        "to delete the temp .md and .cmd files after successful issue creation"
    )
    assert "/tmp/capture-" in text, (
        "commands/capture.md must reference the /tmp/capture-<repo-slug>-<ts>* "
        "file pattern in the clean-state-files.sh call"
    )


def test_capture_step9_cleanup_on_success_only():
    """commands/capture.md must specify that temp files are left on failure (for retry)."""
    text = CAPTURE_MD.read_text()
    assert "failure" in text.lower() or "retry" in text.lower(), (
        "commands/capture.md must state that temp files are left intact on failure (for retry)"
    )


def test_capture_delegates_to_product_manager():
    """commands/capture.md must delegate to the product-manager subagent."""
    text = CAPTURE_MD.read_text()
    assert "product-manager" in text, (
        "commands/capture.md must reference the product-manager subagent"
    )
