"""Tests for /swe-workbench:report-issue command (Issue #226)."""

import re
from pathlib import Path

from helpers import gh_spans

ROOT = Path(__file__).parent.parent
REPORT_ISSUE_MD = ROOT / "commands" / "report-issue.md"
PREFLIGHT_SCRIPT = ROOT / "bin" / "swe-workbench-issue-preflight"


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


REPO = "lugassawan/swe-workbench"
FAILURE_KINDS = ("unsupported_flag", "unauthenticated", "repo_inaccessible", "gh_missing", "unknown")


def _spans(*prefixes, min_tokens=1):
    """gh spans from the prose whose leading tokens match one of `prefixes` (each a tuple
    like ("issue", "create")), skipping descriptive mentions shorter than `min_tokens`."""
    found = []
    for span in gh_spans(REPORT_ISSUE_MD.read_text()):
        tokens = span.split()
        if len(tokens) < min_tokens:
            continue
        if any(tuple(tokens[1:1 + len(p)]) == p for p in prefixes):
            found.append(span)
    return found


def _min_gh_version():
    """MIN_GH_VERSION as the script declares it — the one value every surface must match."""
    match = re.search(r'^MIN_GH_VERSION = "([^"]+)"', PREFLIGHT_SCRIPT.read_text(), re.MULTILINE)
    assert match, "bin/swe-workbench-issue-preflight must declare MIN_GH_VERSION"
    return match.group(1)


def _step1_row(kind):
    step1 = _delegation_step1_slice(REPORT_ISSUE_MD.read_text())
    return next(
        (line.strip() for line in step1.splitlines() if line.strip().startswith(f"| `{kind}` |")), ""
    )


def _delegation_step1_slice(text):
    start = text.find("1. **Auth + repo check.**")
    assert start != -1, "commands/report-issue.md must keep the delegation 'Auth + repo check' step"
    end = text.find("2. **Restatement.**", start)
    assert end != -1, "commands/report-issue.md must keep the delegation 'Restatement' step"
    return text[start:end]


def _delegation_step9_slice(text):
    start = text.find("9. **File on confirm.**")
    assert start != -1, "commands/report-issue.md must keep delegation step 9 'File on confirm'"
    return text[start:]


def test_report_issue_gh_issue_and_label_commands_name_the_repo_with_flag():
    """`gh issue` / `gh label` take --repo; every one with arguments must carry it."""
    spans = _spans(("issue", "create"), ("issue", "list"), ("label", "list"), min_tokens=4)
    assert len(spans) >= 5, (
        "expected the issue create (x5 shapes), issue list, and label list command lines to "
        f"be parsed from the prose — found {len(spans)}: {spans}"
    )
    for span in spans:
        assert f"--repo {REPO}" in span, (
            f"every gh issue/label command must pass '--repo {REPO}' explicitly: {span!r}"
        )


def test_report_issue_gh_api_commands_use_literal_repo_path_and_no_repo_flag():
    """`gh api` has no --repo flag; the literal repos/<owner>/<repo>/ path is what scopes it."""
    spans = _spans(("api",), min_tokens=3)
    assert len(spans) >= 3, (
        "expected the two template-discovery calls and the version fallback to be parsed "
        f"from the prose — found {len(spans)}: {spans}"
    )
    for span in spans:
        assert "--repo" not in span, f"gh api does not accept --repo: {span!r}"
        assert f"repos/{REPO}/" in span, (
            f"gh api must hit the literal repos/{REPO}/ path, never infer the repo: {span!r}"
        )


def test_report_issue_gh_repo_view_takes_the_repo_positionally():
    """`gh repo view` takes the repo as a positional argument; --repo is an unknown flag."""
    spans = _spans(("repo", "view"), min_tokens=4)
    assert spans, "the bail hint must show a `gh repo view <repo>` diagnose command"
    for span in spans:
        assert "--repo" not in span, f"gh repo view does not accept --repo: {span!r}"
        assert span.split()[3] == REPO, (
            f"gh repo view must name {REPO} as its positional argument: {span!r}"
        )


def test_report_issue_gh_commands_have_no_placeholder_repo_templating():
    """{owner}/{repo} placeholders resolve from cwd, which is exactly what this flow forbids."""
    for span in gh_spans(REPORT_ISSUE_MD.read_text()):
        assert "{owner}" not in span and "{repo}" not in span, (
            f"gh commands must name {REPO} literally, not via placeholders: {span!r}"
        )


def test_report_issue_override_names_the_target_per_command_shape():
    """The override must say how each command shape names the target — not just '--repo
    everywhere' — and that gh auth status takes no repo."""
    text = REPORT_ISSUE_MD.read_text()
    end = text.find("The user wants to file a plugin issue")
    assert end != -1
    override = text[:end]
    assert "`gh repo view`" in override and "positional" in override, (
        "the override must say gh repo view takes the repo positionally"
    )
    assert "`gh api`" in override and f"repos/{REPO}/" in override, (
        "the override must say gh api is scoped by the literal repos/<owner>/<repo>/ path"
    )
    assert "`gh auth status`" in override and "host-scoped" in override, (
        "the override must say gh auth status is host-scoped and takes no repo"
    )
    assert "every `gh` invocation" not in override, (
        "the blanket 'pass --repo on every gh invocation' wording is the bug — gone"
    )


def test_report_issue_step1_uses_the_issue_preflight_runtime():
    """Delegation step 1 must classify via the runtime, not hand-run gh auth status."""
    step1 = _delegation_step1_slice(REPORT_ISSUE_MD.read_text())
    assert "command -v swe-workbench-issue-preflight" in step1, (
        "step 1 must guard the runtime with a command -v preflight"
    )
    assert (
        f"swe-workbench-issue-preflight {REPO} | swe-workbench-result-check swb.issue-preflight/1"
        in step1
    ), "step 1 must pipe the preflight through swe-workbench-result-check swb.issue-preflight/1"
    assert "|| exit 1" in step1
    for span in gh_spans(step1):
        assert span.split()[1:3] not in (["auth", "status"],), (
            f"step 1 must not hand-run gh auth status: {span!r}"
        )


def test_report_issue_step1_failure_kind_table_names_every_kind():
    step1 = _delegation_step1_slice(REPORT_ISSUE_MD.read_text())
    for kind in FAILURE_KINDS:
        assert f"| `{kind}` |" in step1, (
            f"step 1 must map failure_kind `{kind}` to a user-facing message in its table"
        )


def test_report_issue_step1_distinguishes_unsupported_flag_from_repo_inaccessible():
    """An unknown-flag rejection must never be reported as 'repo access failed'."""
    step1 = _delegation_step1_slice(REPORT_ISSUE_MD.read_text())
    row = next(
        (line.strip() for line in step1.splitlines() if line.strip().startswith("| `unsupported_flag` |")), ""
    )
    assert row, "step 1 must have an unsupported_flag row"
    assert _min_gh_version() in row, "the unsupported_flag row must name MIN_GH_VERSION"
    assert "Repo access check failed" not in row, (
        "an unsupported flag is a tooling problem, not a repo-access failure"
    )


def test_report_issue_step1_gh_missing_row_names_the_declared_minimum():
    row = _step1_row("gh_missing")
    assert row, "step 1 must have a gh_missing row"
    assert _min_gh_version() in row, "the gh_missing row must name MIN_GH_VERSION"


def test_report_issue_step1_unauthenticated_row_shows_reason_and_token_hint():
    """The preflight reports `unauthenticated` for a token gh could not validate, so the row
    must show why, and `gh auth login` is no remedy for an env-supplied token."""
    row = _step1_row("unauthenticated")
    assert row, "step 1 must have an unauthenticated row"
    assert "<reason>" in row, "the unauthenticated row must surface the gh reason"
    assert "GH_TOKEN" in row, "the unauthenticated row must cover an env-supplied token"


def test_report_issue_step1_scope_is_a_warning_with_three_states():
    step1 = _delegation_step1_slice(REPORT_ISSUE_MD.read_text())
    assert '`scope_status == "insufficient"`' in step1
    assert '`scope_status == "unknown"`' in step1
    assert "gh auth refresh -s public_repo" in step1, (
        "the insufficient-scope warning must name the command that adds the scope"
    )
    assert "lack issue-write scope" in step1, "the unknown-scope warning text must be preserved"
    assert "continue" in step1.lower(), "a scope warning must warn and continue, not bail"


def test_report_issue_step1_carves_out_branch_b_unauthenticated():
    """Branch B must keep rendering its digest when gh is unauthenticated, and the carve-out
    must be stated where the bail is defined — not only in a Branch B edge case."""
    text = REPORT_ISSUE_MD.read_text()
    step1 = _delegation_step1_slice(text)
    assert "Branch B only" in step1 and "do not bail" in step1, (
        "step 1 must state the Branch B unauthenticated carve-out next to the bail table"
    )
    edge = next(
        (line for line in _branch_b_slice(text).splitlines() if "`gh` unauthenticated" in line), ""
    )
    assert edge, "Branch B must keep its unauthenticated edge case"
    assert "failure_kind == unauthenticated" in edge and "do not bail" in edge
    assert 'scope_status == "unknown"' not in edge, (
        "the edge case must not point at the ok-only scope-warning table, which never fires "
        "for a failed envelope"
    )


def test_report_issue_remediations_do_not_overpromise():
    """`gh auth refresh` cannot add a scope to an env-supplied token, and a 403 can be a
    rate limit rather than a scope problem."""
    text = REPORT_ISSUE_MD.read_text()
    step1 = _delegation_step1_slice(text)
    step9 = _delegation_step9_slice(text)
    assert "GH_TOKEN" in step1, "the refresh remedy must cover an env-supplied token"
    assert "GH_TOKEN" in step9
    assert "rate limit" in step9.lower(), "step 9 must not report a rate-limit 403 as a scope problem"


def test_report_issue_create_time_403_is_reported_as_scope_not_repo_inaccessible():
    """A fine-grained token passes the preflight, then 403s at gh issue create."""
    text = REPORT_ISSUE_MD.read_text()
    step9 = _delegation_step9_slice(text)
    branch_b_step8 = _branch_b_slice(text)
    for label, block in (("delegation step 9", step9), ("Branch B step 8", branch_b_step8)):
        assert "403" in block, f"{label} must handle a create-time HTTP 403"
        assert "Resource not accessible by personal access token" in block, (
            f"{label} must recognise the fine-grained-token 403 message"
        )
    assert "insufficient" in step9 and "issue-write" in step9, (
        "step 9 must report a create-time 403 as insufficient issue-write scope"
    )
    assert "retry" in step9.lower(), "step 9 must keep the temp files for retry on a 403"


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


# --- Runtime memory-read assertions ---

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


def test_report_issue_memory_body_path_via_entries_path():
    """Body paths come from each entry's absolute .path field — never a
    .data.stores[store].path + .file composition, which resolves cwd-slug-merged
    entries against the wrong store."""
    text = REPORT_ISSUE_MD.read_text()
    for label, block in (
        ("Branch A step 2", _branch_a_step2_slice(text)),
        ("Branch B step 1", _branch_b_step1_slice(text)),
    ):
        assert ".data.entries" in block, (
            f"{label} must read body paths via .data.entries[].path"
        )
        assert ".path" in block, (
            f"{label} must use the entry's absolute .path field"
        )
        assert ".data.stores" not in block, (
            f"{label} must not compose body paths from .data.stores — the store-path "
            "+ basename composition resolves cwd-slug-merged entries against the "
            "wrong store"
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
