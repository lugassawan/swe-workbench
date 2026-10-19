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

Scope: skills/workflow-pr-review-post/SKILL.md (the input contract) plus
bin/swe-workbench-pr-review-submit (the posting mechanism, since #550 moved
Steps 1-4 out of this file's bash+jq prose and into that script). The two
tests below pin input-contract prose that still lives in SKILL.md; every
other #531 behavior (visibility detection: test_build_byline_*; self-review
event forcing: test_resolve_event_self_review_never_yields_approve;
empty-comments fallthrough: test_n_zero_skips_atomic_post_entirely; the
bounded 422 retry: test_confirmed_422_retries_once_demotes_and_posts_second_review;
never-blind-retry: test_5xx_where_the_read_back_finds_no_marker_retries_once;
pre-submit-summary-from-N: test_atomic_post_carries_candidate_count_in_body;
demotion-never-drops: test_double_422_ends_in_a_single_body_only_post)
now has a direct behavioral equivalent in tests/test_pr_review_submit_script.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POST_CORE_SKILL = ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md"


def _text() -> str:
    return POST_CORE_SKILL.read_text()


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


def test_never_approve_on_self_review_documented():
    text = _text()
    assert re.search(r"(?i)never.{0,20}APPROVE.{0,20}self-review", text), (
        "workflow-pr-review-post: must explicitly document that self-review "
        "never submits APPROVE"
    )


def test_posting_core_documents_body_batch_budget_and_overflow():
    text = _text()
    assert re.search(r"single\s+`POST \.\.\./pulls/\{n\}/reviews`", text)
    assert re.search(r"up to 50 rows / ~60,000 characters", text)
    assert re.search(r"Only the overflow beyond that budget is posted\s+afterwards as issue-comment batches", text)
    assert re.search(r"the one allowed second mutation", text)


def test_posting_core_documents_the_failure_ladder_and_retry_file():
    text = _text()
    assert re.search(r"(?i)no per-comment fallback", text)
    assert re.search(r"(?i)never.{0,20}blind-retried", text)
    assert re.search(r"reads the reviews back and looks for\s+it", text)
    assert re.search(r"submitted as `COMMENT`.{0,80}never approved", text, re.S)
    assert "--retry-state" in text and "$RETRY_STATE" in text
    assert "submit-retry.json" in text
    assert re.search(r"`\.data\.skipped_reason = \"unchanged\"`", text)
    assert re.search(r"reworded\s+out-of-diff finding counts as new", text)
    assert re.search(r"two\s+`except Exception:` lines", text)
    assert re.search(r"after 5\s+failed attempts", text)


def test_posting_core_documents_address_feedback_provenance_markers():
    text = _text()
    assert "<!-- swe-workbench:review-findings -->" in text
    assert "<!-- swe-workbench:review-finding:<positive-integer> -->" in text
    assert "address-feedback" in text
    assert re.search(r"whether it sits in a review body or an issue comment", text)
    assert not re.search(r"Review summary bodies are not consumed", text)
