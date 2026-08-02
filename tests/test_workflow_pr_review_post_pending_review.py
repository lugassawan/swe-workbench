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
other #531 behavior (visibility detection, self-review event forcing,
empty-comments fallthrough, the bounded 422 retry, never-blind-retry,
pre-submit-summary-from-N, dedup counting, fallback-never-drops) now has a
direct behavioral equivalent in tests/test_pr_review_submit_script.py —
see its module docstring for the full mapping.
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
