# tests/test_workflow_pr_review_thread_verification.py

"""
Tests for the thread-verification + approval-override prose contract.

Contract layers:
  Unit 1 — workflow-pr-review/SKILL.md (new Step 5.5: verify own open review
           threads before an APPROVE submit, resolve the addressed ones, and
           surface an AskUserQuestion override for anything left open)
  Unit 2 — workflow-pr-review-post/SKILL.md (APPROVE_OVER_OPEN_THREADS input
           contract, Post block flag, gate-semantics + failure-mode prose)
  Unit 3 — commands/review.md (--approve-over-open-threads argument parsing
           and pass-through to both workflow-pr-review delegations)
  Unit 4 — no issue-number self-citation in any of the three files
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PR_REVIEW_SKILL = ROOT / "skills" / "workflow-pr-review" / "SKILL.md"
POST_CORE_SKILL = ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md"
REVIEW_CMD = ROOT / "commands" / "review.md"


# ---------------------------------------------------------------------------
# Unit 1 — workflow-pr-review/SKILL.md Step 5.5
# ---------------------------------------------------------------------------


def test_step_5_5_heading_exists():
    """A 'Step 5.5' heading must exist between Step 5 and Step 6."""
    text = PR_REVIEW_SKILL.read_text()
    assert re.search(r"^###\s+Step 5\.5\b", text, re.MULTILINE), (
        "skills/workflow-pr-review/SKILL.md must contain a '### Step 5.5' heading "
        "for the own-thread verification step"
    )


def test_step_5_5_gated_on_decision_approve():
    """Step 5.5 must be gated on $DECISION == APPROVE."""
    text = PR_REVIEW_SKILL.read_text()
    assert re.search(r'\$DECISION\s*==\s*APPROVE', text), (
        "skills/workflow-pr-review/SKILL.md must gate Step 5.5 on '$DECISION == APPROVE' "
        "so it never runs on a COMMENT decision"
    )


def test_step_5_5_invokes_evidence_and_resolve_subcommands():
    """Step 5.5 must invoke the threads-evidence and threads-resolve subcommands by exact name."""
    text = PR_REVIEW_SKILL.read_text()
    assert "swe-workbench-pr-review-threads evidence" in text, (
        "skills/workflow-pr-review/SKILL.md must call "
        "'swe-workbench-pr-review-threads evidence' by exact command name"
    )
    assert "swe-workbench-pr-review-threads resolve" in text, (
        "skills/workflow-pr-review/SKILL.md must call "
        "'swe-workbench-pr-review-threads resolve' by exact command name"
    )


def test_step_5_5_references_nothing_to_verify_short_circuit():
    """Step 5.5 must reference the nothing_to_verify field as its short-circuit gate."""
    text = PR_REVIEW_SKILL.read_text()
    assert "nothing_to_verify" in text, (
        "skills/workflow-pr-review/SKILL.md must reference 'nothing_to_verify' as the "
        "field that short-circuits Step 5.5 straight to Step 6"
    )


def test_step_5_5_uses_askuserquestion_with_both_option_labels():
    """Step 5.5 must call AskUserQuestion with 'Approve anyway' and 'Submit COMMENT' options."""
    text = PR_REVIEW_SKILL.read_text()
    assert "AskUserQuestion" in text, (
        "skills/workflow-pr-review/SKILL.md must call AskUserQuestion when threads remain open"
    )
    assert "Approve anyway" in text, (
        "skills/workflow-pr-review/SKILL.md must offer an 'Approve anyway' option"
    )
    assert "Submit COMMENT" in text, (
        "skills/workflow-pr-review/SKILL.md must offer a 'Submit COMMENT' option"
    )


def test_step_5_5_askuserquestion_prompt_preempted_by_flag():
    """The AskUserQuestion prompt must be documented as pre-answered/skipped when the
    override flag already arrived from the command layer."""
    text = PR_REVIEW_SKILL.read_text()
    assert re.search(r"APPROVE_OVER_OPEN_THREADS", text), (
        "skills/workflow-pr-review/SKILL.md must reference $APPROVE_OVER_OPEN_THREADS"
    )
    assert re.search(r"(?i)pre-answered|skipped entirely", text), (
        "skills/workflow-pr-review/SKILL.md must document that the AskUserQuestion prompt "
        "is pre-answered/skipped when $APPROVE_OVER_OPEN_THREADS already arrived non-empty"
    )


def test_step_5_5_resolve_reply_body_uses_head_sha():
    """The reply body sent to `resolve` for ADDRESSED threads must cite $HEAD_SHA."""
    text = PR_REVIEW_SKILL.read_text()
    assert "Verified addressed at $HEAD_SHA" in text, (
        "skills/workflow-pr-review/SKILL.md must build the ADDRESSED reply_body as "
        "'Verified addressed at $HEAD_SHA — resolving.'"
    )


def test_step_5_5_missing_anchor_status_never_addressed():
    """Step 5.5 must state that anchor_status: missing records are never ADDRESSED."""
    text = PR_REVIEW_SKILL.read_text()
    assert "anchor_status" in text and "missing" in text, (
        "skills/workflow-pr-review/SKILL.md must reference anchor_status/missing records"
    )
    assert re.search(r"(?i)missing.{0,200}never.{0,20}ADDRESSED|never.{0,20}ADDRESSED.{0,200}missing", text), (
        "skills/workflow-pr-review/SKILL.md must state that anchor_status: missing records "
        "are never ADDRESSED"
    )


def test_step_6_payload_includes_approve_over_open_threads():
    """Step 6's payload list to workflow-pr-review-post must literally contain APPROVE_OVER_OPEN_THREADS."""
    text = PR_REVIEW_SKILL.read_text()
    step6_start = text.index("### Step 6")
    step6_section = text[step6_start:text.index("### Step 7")]
    assert "APPROVE_OVER_OPEN_THREADS" in step6_section, (
        "skills/workflow-pr-review/SKILL.md Step 6 payload list must include "
        "APPROVE_OVER_OPEN_THREADS alongside PR/OWNER/REPO/etc."
    )


def test_common_mistakes_documents_unconditional_step_5_5_misuse():
    """Common mistakes table should warn against running Step 5.5 unconditionally
    (i.e. without the $DECISION == APPROVE gate)."""
    text = PR_REVIEW_SKILL.read_text()
    mistakes_start = text.index("## Common mistakes")
    mistakes_section = text[mistakes_start:]
    assert re.search(r"(?i)step 5\.5", mistakes_section), (
        "skills/workflow-pr-review/SKILL.md Common mistakes table must add a row about "
        "misusing the new Step 5.5 (e.g. running it unconditionally)"
    )


# ---------------------------------------------------------------------------
# Unit 2 — workflow-pr-review-post/SKILL.md
# ---------------------------------------------------------------------------


def test_post_core_input_contract_table_has_override_row():
    """Input contract table must document APPROVE_OVER_OPEN_THREADS / --approve-over-open-threads."""
    text = POST_CORE_SKILL.read_text()
    assert "APPROVE_OVER_OPEN_THREADS" in text, (
        "skills/workflow-pr-review-post/SKILL.md input contract table must document "
        "the APPROVE_OVER_OPEN_THREADS field"
    )
    assert "--approve-over-open-threads" in text, (
        "skills/workflow-pr-review-post/SKILL.md input contract table must document "
        "the --approve-over-open-threads CLI flag"
    )


def test_post_core_post_block_passes_override_flag():
    """The ## Post bash block must invoke swe-workbench-pr-review-submit with --approve-over-open-threads."""
    text = POST_CORE_SKILL.read_text()
    post_start = text.index("## Post")
    post_section = text[post_start:text.index("## Step 5")]
    assert '--approve-over-open-threads "$APPROVE_OVER_OPEN_THREADS"' in post_section, (
        "skills/workflow-pr-review-post/SKILL.md ## Post block must pass "
        '--approve-over-open-threads "$APPROVE_OVER_OPEN_THREADS" to swe-workbench-pr-review-submit'
    )


def test_post_core_documents_blocked_by_unresolved_stays_true_regardless_of_override():
    """The gate-semantics prose must state blocked_by_unresolved stays the true count regardless of override."""
    text = POST_CORE_SKILL.read_text()
    assert "blocked_by_unresolved" in text, (
        "skills/workflow-pr-review-post/SKILL.md must reference .data.blocked_by_unresolved"
    )
    assert re.search(r"(?i)blocked_by_unresolved.{0,200}(true|regardless)", text) or re.search(
        r"(?i)regardless.{0,200}blocked_by_unresolved", text
    ), (
        "skills/workflow-pr-review-post/SKILL.md must state that .data.blocked_by_unresolved "
        "stays the true, non-zero count regardless of whether the override fired"
    )


def test_post_core_failure_mode_row_mentions_override():
    """The blocked_by_unresolved failure-mode row must mention the override flag as an alternative."""
    text = POST_CORE_SKILL.read_text()
    row_lines = [
        line for line in text.splitlines()
        if line.startswith("|") and line.rstrip().endswith("|") and "blocked_by_unresolved > 0" in line
    ]
    assert row_lines, (
        "skills/workflow-pr-review-post/SKILL.md must have a failure-mode table row for "
        "'.data.blocked_by_unresolved > 0'"
    )
    row = row_lines[0]
    assert "APPROVE_OVER_OPEN_THREADS" in row or "--approve-over-open-threads" in row, (
        "skills/workflow-pr-review-post/SKILL.md's blocked_by_unresolved failure-mode row must "
        "mention the override flag as an alternative to manually resolving each thread"
    )


# ---------------------------------------------------------------------------
# Unit 3 — commands/review.md
# ---------------------------------------------------------------------------


def test_review_cmd_parses_approve_over_open_threads_flag():
    """Step 1 must parse --approve-over-open-threads."""
    text = REVIEW_CMD.read_text()
    assert "--approve-over-open-threads" in text, (
        "commands/review.md must document parsing of --approve-over-open-threads in "
        "## Step 1 — Argument resolution"
    )


def test_review_cmd_passes_flag_to_both_delegations():
    """Both the PR-mode MODE=auto and Followup-mode MODE=followup delegations must
    carry $APPROVE_OVER_OPEN_THREADS through to swe-workbench:workflow-pr-review."""
    text = REVIEW_CMD.read_text()
    delegation_lines = [
        line for line in text.splitlines()
        if "workflow-pr-review" in line and "via the `Skill` tool" in line
    ]
    assert len(delegation_lines) >= 2, (
        "commands/review.md must invoke swe-workbench:workflow-pr-review via the Skill tool "
        "at least twice (PR-mode MODE=auto and Followup-mode MODE=followup)"
    )
    for line in delegation_lines:
        assert "APPROVE_OVER_OPEN_THREADS" in line, (
            f"commands/review.md delegation line must pass $APPROVE_OVER_OPEN_THREADS through: {line!r}"
        )


def test_review_cmd_documents_when_flag_is_safe():
    """commands/review.md must document that the flag is only safe post-verification,
    as an answer to (or a way to pre-empt) Step 5.5's AskUserQuestion prompt."""
    text = REVIEW_CMD.read_text()
    assert re.search(r"(?i)when this flag is safe", text), (
        "commands/review.md must document when --approve-over-open-threads is safe to use"
    )
    assert "Step 5.5" in text, (
        "commands/review.md must reference Step 5.5 (skills/workflow-pr-review/SKILL.md) "
        "as the verification step this flag answers/pre-empts"
    )


# ---------------------------------------------------------------------------
# Unit 4 — no issue-number self-citation
# ---------------------------------------------------------------------------


def test_no_issue_number_self_citation():
    """No file touched by this change may reference the tracking issue number."""
    for path in (PR_REVIEW_SKILL, POST_CORE_SKILL, REVIEW_CMD):
        text = path.read_text()
        assert "712" not in text, (
            f"{path} must not contain '712' (issue-number self-citation) — issue refs "
            "belong in the PR body only"
        )
