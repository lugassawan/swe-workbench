"""Regression tests for issue #531 — inline-byline removal, pending-review
(atomic) posting, and the public-only swe-workbench remark.

Target end state (see the #531 plan):
  - Inline comment bodies (public or private repo) carry finding text only —
    no byline, no remark, ever.
  - The summary byline includes the ` ([swe-workbench](url))` remark only
    when the target repo is confirmed public; private/unknown omits it
    (fail-safe).
  - Inline findings post via one atomic `POST /pulls/{n}/reviews` call
    (comments[] + event) instead of a per-finding loop; self-review submits
    `event=COMMENT` (GitHub blocks self-APPROVE) so inline comments still
    land instead of being skipped outright.

Scope: skills/workflow-pr-review-post/SKILL.md (the shared posting core) —
the only file that owns posting mechanics per the #499 dependency rule.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POST_CORE_SKILL = ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md"


def _text() -> str:
    return POST_CORE_SKILL.read_text()


# ---------------------------------------------------------------------------
# (a) inline comment bodies must never contain the byline/remark
# ---------------------------------------------------------------------------


def test_input_contract_forbids_byline_in_inline_bodies():
    text = _text()
    assert re.search(
        r"(?i)inline comment bod(?:y|ies).{0,120}must not contain the byline",
        text,
    ), (
        "workflow-pr-review-post: the input contract must explicitly forbid the "
        "byline/remark from appearing in any inline (comments[]) finding body "
        "(#531 regression guard)"
    )


def test_comments_assembly_body_is_finding_body_verbatim():
    text = _text()
    assert '--arg body "$BODY"' in text, (
        "workflow-pr-review-post: comments[] body assembly must set "
        "body=$BODY verbatim (the finding's own body), via jq --arg"
    )
    for bad in (
        '--arg body "$BYLINE"',
        '--arg body "$BYLINE_FULL"',
        '--arg body "$REMARK"',
        'body: $body} + $BYLINE',
    ):
        assert bad not in text, (
            f"workflow-pr-review-post: comments[] body must never concatenate "
            f"{bad!r} — the byline/remark is a Step 4 review-level concern only"
        )


# ---------------------------------------------------------------------------
# (b) isPrivate detection + public-only remark + unknown -> omit fail-safe
# ---------------------------------------------------------------------------


def test_visibility_detected_via_gh_repo_view_isprivate():
    text = _text()
    assert re.search(r'IS_PRIVATE=\$\(gh repo view .*isPrivate', text), (
        "workflow-pr-review-post: IS_PRIVATE must be assigned from a "
        "'gh repo view ... --json isPrivate -q .isPrivate' call"
    )


def test_remark_gated_on_confirmed_public_not_absence_of_true():
    text = _text()
    assert re.search(r'"\$IS_PRIVATE"\s*=\s*"false"', text), (
        "workflow-pr-review-post: the remark must be gated on IS_PRIVATE = \"false\" "
        "(confirmed public) — gating on '!= true' would wrongly include the "
        "empty/error case"
    )


def test_remark_omitted_on_unknown_visibility_failsafe():
    text = _text()
    assert re.search(r"(?i)fail-safe.{0,60}never advertise", text), (
        "workflow-pr-review-post: must document that an empty/errored IS_PRIVATE "
        "result omits the remark (fail-safe — never advertise on an unconfirmed repo)"
    )


# ---------------------------------------------------------------------------
# (c) self-review submits EVENT=COMMENT, never APPROVE
# ---------------------------------------------------------------------------


def test_self_review_forces_event_comment():
    text = _text()
    assert re.search(
        r'if \[ "\$IS_SELF_REVIEW" = true \]; then EVENT=COMMENT', text
    ), (
        "workflow-pr-review-post: self-review must force EVENT=COMMENT "
        "regardless of $DECISION (GitHub blocks self-APPROVE but allows "
        "self-COMMENT, so inline comments still land)"
    )
    assert 'SUMMARY=""' not in text, (
        "workflow-pr-review-post: the old skip-submit SUMMARY=\"\" self-review "
        "branch must be removed — self-review now submits event=COMMENT with a "
        "real body instead of skipping submit entirely"
    )


def test_never_approve_on_self_review_documented():
    text = _text()
    assert re.search(r"(?i)never.{0,20}APPROVE.{0,20}self-review", text), (
        "workflow-pr-review-post: must explicitly document that self-review "
        "never submits APPROVE"
    )


# ---------------------------------------------------------------------------
# (d) empty comments[] falls through to gh pr review --approve|--comment
# ---------------------------------------------------------------------------


def test_empty_comments_falls_through_to_gh_pr_review():
    text = _text()
    assert re.search(r'\[\s*"\$N"\s*-gt\s*0\s*\]', text), (
        "workflow-pr-review-post: submit must branch on whether N (candidate "
        "inline count) is greater than zero"
    )
    assert re.search(r"gh pr review .*--approve", text), (
        "workflow-pr-review-post: the empty/fallback path must still support "
        "gh pr review --approve"
    )
    assert re.search(r"gh pr review .*--comment", text), (
        "workflow-pr-review-post: the empty/fallback path must still support "
        "gh pr review --comment"
    )


# ---------------------------------------------------------------------------
# (e) atomic-422 retries once against a re-fetched HEAD, then falls back
# ---------------------------------------------------------------------------


def test_atomic_422_retries_once_then_falls_back_to_model_a():
    text = _text()
    assert re.search(r"(?i)retry.{0,30}once", text), (
        "workflow-pr-review-post: must document a single retry on a "
        "whole-review 422"
    )
    assert re.search(r"headRefOid", text), (
        "workflow-pr-review-post: the 422 retry must re-fetch HEAD_SHA via "
        "'gh pr view ... --json headRefOid'"
    )
    assert re.search(r"(?i)model-A", text), (
        "workflow-pr-review-post: must document the model-A per-comment "
        "fallback path reachable after a confirmed double-422"
    )


def test_never_blind_retries_on_network_or_5xx():
    text = _text()
    assert re.search(r"(?i)never.{0,20}blind-retry", text), (
        "workflow-pr-review-post: must document that network/5xx failures are "
        "never blind-retried (no idempotency key — a retried success after an "
        "already-landed post would double-post every comment)"
    )


# ---------------------------------------------------------------------------
# Reviewer-caught regression: the pre-submit SUMMARY is embedded in the
# atomic POST's own body= field, so it must be built from the frozen
# candidate count $N — $posted_inline is not assigned until *after* that
# same POST is attempted, so referencing it in the pre-submit body silently
# expands to an empty string in the review actually posted to GitHub.
# ---------------------------------------------------------------------------


def test_pre_submit_summary_built_from_candidate_count_n():
    text = _text()
    assert "Posted ${N} inline comment(s)" in text, (
        "workflow-pr-review-post: the pre-submit BYLINE_FULL (embedded into the "
        "atomic POST's own body=$SUMMARY) must read 'Posted ${N} inline "
        "comment(s)' — $posted_inline is unset until Step 4's atomic POST "
        "attempt completes, so using it in the pre-submit body posts an empty "
        "count on every successful atomic-path run"
    )


def test_deduped_count_tracked_in_dedup_match_branch():
    text = _text()
    assert re.search(r"(?i)increment.{0,20}`?\$?deduped", text), (
        "workflow-pr-review-post: the dedup 'On match' branch must explicitly "
        "instruct incrementing $deduped — the old single-paragraph "
        "'posted_inline=N, deduped=M' tracking note was removed when Step 2 "
        "was rewritten and never replaced"
    )


def test_422_retry_rebuilds_comments_against_refreshed_head():
    text = _text()
    assert re.search(r"STILL_IN_DIFF|re-check.{0,40}in.diff", text, re.IGNORECASE), (
        "workflow-pr-review-post: the 422 retry must actually re-validate/rebuild "
        "COMMENTS_ARGS against the refreshed HEAD_SHA (not just claim to in prose "
        "while reusing the original unchanged array) — a genuinely stale line "
        "would otherwise 422 again on retry"
    )


def test_fallback_loop_never_silently_drops_a_finding():
    text = _text()
    assert re.search(
        r"(?i)fallback.{0,200}never.{0,20}drop|never.{0,40}drop.{0,200}fallback",
        text,
        re.DOTALL,
    ), (
        "workflow-pr-review-post: the model-A fallback loop must document that "
        "a comment failing even the individual per-comment POST is demoted to a "
        "follow-up pr-level comment and logged — never silently skipped"
    )
