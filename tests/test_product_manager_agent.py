"""Tests for agents/product-manager.md (issue #428 state-file cleanup)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
AGENT_MD = ROOT / "agents" / "product-manager.md"


def test_product_manager_has_required_frontmatter():
    """agents/product-manager.md must have description: frontmatter."""
    text = AGENT_MD.read_text()
    fm = validate.parse_frontmatter(AGENT_MD, text=text)
    assert fm is not None, "agents/product-manager.md must have valid frontmatter"
    assert "description" in fm, (
        "agents/product-manager.md must include a 'description:' frontmatter field"
    )


def test_product_manager_step9_deletes_temp_files():
    """agents/product-manager.md step 9 must invoke clean-state-files.sh on success."""
    text = AGENT_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "agents/product-manager.md step 9 must call runtime/clean-state-files.sh "
        "to delete the temp .md and .cmd files after successful issue creation"
    )
    assert "/tmp/capture-" in text, (
        "agents/product-manager.md must reference the /tmp/capture-<repo-slug>-<ts>* "
        "file pattern in the clean-state-files.sh call"
    )


def test_product_manager_step9_cleanup_on_success_only():
    """agents/product-manager.md must specify that temp files are left on failure (for retry)."""
    text = AGENT_MD.read_text()
    assert "failure" in text.lower() or "retry" in text.lower(), (
        "agents/product-manager.md must state that temp files are left intact on failure (for retry)"
    )


def test_product_manager_confirm_gate_before_cleanup():
    """Cleanup must occur AFTER confirm, not before (cleanup is on success path only)."""
    text = AGENT_MD.read_text()
    confirm_pos = text.find("confirm")
    cleanup_pos = text.find("clean-state-files.sh")
    assert confirm_pos != -1, "agents/product-manager.md must mention 'confirm'"
    assert cleanup_pos != -1, "agents/product-manager.md must mention clean-state-files.sh"
    assert confirm_pos < cleanup_pos, (
        "The 'confirm' gate must appear before the clean-state-files.sh call — "
        "cleanup runs on the success path only, after gh issue create succeeds"
    )
