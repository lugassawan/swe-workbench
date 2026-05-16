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
    assert count >= 4, (
        f"commands/report-issue.md must include '{repo_flag}' at least 4 times "
        f"(issue create, issue list, label list, repo view) — found {count}"
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
