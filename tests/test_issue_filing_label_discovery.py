"""Tests for issue-filing surfaces including --label (#247)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
CAPTURE_MD = ROOT / "commands" / "capture.md"
PRODUCT_MANAGER_MD = ROOT / "agents" / "product-manager.md"
BUG_TRIAGE_MD = ROOT / "skills" / "workflow-bug-triage" / "SKILL.md"


def test_capture_runs_gh_label_list():
    """commands/capture.md must run `gh label list` during template discovery."""
    text = CAPTURE_MD.read_text()
    assert "gh label list" in text, (
        "commands/capture.md must call `gh label list` to discover repo labels"
    )


def test_capture_preview_shows_label_flag():
    """commands/capture.md preview block and .cmd sidecar must include --label."""
    text = CAPTURE_MD.read_text()
    assert "--label" in text, (
        "commands/capture.md must include --label in the preview command and .cmd sidecar"
    )


def test_capture_documents_label_override():
    """commands/capture.md preview gate must mention that the user can change the label."""
    text = CAPTURE_MD.read_text().lower()
    assert "label" in text and ("override" in text or "change" in text or "edit" in text), (
        "commands/capture.md must tell the user how to override the chosen label"
    )


def test_product_manager_runs_gh_label_list():
    """agents/product-manager.md must call `gh label list` during template discovery."""
    text = PRODUCT_MANAGER_MD.read_text()
    assert "gh label list" in text, (
        "agents/product-manager.md must call `gh label list`"
    )


def test_product_manager_v1_ban_lifted():
    """agents/product-manager.md must no longer ban --label under v1."""
    text = PRODUCT_MANAGER_MD.read_text()
    assert "Never use `--label`" not in text, (
        "v1 ban on --label must be lifted; "
        "agents/product-manager.md still contains the backtick-quoted prohibition"
    )
    assert "Never use --label" not in text, (
        "v1 ban on --label must be lifted (unquoted form)"
    )


def test_product_manager_preview_shows_label_flag():
    """agents/product-manager.md preview/sidecar lines must include --label."""
    text = PRODUCT_MANAGER_MD.read_text()
    assert "--label" in text, (
        "agents/product-manager.md must include --label in preview and .cmd sidecar"
    )


def test_product_manager_still_bans_assignee_and_milestone():
    """v1 ban on --assignee and --milestone must remain (scope discipline)."""
    text = PRODUCT_MANAGER_MD.read_text()
    assert "--assignee" in text and "--milestone" in text, (
        "agents/product-manager.md must still document the v1 restrictions on "
        "--assignee and --milestone (only --label is being lifted)"
    )
