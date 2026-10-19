"""Tests for agents/product-manager.md (issue #428 state-file cleanup)."""

import re
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
    """agents/product-manager.md step 9 must invoke swe-workbench-clean-state-files on success."""
    text = AGENT_MD.read_text()
    assert "swe-workbench-clean-state-files" in text, (
        "agents/product-manager.md step 9 must call swe-workbench-clean-state-files "
        "to delete the temp .md and .cmd files after successful issue creation"
    )
    assert "/tmp/capture-" in text, (
        "agents/product-manager.md must reference the /tmp/capture-<repo-slug>-<ts>* "
        "file pattern in the swe-workbench-clean-state-files call"
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
    cleanup_pos = text.find("swe-workbench-clean-state-files")
    assert confirm_pos != -1, "agents/product-manager.md must mention 'confirm'"
    assert cleanup_pos != -1, "agents/product-manager.md must mention swe-workbench-clean-state-files"
    assert confirm_pos < cleanup_pos, (
        "The 'confirm' gate must appear before the swe-workbench-clean-state-files call — "
        "cleanup runs on the success path only, after gh issue create succeeds"
    )


# --- Public-repo redaction assertions ---

def _joined(text):
    """Fold shell line continuations so a multi-line command can be matched as one."""
    return re.sub(r"\\\n\s*", " ", text)


def test_product_manager_reads_visibility_and_gates_the_redactor():
    text = AGENT_MD.read_text()
    assert "gh repo view --json nameWithOwner,visibility" in text
    assert "PRIVATE" in text and "INTERNAL" in text
    assert "unknown" in text.lower(), "an unknown visibility must redact"


def test_product_manager_invokes_the_redactor_through_the_result_checker():
    text = _joined(AGENT_MD.read_text())
    assert "command -v swe-workbench-redact" in text
    assert "swe-workbench-redact --target-repo <nameWithOwner>" in text
    assert "| swe-workbench-result-check swb.redact/1" in text
    assert "--field title " in text and "--field body " in text


def test_product_manager_preview_has_a_redacted_line_before_the_confirm_prompt():
    text = AGENT_MD.read_text()
    preview = text[text.find("8. **Preview gate.**"):]
    redacted_pos = preview.find("Redacted:")
    reply_pos = preview.find("Reply 'confirm'")
    assert redacted_pos != -1 and reply_pos != -1 and redacted_pos < reply_pos
    assert "skipped — private repository" in preview
    assert "Redacted:" in text[text.find("## Output format"):], (
        "the Output format section must list the Redacted: line too"
    )


def test_product_manager_dup_scan_runs_after_redaction_on_the_sanitized_title():
    text = AGENT_MD.read_text()
    redaction_pos = text.find("**Sanitize")
    scan_pos = text.find("**Dup-scan.**")
    assert redaction_pos != -1 and scan_pos != -1 and redaction_pos < scan_pos
    scan = text[scan_pos:text.find("8. **Preview gate.**", scan_pos)]
    assert "sanitized title" in scan


def test_product_manager_edits_rerun_the_redactor_and_need_a_fresh_confirm():
    text = AGENT_MD.read_text()
    assert "fresh `confirm`" in text
    assert "re-runs the redactor" in text
    assert "credentials can never be restored" in text.lower()


def test_product_manager_cmd_sidecar_reads_the_title_from_its_file():
    text = AGENT_MD.read_text()
    assert '--title "$(cat ' in text
    assert '--title "..."' not in text and '--title "<title>"' not in text


def test_product_manager_cleanup_lists_the_draft_files():
    text = AGENT_MD.read_text()
    step9 = text[text.find("9. **File on confirm.**"):text.find("## Decision boundaries")]
    for suffix in (".draft.md", ".title.draft", ".title"):
        assert suffix in step9, f"step 9 must reap the {suffix} file"
