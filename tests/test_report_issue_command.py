"""Tests for /swe-workbench:report-issue command (Issue #226)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
REPORT_ISSUE_MD = ROOT / "commands" / "report-issue.md"


def test_report_issue_has_required_frontmatter():
    """commands/report-issue.md must have description: and argument-hint: frontmatter."""
    text = REPORT_ISSUE_MD.read_text()
    assert "description:" in text, (
        "commands/report-issue.md must include a 'description:' frontmatter field"
    )
    assert "argument-hint:" in text, (
        "commands/report-issue.md must include an 'argument-hint:' frontmatter field"
    )


def test_report_issue_hardcodes_target_repo():
    """commands/report-issue.md must hardcode lugassawan/swe-workbench as the target repo."""
    text = REPORT_ISSUE_MD.read_text()
    assert "lugassawan/swe-workbench" in text, (
        "commands/report-issue.md must hardcode 'lugassawan/swe-workbench' as the filing target"
    )


def test_report_issue_passes_repo_flag_to_gh():
    """commands/report-issue.md must pass --repo lugassawan/swe-workbench to every gh invocation."""
    text = REPORT_ISSUE_MD.read_text()
    repo_flag = "--repo lugassawan/swe-workbench"
    count = text.count(repo_flag)
    assert count >= 6, (
        f"commands/report-issue.md must include '{repo_flag}' at least 6 times "
        f"(issue create, issue list, label list, repo view, template discovery, version fallback) — found {count}"
    )
    assert "gh issue create" in text, (
        "commands/report-issue.md must include a gh issue create call"
    )
    assert "gh issue list" in text, (
        "commands/report-issue.md must include a gh issue list call for duplicate scan"
    )
    assert "gh label list" in text, (
        "commands/report-issue.md must include a gh label list call for label discovery"
    )


def test_report_issue_documents_product_manager_override():
    """commands/report-issue.md must document the product-manager --repo rule override."""
    text = REPORT_ISSUE_MD.read_text()
    assert "product-manager" in text, (
        "commands/report-issue.md must reference the product-manager agent"
    )
    assert ("override" in text.lower() or "suspended" in text.lower()), (
        "commands/report-issue.md must document that the product-manager's no-repo rule is overridden/suspended"
    )


def test_report_issue_attaches_version_footer():
    """commands/report-issue.md must capture plugin version and Claude Code version for the footer."""
    text = REPORT_ISSUE_MD.read_text()
    assert "plugin.json" in text, (
        "commands/report-issue.md must read plugin.json to capture the plugin version"
    )
    assert "claude --version" in text, (
        "commands/report-issue.md must run 'claude --version' to capture the CLI version"
    )


def test_report_issue_supports_blank_argument():
    """commands/report-issue.md must handle empty $ARGUMENTS by scanning conversation then MEMORY.md."""
    text = REPORT_ISSUE_MD.read_text()
    assert "ARGUMENTS" in text, (
        "commands/report-issue.md must reference $ARGUMENTS"
    )
    assert ("blank" in text.lower() or "empty" in text.lower()), (
        "commands/report-issue.md must describe the blank-argument behaviour"
    )
    assert "MEMORY.md" in text, (
        "commands/report-issue.md must reference MEMORY.md as the memory fallback for blank-arg mode"
    )


def test_report_issue_has_redaction_pass():
    """commands/report-issue.md must include a redaction sub-step in the draft step."""
    text = REPORT_ISSUE_MD.read_text()
    assert "Redaction pass" in text, (
        "commands/report-issue.md must include a 'Redaction pass' instruction in step 7"
    )


def test_report_issue_redaction_has_allowlist():
    """commands/report-issue.md must define an allowlist for the redaction pass."""
    text = REPORT_ISSUE_MD.read_text()
    assert "Allowlist" in text, (
        "commands/report-issue.md must include an 'Allowlist' section in the redaction instructions"
    )
    assert "NEVER redact" in text, (
        "commands/report-issue.md must include a 'NEVER redact' directive in the allowlist"
    )
    never_redact_pos = text.find("NEVER redact")
    allowlist_end = text.find("Redact when NOT allowlisted", never_redact_pos)
    allowlist_block = text[never_redact_pos:allowlist_end]
    assert "swe-workbench" in allowlist_block, (
        "commands/report-issue.md must name 'swe-workbench' as an allowlisted token"
    )


def test_report_issue_redaction_has_placeholder_vocabulary():
    """commands/report-issue.md must define placeholder vocabulary for all required categories."""
    text = REPORT_ISSUE_MD.read_text()
    assert "[internal-email]" in text, (
        "commands/report-issue.md must specify '[internal-email]' as a redaction placeholder"
    )
    assert "[internal-host]" in text, (
        "commands/report-issue.md must specify '[internal-host]' as a redaction placeholder"
    )
    assert "[internal-ip]" in text, (
        "commands/report-issue.md must specify '[internal-ip]' as a redaction placeholder"
    )
    assert "an internal service" in text, (
        "commands/report-issue.md must specify 'an internal service' as a redaction placeholder"
    )
    assert "[redacted-token]" in text, (
        "commands/report-issue.md must specify '[redacted-token]' as a placeholder for API keys/tokens"
    )


def test_report_issue_preview_shows_redaction_status():
    """commands/report-issue.md must include a 'Redacted:' line in the step 8 preview block."""
    text = REPORT_ISSUE_MD.read_text()
    assert "Redacted:" in text, (
        "commands/report-issue.md must include a 'Redacted:' line in the preview gate block"
    )


def test_report_issue_redaction_before_preview():
    """commands/report-issue.md: redaction pass → Redacted: line → confirm gate, in that order."""
    text = REPORT_ISSUE_MD.read_text()
    redaction_pos = text.find("Redaction pass")
    assert redaction_pos != -1, (
        "commands/report-issue.md must include a 'Redaction pass' instruction"
    )
    redacted_line_pos = text.find("Redacted:", redaction_pos)
    assert redacted_line_pos != -1, (
        "commands/report-issue.md must include a 'Redacted:' preview line"
    )
    confirm_pos = text.find("Reply 'confirm'", redacted_line_pos)
    assert confirm_pos != -1, (
        "commands/report-issue.md must include a \"Reply 'confirm'\" instruction"
    )
    assert redaction_pos < redacted_line_pos < confirm_pos, (
        "Order must be: 'Redaction pass' → 'Redacted:' line → \"Reply 'confirm'\""
    )


# --- State-file cleanup assertions (issue #428) ---

def test_report_issue_step9_deletes_temp_files():
    """commands/report-issue.md step 9 must invoke clean-state-files.sh on success."""
    text = REPORT_ISSUE_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "commands/report-issue.md step 9 must call runtime/clean-state-files.sh "
        "to delete the temp .md and .cmd files after successful issue creation"
    )
    assert "/tmp/report-issue-lugassawan-swe-workbench-" in text, (
        "commands/report-issue.md must reference the /tmp/report-issue-lugassawan-swe-workbench-* "
        "file pattern in the clean-state-files.sh call"
    )


def test_report_issue_step9_cleanup_on_success_only():
    """commands/report-issue.md must specify that temp files are left on failure."""
    text = REPORT_ISSUE_MD.read_text()
    assert "failure" in text.lower() or "on failure" in text.lower() or "retry" in text.lower(), (
        "commands/report-issue.md must state that temp files are left intact on failure (for retry)"
    )
