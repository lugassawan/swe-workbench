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
never-blind-retry: test_5xx_issues_zero_retries_and_one_read_your_write_call;
pre-submit-summary-from-N: test_atomic_post_carries_candidate_count_in_body;
fallback-never-drops: test_double_422_falls_through_to_per_comment_model_a)
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
