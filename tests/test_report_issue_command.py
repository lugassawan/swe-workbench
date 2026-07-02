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


# --- Synthesis mode assertions (issue #475) ---

def _branch_b_slice(text):
    pos = text.find("### Branch B")
    assert pos != -1, "commands/report-issue.md must contain a '### Branch B' heading"
    end = text.find("Delegate to the `product-manager` subagent", pos)
    assert end != -1, (
        "commands/report-issue.md must contain the delegation block after Branch B"
    )
    return text[pos:end]


def test_report_issue_step0_offers_mode_selector():
    """Step 0 must offer a quick-pick vs synthesize mode selector before Branch B."""
    text = REPORT_ISSUE_MD.read_text()
    lower = text.lower()
    assert "quick pick" in lower, (
        "commands/report-issue.md Step 0 must offer a 'quick pick' mode"
    )
    assert "synthesize" in lower, (
        "commands/report-issue.md Step 0 must offer a 'synthesize' mode"
    )
    selector_pos = lower.find("quick pick")
    branch_b_pos = text.find("### Branch B")
    assert branch_b_pos != -1, "commands/report-issue.md must contain a '### Branch B' heading"
    assert selector_pos < branch_b_pos, (
        "The mode selector must precede the '### Branch B' section"
    )


def test_report_issue_synthesize_branch_exists():
    """commands/report-issue.md must contain a '### Branch B — Synthesize' section."""
    text = REPORT_ISSUE_MD.read_text()
    assert "### Branch B — Synthesize" in text, (
        "commands/report-issue.md must contain a '### Branch B — Synthesize' heading"
    )


def test_report_issue_synthesize_aggregates_all_memory():
    """Branch B must aggregate MEMORY.md plus feedback_*/project_* entries."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert "MEMORY.md" in branch_b, (
        "Branch B must reference MEMORY.md as the aggregation source"
    )
    assert "feedback_" in branch_b, (
        "Branch B must reference feedback_*.md memory entries"
    )
    assert "project_" in branch_b, (
        "Branch B must reference project_*.md memory entries"
    )


def test_report_issue_synthesize_clusters_emergent_themes():
    """Branch B must cluster entries into emergent themes, not a fixed taxonomy."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    lower = branch_b.lower()
    assert "cluster" in lower, "Branch B must describe clustering entries"
    assert "theme" in lower, "Branch B must describe theme labels"
    assert "NOT a fixed taxonomy" in branch_b, (
        "Branch B must explicitly rule out a fixed taxonomy for clustering"
    )


def test_report_issue_synthesize_ranks_by_prevalence():
    """Branch B must rank clusters by prevalence with a recency boost, keeping top 5-7."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    lower = branch_b.lower()
    assert "prevalence" in lower, "Branch B must rank insights by prevalence"
    assert "recency" in lower, "Branch B must apply a recency signal"
    assert "5–7" in branch_b or "5-7" in branch_b, (
        "Branch B must document keeping the top 5-7 insights"
    )
    assert "do not pad to reach the 5–7 range" in branch_b, (
        "Branch B step 4 must not pad the digest when fewer than 5 emergent clusters exist"
    )


def test_report_issue_synthesize_pick_then_confirm_order():
    """Branch B must present a ranked digest (pick) before a final preview (confirm)."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    numbers_pos = branch_b.find("numbers to file")
    assert numbers_pos != -1, (
        "Branch B must prompt the user to reply with numbers to file"
    )
    preview_pos = branch_b.find("final preview")
    if preview_pos == -1:
        preview_pos = branch_b.find("Filing into")
    assert preview_pos != -1, (
        "Branch B must present a final preview (or re-run 'Filing into') for the picks"
    )
    confirm_pos = branch_b.find("Reply 'confirm'")
    assert confirm_pos != -1, (
        "Branch B must gate filing behind a literal 'confirm' reply"
    )
    assert numbers_pos < preview_pos < confirm_pos, (
        "Order must be: numbers-to-file digest -> final preview -> Reply 'confirm'"
    )
    assert "Print each selected body with its `Title:` / `Filing into:`" in branch_b, (
        "Branch B step 7 must enumerate Title: and Filing into: as preview lines, "
        "not just reference delegation step 1 by name"
    )


def test_report_issue_synthesize_no_insights_remain_exit():
    """Branch B must exit cleanly (not silently no-op) when no picks remain to file."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert branch_b.count("No insights remain to file") == 2, (
        "Branch B must handle both an empty picked set (after the step-6 re-prompt) "
        "and a drop N that empties the pick set, each with a 'No insights remain to file' exit"
    )
    assert "after the one re-prompt from step 6" in branch_b, (
        "The empty-picked-set exit at the start of step 7 must fire only after step 6's "
        "own re-prompt has already failed once, not on the raw Turn 1 reply"
    )


def test_report_issue_synthesize_no_premature_filing():
    """Branch B must explicitly forbid filing on both Turn 1 and Turn 2."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert "run no `gh` command this turn" in branch_b, (
        "Branch B Turn 1 must explicitly forbid running gh this turn"
    )
    assert "Do NOT run `gh issue create` on this turn" in branch_b, (
        "Branch B Turn 2 must explicitly forbid filing before the literal 'confirm' reply"
    )
    turn1_guard_pos = branch_b.find("run no `gh` command this turn")
    turn2_guard_pos = branch_b.find("Do NOT run `gh issue create` on this turn")
    confirm_pos = branch_b.find("Reply 'confirm'")
    assert turn1_guard_pos < turn2_guard_pos, (
        "The Turn 1 no-filing guard must precede the Turn 2 no-filing guard"
    )
    assert confirm_pos < turn2_guard_pos, (
        "The Turn 2 no-filing guard must sit alongside/after the confirm prompt, not before it"
    )


def test_report_issue_synthesize_numbered_tempfiles():
    """Branch B must write numbered per-insight temp files plus a single .cmd sidecar."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert "-<n>.md" in branch_b, (
        "Branch B must write numbered temp files like -<n>.md, one per picked insight"
    )
    assert ".cmd" in branch_b, (
        "Branch B must write a .cmd sidecar for the picked insights"
    )


def test_report_issue_synthesize_seeds_enhancement_label():
    """Branch B must seed the 'enhancement' label for synthesized issues."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert "enhancement" in branch_b, (
        "Branch B must reference the 'enhancement' label"
    )
    label_pos = branch_b.find("enhancement")
    nearby = branch_b[max(0, label_pos - 80):label_pos + 80].lower()
    assert "label" in nearby, (
        "The 'enhancement' reference in Branch B must be near label-selection wording"
    )


def test_report_issue_synthesize_one_issue_per_insight():
    """Branch B must file exactly one enhancement issue per selected insight."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert "one enhancement issue per" in branch_b, (
        "Branch B must state that filing produces one enhancement issue per selected insight"
    )


def test_report_issue_synthesize_edge_too_few_entries():
    """Branch B must document the too-few-entries-to-cluster fallback."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    lower = branch_b.lower()
    assert "fewer than" in lower or "too few" in lower, (
        "Branch B must document a fallback for when there are too few memory entries to cluster"
    )
