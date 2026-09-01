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
    """commands/report-issue.md must capture plugin version and harness version for the footer,
    for both the Claude Code and Pi harnesses."""
    text = REPORT_ISSUE_MD.read_text()
    assert "plugin.json" in text, (
        "commands/report-issue.md must read plugin.json to capture the plugin version"
    )
    assert "claude --version" in text, (
        "commands/report-issue.md must run 'claude --version' to capture the CLI version"
    )
    assert "pi --version" in text, (
        "commands/report-issue.md must run 'pi --version' to capture the Pi CLI version"
    )
    assert "PI_SESSION_ID" in text, (
        "commands/report-issue.md must detect the Pi harness via the PI_SESSION_ID env var"
    )


def test_report_issue_footer_names_both_harnesses():
    """Both footer occurrences (memory-synthesis branch and delegation step 7) must
    parameterise the harness name rather than hardcoding 'Claude Code'."""
    text = REPORT_ISSUE_MD.read_text()
    count = text.count("<harness> <cli-version>")
    assert count == 2, (
        "commands/report-issue.md must parameterise 'Claude Code <cli-version>' as "
        f"'<harness> <cli-version>' in both footer occurrences (Branch B synthesis + "
        f"delegation step 7) — found {count}"
    )
    assert "Claude Code <cli-version>" not in text, (
        "commands/report-issue.md must not hardcode 'Claude Code <cli-version>' in the "
        "footer any more — both occurrences must parameterise the harness name"
    )


def test_report_issue_supports_blank_argument():
    """commands/report-issue.md must handle empty $ARGUMENTS by scanning conversation then memory."""
    text = REPORT_ISSUE_MD.read_text()
    assert "ARGUMENTS" in text, (
        "commands/report-issue.md must reference $ARGUMENTS"
    )
    assert ("blank" in text.lower() or "empty" in text.lower()), (
        "commands/report-issue.md must describe the blank-argument behaviour"
    )
    assert "MEMORY.md" in text, (
        "commands/report-issue.md must mention MEMORY.md (the store's on-disk shape) "
        "when describing the memory fallback for blank-arg mode"
    )


# --- Runtime memory-read assertions (issue #697 Task 4) ---

def _branch_a_step2_slice(text):
    branch_pos = text.find("### Branch A")
    assert branch_pos != -1, "commands/report-issue.md must contain a '### Branch A' heading"
    step2_pos = text.find("2. If conversation", branch_pos)
    assert step2_pos != -1, "Branch A must keep a step-2 memory-scan instruction"
    step3_pos = text.find("3. Present candidates", step2_pos)
    assert step3_pos != -1, "Branch A must keep a step-3 candidates-presentation instruction"
    return text[step2_pos:step3_pos]


def _branch_b_step1_slice(text):
    branch_b = _branch_b_slice(text)
    step1_pos = branch_b.find("1. **Load all memory")
    assert step1_pos != -1, "Branch B must keep a step-1 load-all-memory instruction"
    step2_pos = branch_b.find("2. **Harvest conversation", step1_pos)
    assert step2_pos != -1, "Branch B must keep a step-2 harvest-conversation instruction"
    return branch_b[step1_pos:step2_pos]


def test_report_issue_branch_a_step2_reads_memory_via_runtime():
    """Branch A step 2 must scan memory through the runtime, not a computed path."""
    step2 = _branch_a_step2_slice(REPORT_ISSUE_MD.read_text())
    assert "swe-workbench-memory show" in step2, (
        "Branch A step 2 must call swe-workbench-memory show via the runtime"
    )
    assert "swe-workbench-result-check swb.memory/1" in step2, (
        "Branch A step 2 must pipe the runtime output through "
        "swe-workbench-result-check swb.memory/1"
    )


def test_report_issue_branch_b_step1_reads_memory_via_runtime():
    """Branch B step 1 must load all memory through the runtime, not a computed path."""
    step1 = _branch_b_step1_slice(REPORT_ISSUE_MD.read_text())
    assert "swe-workbench-memory show" in step1, (
        "Branch B step 1 must call swe-workbench-memory show via the runtime"
    )
    assert "swe-workbench-result-check swb.memory/1" in step1, (
        "Branch B step 1 must pipe the runtime output through "
        "swe-workbench-result-check swb.memory/1"
    )


def test_report_issue_no_slug_recipe_prose():
    """The prose slug recipe for computing the memory path must be gone."""
    text = REPORT_ISSUE_MD.read_text()
    assert "derived from the current working directory path by replacing" not in text, (
        "commands/report-issue.md must not restate the project-slug derivation recipe — "
        "memory paths come from the runtime envelope"
    )


def test_report_issue_memory_recency_contract_preserved():
    """Entry order (index order) is the only recency signal in both branches."""
    text = REPORT_ISSUE_MD.read_text()
    branch_a_step2 = _branch_a_step2_slice(text)
    assert "order is the recency signal" in branch_a_step2, (
        "Branch A step 2 must state that entry order is the recency signal"
    )
    branch_b_step1 = _branch_b_step1_slice(text)
    assert "only recency signal" in branch_b_step1, (
        "Branch B step 1 must state the entries' listed order is the only recency signal"
    )


def test_report_issue_memory_body_path_via_stores_composition():
    """Body paths must compose .data.stores[store].path + .file — entries carry a basename only."""
    text = REPORT_ISSUE_MD.read_text()
    for label, block in (
        ("Branch A step 2", _branch_a_step2_slice(text)),
        ("Branch B step 1", _branch_b_step1_slice(text)),
    ):
        assert ".data.stores" in block, (
            f"{label} must read body paths via .data.stores[store].path"
        )
        assert ".file" in block, (
            f"{label} must compose the body path with the entry's basename .file field"
        )


def test_report_issue_memory_runtime_preflight_once():
    """Exactly one command -v preflight guards the memory runtime (Branch A; B references it)."""
    text = REPORT_ISSUE_MD.read_text()
    assert text.count("command -v swe-workbench-memory") == 1, (
        "commands/report-issue.md must carry exactly one "
        "'command -v swe-workbench-memory' preflight, in Branch A step 2"
    )
    assert "command -v swe-workbench-memory" in _branch_a_step2_slice(text)


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
    assert "Pi" in allowlist_block, (
        "commands/report-issue.md must name 'Pi' as an allowlisted token, so a Pi bug "
        "report doesn't get its own harness name redacted"
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
    """commands/report-issue.md step 9 must invoke swe-workbench-clean-state-files on success."""
    text = REPORT_ISSUE_MD.read_text()
    assert "swe-workbench-clean-state-files" in text, (
        "commands/report-issue.md step 9 must call swe-workbench-clean-state-files "
        "to delete the temp .md and .cmd files after successful issue creation"
    )
    assert "/tmp/report-issue-lugassawan-swe-workbench-" in text, (
        "commands/report-issue.md must reference the /tmp/report-issue-lugassawan-swe-workbench-* "
        "file pattern in the swe-workbench-clean-state-files call"
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
    end = text.find("Delegate to the `swe-workbench:product-manager` subagent", pos)
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
    """Branch B must aggregate every memory entry (feedback_*/project_* files under a MEMORY.md index)."""
    branch_b = _branch_b_slice(REPORT_ISSUE_MD.read_text())
    assert "MEMORY.md" in branch_b, (
        "Branch B must reference MEMORY.md when describing the store's on-disk shape"
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
