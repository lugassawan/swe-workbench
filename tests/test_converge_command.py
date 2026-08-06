"""Tests for the /swe-workbench:converge command (closes #592)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
CONVERGE_CMD = COMMANDS_DIR / "converge.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def _text():
    assert CONVERGE_CMD.exists(), "commands/converge.md must exist"
    return CONVERGE_CMD.read_text()


def _normalized():
    """Whitespace-collapsed text, for phrase assertions that may cross a
    manually-wrapped prose line break in the source markdown."""
    return re.sub(r"\s+", " ", _text())


def test_converge_command_file_exists():
    """commands/converge.md must exist and have valid frontmatter with description."""
    text = _text()
    fm = validate.parse_frontmatter(CONVERGE_CMD, text=text)
    assert fm is not None, "converge.md must have valid frontmatter"
    assert "description" in fm, "converge.md frontmatter must have a description field"


def test_converge_no_broken_skill_refs():
    """All swe-workbench: skill/agent refs in converge.md must resolve to skills/ or agents/ on disk."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    text = _text()
    pattern = re.compile(r"`swe-workbench:([\w-]+)`")
    missing = [
        sid for sid in set(pattern.findall(text))
        if not (skills_dir / sid).is_dir() and not (agents_dir / f"{sid}.md").is_file()
    ]
    assert not missing, f"converge.md references non-existent skills or agents: {missing}"


def test_converge_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:converge in the Commands table."""
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:converge" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:converge in the Commands table"
    )


def test_converge_in_readme():
    """README.md Commands bullet must include /swe-workbench:converge."""
    text = README.read_text()
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, "README.md must have a '- **Commands**' bullet line"
    assert "/swe-workbench:converge" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:converge"
    )


def test_converge_cap_default_and_loop_invariant():
    """Cap defaults to 4 reviews, overridable 2..6, and the loop always ends on a review."""
    text = _text()
    assert "MAX_REVIEWS = 4" in text or "CAP=4" in text, (
        "converge.md must state the specific default cap bound (4), not merely 'a cap exists'"
    )
    assert "2..6" in text or "2-6" in text, "converge.md must document the --cap override range 2..6"
    assert "the loop always ends on a review, never on a fix" in _normalized(), (
        "converge.md must state the loop invariant explicitly — a cap counting fixes would let "
        "the loop exit having just applied unverified edits"
    )


def test_converge_floor_is_medium_and_excludes_out_of_diff():
    """FLOOR is hardcoded Medium; out-of-diff findings are excluded from the convergence predicate."""
    text = _text()
    assert "`FLOOR` is hardcoded to `Medium`" in text, (
        "converge.md must assert the specific floor bound (Medium), not merely 'a floor exists'"
    )
    assert "Out-of-diff findings are excluded from the predicate" in text, (
        "converge.md must document that out-of-diff findings are excluded from the convergence predicate"
    )


def test_converge_ownership_gate_refuses():
    """The ownership gate compares gh api /user against the PR author and refuses — not warns."""
    text = _text()
    assert "gh api /user -q .login" in text, "converge.md must derive CURRENT_USER via gh api /user"
    assert 'gh pr view --json author -q .author.login' in text, (
        "converge.md must derive PR_AUTHOR via gh pr view --json author"
    )
    assert (
        "only runs on your own PRs" in text
    ), "converge.md must state the specific refusal wording, not merely mention both gh calls"
    assert "exit 1" in text


def test_converge_fixer_verify_before_fix_and_unfounded_distinct_from_rejected():
    """The fixer brief mandates verify-before-fix and defines UNFOUNDED distinctly from REJECTED."""
    text = _text()
    assert "Verify before you fix" in text, "converge.md must mandate verify-before-fix in the fixer brief"
    assert "`UNFOUNDED` is deliberately distinct from `REJECTED`" in text, (
        "converge.md must explicitly distinguish UNFOUNDED (false premise) from REJECTED "
        "(true but declined) — collapsing them hides reviewer-degradation signal"
    )


def test_converge_anchor_validation_precedes_termination_and_does_not_block():
    """Phase 1b (anchor validation) must appear before Phase 2 (termination check), and
    UNFOUNDED findings must not block convergence."""
    text = _text()
    idx_1b = text.find("Phase 1b")
    idx_2 = text.find("Phase 2")
    assert idx_1b != -1 and idx_2 != -1, "converge.md must have both a Phase 1b and a Phase 2 section"
    assert idx_1b < idx_2, "Phase 1b (anchor validation) must run before Phase 2 (termination check)"
    assert "Only anchor-valid findings count" in text, (
        "converge.md must state that UNFOUNDED findings do not block convergence — a converged "
        "round is one whose findings are all UNFOUNDED, not a blocked one"
    )


def test_converge_unverifiable_precondition_and_batched_escalation():
    """UNVERIFIABLE requires a codebase-first precondition; escalation is batched to one
    AskUserQuestion per round with a 4-finding ceiling."""
    text = _text()
    assert "exhaust the codebase first, escalate only when it is silent" in _normalized(), (
        "converge.md must state the codebase-first precondition for UNVERIFIABLE"
    )
    assert "One batched `AskUserQuestion` per round, never one per finding" in text, (
        "converge.md must mandate exactly one AskUserQuestion call per round"
    )
    assert "More than 4 `UNVERIFIABLE` findings in one round" in text, (
        "converge.md must assert the specific ceiling bound (4), not merely 'a ceiling exists'"
    )


def test_converge_adjudicated_answers_cached_and_replayed():
    """Adjudicated answers are cached keyed by fingerprint and replayed into suppression —
    the same question must never be asked twice across rounds."""
    text = _text()
    assert "adjudicated[]" in text
    assert "the same question is never asked twice" in text, (
        "converge.md must state the never-ask-twice guarantee explicitly — a regression here "
        "turns an unattended loop into a prompt loop"
    )


def test_converge_fixer_prohibits_test_weakening():
    """The fixer prohibition list must name test-weakening explicitly."""
    text = _text()
    for term in ("xfail", "@Ignore", "weaken an assertion", "lower a coverage threshold"):
        assert term in text, f"converge.md fixer prohibitions must name '{term}' explicitly"


def test_converge_red_tests_and_zero_edit_are_hard_stops():
    """A red test suite and a zero-edit fix pass must both be documented hard stops."""
    text = _text()
    assert "A red tree ends the loop (hard stop)" in _normalized()
    assert "Zero-edit stop (hard stop)" in text


def test_converge_terminal_reap_covers_all_seven_exit_paths():
    """Phase 6 (terminal reap) must cover all seven exit paths and call swe-workbench-reap-run-dir."""
    text = _text()
    assert (
        "converged, cap exhausted, oscillation, red tree, zero-edit, too-many-unverifiable, "
        "parse fault" in _normalized()
    ), "converge.md must enumerate all seven terminal exit paths in Phase 6"
    assert "swe-workbench-reap-run-dir \"$RUN_DIR\"" in text


def test_converge_run_dir_prefix_matches_allowlist_in_both_bin_scripts():
    """The review-converge run-dir prefix must match the review-[a-z][a-z-]* allowlist regex
    in both bin/swe-workbench-new-run-dir and bin/swe-workbench-reap-run-dir — asserted
    against the scripts themselves so a future allowlist edit fails loudly here."""
    text = _text()
    assert "review-converge" in text, "converge.md must use the review-converge run-dir prefix"

    allowlist_pattern = re.compile(
        r"review-\[a-z\]\[a-z-\]\*"
    )
    for script_name in ("swe-workbench-new-run-dir", "swe-workbench-reap-run-dir"):
        script_text = (ROOT / "bin" / script_name).read_text()
        assert allowlist_pattern.search(script_text), (
            f"bin/{script_name} must still allowlist the review-[a-z][a-z-]* prefix shape"
        )
        assert re.match(r"^review-[a-z][a-z-]*$", "review-converge"), (
            "review-converge must itself match the review-[a-z][a-z-]* shape"
        )


def test_converge_jaccard_dedup_threshold():
    """The cross-round dedup threshold must be the specific bound 0.4, not merely 'a threshold exists'."""
    text = _text()
    assert "Jaccard ≥ 0.4" in text, "converge.md must assert the specific Jaccard threshold (0.4)"


def test_converge_findings_schema_matches_pr_review_submit():
    """converge.md must reuse the existing findings schema validated by _finding_problem(),
    not invent a second one."""
    text = _text()
    assert "{severity, body, anchor, path, line}" in text
    assert "_finding_problem()" in text
    assert "bin/swe-workbench-pr-review-submit" in text


def test_converge_never_pushes_on_non_convergence():
    text = _text()
    assert "Non-convergence never pushes" in text


def test_converge_cap_check_runs_before_fix_not_after():
    """Regression guard: the cap check must gate Phase 3 (fix) from Phase 2 (termination
    check), not fire after Phase 4's commit — otherwise the loop can terminate immediately
    after an unreviewed fix, contradicting its own 'ends on a review' invariant."""
    text = _text()
    idx_phase2 = text.find("## Phase 2")
    idx_phase3 = text.find("## Phase 3 —")
    idx_phase4 = text.find("## Phase 4")
    assert -1 not in (idx_phase2, idx_phase3, idx_phase4)
    phase2_body = text[idx_phase2:idx_phase3]
    phase4_body = text[idx_phase4:]
    assert "check the cap before fixing anything" in phase2_body, (
        "the cap check must be documented inside Phase 2, before the loop is allowed into Phase 3"
    )
    assert "Only proceed to Phase 3 when `N < CAP`" in phase2_body
    assert "has reached `CAP`, in which case jump to Phase 6" not in phase4_body, (
        "Phase 4 must not re-introduce a post-fix cap check — that was the regression"
    )


def test_converge_out_of_diff_distinct_from_unfounded():
    """OUT-OF-DIFF anchor rows must be tracked separately from UNFOUNDED — a path outside the
    branch diff is an untested claim, not a false one, and must not inflate the
    reviewer-degradation signal."""
    text = _text()
    assert "out_of_diff[]" in text
    assert "OUT-OF-DIFF (excluded from predicate)" in text
    assert "never `unfounded[]`" in _normalized() or "never `unfounded[]`." in text


def test_converge_fixer_brief_overrides_code_impl_default_contract():
    """The fixer brief must explicitly override code-impl's own status/files_changed contract,
    since the per-finding disposition format the ledger parses is not code-impl's default."""
    text = _text()
    assert "explicitly overrides `swe-workbench:code-impl`'s standard" in _normalized()
