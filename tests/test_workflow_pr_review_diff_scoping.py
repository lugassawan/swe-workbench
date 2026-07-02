# tests/test_workflow_pr_review_diff_scoping.py

"""
Tests for the diff-scoping leniency contract (issue #304).

Three contract layers:
  Unit 1 — agents/reviewer.md  (scope classification, per-finding marker, verdict line)
  Unit 2 — workflow-pr-review/SKILL.md and workflow-pr-review-followup/SKILL.md
            (Step 4 instruction, Step 5 parse, Step 6 422 reroute, Step 7 flip + self-review gate)
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
REVIEWER_MD = ROOT / "agents" / "reviewer.md"

SKILLS = [
    ROOT / "skills" / "workflow-pr-review" / "SKILL.md",
    ROOT / "skills" / "workflow-pr-review-followup" / "SKILL.md",
]


# ---------------------------------------------------------------------------
# Unit 1 — reviewer.md
# ---------------------------------------------------------------------------


def test_reviewer_md_exists():
    assert REVIEWER_MD.exists(), "agents/reviewer.md must exist"


def test_reviewer_documents_all_blocking_scope_values():
    """The agent must document all three Blocking Scope verdict values."""
    text = REVIEWER_MD.read_text()
    assert "Blocking Scope: NONE" in text, (
        "reviewer.md must document 'Blocking Scope: NONE' (no Critical/High)"
    )
    assert "Blocking Scope: OUT-OF-DIFF-ONLY" in text, (
        "reviewer.md must document 'Blocking Scope: OUT-OF-DIFF-ONLY' (all Critical/High out of diff)"
    )
    assert "Blocking Scope: IN-DIFF" in text, (
        "reviewer.md must document 'Blocking Scope: IN-DIFF' (at least one in-diff Critical/High)"
    )


def test_reviewer_documents_informational_marker():
    """The agent must document the per-finding out-of-diff informational marker."""
    text = REVIEWER_MD.read_text()
    assert "Informational (out-of-diff)" in text, (
        "reviewer.md must document the '**Informational (out-of-diff):**' prefix "
        "so out-of-diff Critical/High findings are marked non-blocking"
    )


def test_reviewer_blocking_scope_verdict_section_exists():
    """reviewer.md must have a ## Blocking-scope verdict section."""
    text = REVIEWER_MD.read_text()
    assert re.search(r"^##\s+Blocking-scope verdict", text, re.MULTILINE), (
        "reviewer.md must contain a '## Blocking-scope verdict' section "
        "that instructs the agent when and how to emit the verdict line"
    )


def test_reviewer_verdict_is_opt_in():
    """Verdict must only fire when a Decision footer is instructed (mirrors the footer's opt-in)."""
    text = REVIEWER_MD.read_text()
    # The section must tie verdict emission to footer instruction — look for
    # "when instructed" language near the blocking-scope verdict section.
    assert re.search(r"(?i)when instructed", text), (
        "reviewer.md must state that the blocking-scope verdict is opt-in "
        "(emitted only when a Decision footer is instructed)"
    )


def test_reviewer_footer_rule_unchanged():
    """The COMMENT/APPROVE footer rule must remain unchanged — COMMENT on any Critical/High."""
    text = REVIEWER_MD.read_text()
    # Original footer rule: "at least one Critical/High finding" → COMMENT
    assert re.search(r"Critical.*High.*COMMENT|COMMENT.*Critical.*High", text), (
        "reviewer.md footer rule must still key COMMENT on Critical/High findings — "
        "the diff-scoping flip is the orchestrator's job, not the agent's"
    )


def test_reviewer_verdict_emitted_before_footer():
    """The verdict line must be emitted immediately before the Review Decision footer."""
    text = REVIEWER_MD.read_text()
    assert re.search(r"(?i)before.*Review Decision|before.*footer|immediately before", text), (
        "reviewer.md must instruct the agent to emit the Blocking Scope verdict "
        "immediately before the **Review Decision:** footer line"
    )


def test_reviewer_in_diff_defined_as_plus_lines():
    """reviewer.md must define 'in-diff' as lines added/modified by the PR ('+' lines in the diff)."""
    text = REVIEWER_MD.read_text()
    assert re.search(r"in-diff.*\+|`\+`.*in-diff|added.*modified|`\+`.*line", text, re.IGNORECASE), (
        "reviewer.md must define 'in-diff' as lines added or modified by this PR "
        "('+' lines in the unified diff), not just lines inside a displayed hunk"
    )


# ---------------------------------------------------------------------------
# Unit 2 — orchestrators (parametrized over both skills)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_skill_exists(skill_path):
    assert skill_path.exists(), f"{skill_path} must exist"


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step4_blocking_scope_instruction(skill_path):
    """Step 4 must instruct the agent to classify scope and emit the Blocking Scope verdict."""
    text = skill_path.read_text()
    assert re.search(r"(?i)Blocking.Scope", text), (
        f"{skill_path.parent.name}: Step 4 must include a blocking-scope instruction "
        "so the reviewer agent knows to classify and emit the verdict"
    )
    assert re.search(r"(?i)Blocking.Scope.*instruction|classify.*scope|scope.*instruct", text), (
        f"{skill_path.parent.name}: Step 4 must explicitly instruct the agent "
        "on how to classify in-diff vs out-of-diff findings"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step5_parses_blocking_scope(skill_path):
    """Step 5 must parse the Blocking Scope verdict line into $BLOCKING_SCOPE."""
    text = skill_path.read_text()
    assert re.search(r"BLOCKING_SCOPE", text), (
        f"{skill_path.parent.name}: Step 5 must parse the verdict into $BLOCKING_SCOPE"
    )
    # The regex used to parse must cover all three valid values
    assert re.search(r"NONE|OUT-OF-DIFF-ONLY|IN-DIFF", text), (
        f"{skill_path.parent.name}: Step 5 parse regex must enumerate all three verdict values"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step5_malformed_verdict_defaults_to_in_diff(skill_path):
    """Missing/malformed verdict must default BLOCKING_SCOPE=IN-DIFF (fail-safe)."""
    text = skill_path.read_text()
    assert re.search(r"BLOCKING_SCOPE\s*=\s*IN-DIFF", text), (
        f"{skill_path.parent.name}: Step 5 must default BLOCKING_SCOPE=IN-DIFF on "
        "zero or multiple verdict matches (fail-safe — never auto-approves on ambiguity)"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step7_flip_gate_conditions(skill_path):
    """Step 7 flip must be gated on DECISION=COMMENT AND OUT-OF-DIFF-ONLY AND IS_SELF_REVIEW=false AND identity-known."""
    text = skill_path.read_text()
    # All four conditions must appear near the flip block
    assert re.search(r'DECISION.*=.*COMMENT.*OUT-OF-DIFF-ONLY|OUT-OF-DIFF-ONLY.*DECISION.*=.*COMMENT', text), (
        f"{skill_path.parent.name}: Step 7 flip must check DECISION=COMMENT AND BLOCKING_SCOPE=OUT-OF-DIFF-ONLY"
    )
    assert re.search(r'IS_SELF_REVIEW.*false|IS_SELF_REVIEW.*=.*false', text), (
        f"{skill_path.parent.name}: Step 7 flip must check IS_SELF_REVIEW=false (self-review AC#4)"
    )
    assert re.search(r'IDENTITY_KNOWN', text), (
        f"{skill_path.parent.name}: Step 7 flip must check IDENTITY_KNOWN=true to fail-safe "
        "when reviewer/author identity is unknown"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step7_flip_sets_decision_approve(skill_path):
    """When flip fires, DECISION must be set to APPROVE."""
    text = skill_path.read_text()
    assert re.search(r"DECISION\s*=\s*APPROVE", text), (
        f"{skill_path.parent.name}: Step 7 flip must set DECISION=APPROVE "
        "when all blocking findings are out-of-diff on a cross-author PR"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step7_self_review_regression_guard(skill_path):
    """AC#4: self-review must never trigger the flip. IS_SELF_REVIEW=false must be in the flip condition."""
    text = skill_path.read_text()
    # The flip block must explicitly check IS_SELF_REVIEW = false.
    # We look for the condition in the if-block that also contains DECISION=APPROVE.
    flip_block = re.search(
        r'(if\s.*?DECISION\s*=\s*APPROVE.*?fi|DECISION\s*=\s*APPROVE)',
        text, re.DOTALL
    )
    assert flip_block is not None, (
        f"{skill_path.parent.name}: could not locate the DECISION=APPROVE flip block"
    )
    assert re.search(r'IS_SELF_REVIEW.*false', text), (
        f"{skill_path.parent.name}: AC#4 — the DECISION=APPROVE flip block MUST reference "
        "IS_SELF_REVIEW=false so self-reviews never auto-flip to APPROVE"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step6_out_of_diff_422_rerouted_to_summary(skill_path):
    """Step 6: out-of-diff informational findings that 422 must be rerouted to summary, not cause abort."""
    text = skill_path.read_text()
    assert re.search(r"DEFERRED_INFORMATIONAL", text), (
        f"{skill_path.parent.name}: Step 6 must accumulate out-of-diff 422'd findings "
        "in DEFERRED_INFORMATIONAL for rerouting to the summary (not dropped or counted as stale-SHA)"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step6_stale_sha_detection_scoped_to_in_diff(skill_path):
    """Stale-SHA (all 422) detection must apply only to in-diff findings, not out-of-diff 422s."""
    text = skill_path.read_text()
    assert re.search(r"(?i)in.diff.*422|stale.*in.diff|422.*in.diff", text), (
        f"{skill_path.parent.name}: the stale-SHA / all-422 abort must be scoped to "
        "in-diff findings only — expected out-of-diff 422s must not trigger a false abort"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step7_deferred_informational_appended_to_summary(skill_path):
    """When DEFERRED_INFORMATIONAL is non-empty, Step 7 must append an Informational section to summary."""
    text = skill_path.read_text()
    assert re.search(r"(?i)Informational.*out-of-diff|out-of-diff.*Informational", text), (
        f"{skill_path.parent.name}: Step 7 must append an '### Informational (out-of-diff)' "
        "section to the summary when DEFERRED_INFORMATIONAL is non-empty, "
        "so no out-of-diff finding is silently dropped"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step7_lean_body_no_narrative(skill_path):
    """Step 7 non-self-review body must use the lean form: no ## Review Summary, no
    'Detailed feedback in inline comments.', no NARRATIVE extraction variables."""
    text = skill_path.read_text()
    assert "## Review Summary" not in text, (
        f"{skill_path.parent.name}: '## Review Summary' must not appear — the narrative "
        "is fully removed; the review body carries only the decision + byline + informational notes."
    )
    assert "Detailed feedback in inline comments." not in text, (
        f"{skill_path.parent.name}: 'Detailed feedback in inline comments.' must not appear — "
        "this phrase belonged to the removed narrative branch."
    )
    assert "HAS_NARRATIVE" not in text, (
        f"{skill_path.parent.name}: HAS_NARRATIVE variable must be removed along with the "
        "NARRATIVE extraction block."
    )
    assert "Narrative instruction" not in text, (
        f"{skill_path.parent.name}: 'Narrative instruction' Step-4 bullet must be removed — "
        "the reviewer is no longer instructed to emit a narrative section."
    )
    assert "$REVIEWER_OUTPUT" not in text, (
        f"{skill_path.parent.name}: '$REVIEWER_OUTPUT' is a dangling reference left by the "
        "narrative removal (#391) — the lean body is built from $DECISION/$BYLINE only, not "
        "from reviewer output. Remove the stale Step 7 prose that names it."
    )
    assert "decision line + byline" in text, (
        f"{skill_path.parent.name}: Step 7 prose must affirm the lean-body intent — "
        "'decision line + byline' directive is missing. Findings must not be restated in the body."
    )


def test_reviewer_no_review_summary_section():
    """agents/reviewer.md must no longer contain the ## Review Summary (when instructed) section."""
    text = REVIEWER_MD.read_text()
    assert "## Review Summary" not in text, (
        "agents/reviewer.md still contains '## Review Summary' — delete the entire "
        "'## Review Summary (when instructed)' block; the orchestrator no longer requests it."
    )
    assert "orchestrator extracts these paragraphs" not in text, (
        "agents/reviewer.md still contains explanatory prose from the deleted "
        "'## Review Summary (when instructed)' block — the full section must be removed, "
        "not just the heading."
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_diff_scoping_contract_subsection_exists(skill_path):
    """A ## Diff-scoping flip contract subsection must document the flip gate and self-review exclusion."""
    text = skill_path.read_text()
    assert re.search(r"(?i)Diff.scoping flip contract|diff.scoping", text), (
        f"{skill_path.parent.name}: must contain a 'Diff-scoping flip contract' subsection "
        "documenting the flip gate, self-review exclusion, identity-unknown fail-safe, "
        "and the out-of-diff 422 reroute"
    )


# ---------------------------------------------------------------------------
# Stale-base fix (#414) — fetch + three-dot merge-base diff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step4_fetches_base_before_diff(skill_path):
    """Step 4 must fetch origin/$BASE in the worktree context before computing the diff."""
    text = skill_path.read_text()
    assert re.search(r'git -C "\$WT" fetch origin "\$BASE" --quiet \|\| true', text), (
        f"{skill_path.parent.name}: Step 4 must run "
        "'git -C \"$WT\" fetch origin \"$BASE\" --quiet || true' (in the worktree, with "
        "non-fatal guard) before the diff so already-merged commits on the remote base "
        "are excluded (fix for #414)"
    )


@pytest.mark.parametrize("skill_path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_step4_diff_uses_three_dot_remote_tracking_ref(skill_path):
    """Step 4 diff must use three-dot merge-base against origin/$BASE, not two-dot against local $BASE."""
    text = skill_path.read_text()
    assert re.search(r'diff "origin/\$BASE"\.\.\.HEAD', text), (
        f"{skill_path.parent.name}: Step 4 diff must be "
        "'git -C \"$WT\" diff \"origin/$BASE\"...HEAD' (three-dot = merge-base, "
        "remote-tracking ref) — not two-dot against local $BASE (fix for #414)"
    )
    assert not re.search(r'diff "\$BASE"\.\.HEAD', text), (
        f"{skill_path.parent.name}: Step 4 must NOT use 'diff \"$BASE\"..HEAD' "
        "(two-dot against local ref) — it produces a stale diff when the remote base "
        "has advanced past the feature branch's fork point (fix for #414)"
    )
