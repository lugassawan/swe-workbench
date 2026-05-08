"""
Regression tests for the validate-pr CI issue-reference check.

These tests replicate the strip-then-match pipeline from
.github/workflows/pr.yml so the logic is verifiable without CI.
"""
import re


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def has_na_optout(visible: str) -> bool:
    return bool(
        re.search(
            r"^[[:space:]]*(Issue:[[:space:]]+)?N/A([[:space:]]+[—\-].+)?[[:space:]]*$",
            visible,
            re.IGNORECASE | re.MULTILINE,
        )
    )


def _na_optout(visible: str) -> bool:
    """Python-native equivalent of the bash grep -iqE pattern."""
    return bool(
        re.search(
            r"^[ \t]*(Issue:[ \t]+)?N/A([ \t]+[—\-].+)?[ \t]*$",
            visible,
            re.IGNORECASE | re.MULTILINE,
        )
    )


def has_closing_keyword(visible: str) -> bool:
    return bool(
        re.search(
            r"(close[sd]?|fix(e[sd])?|resolve[sd]?) #[0-9]+",
            visible,
            re.IGNORECASE,
        )
    )


PR_127_BODY = """\
## Summary
<!-- Describe what changed and why. Use bullet points. -->
-

## Test Plan
<!-- How did you verify this works? Check the boxes. -->
- [ ] Changed skills/commands/agents load without errors
- [ ] Examples in the diff were exercised manually
- [ ]

<!-- Link to the GitHub issue this PR addresses.
     Use one of:  Closes #<number>  |  Fixes #<number>  |  Resolves #<number>

     If no issue applies, DELETE the "Closes #" line and replace it with
     a standalone line:
         Issue: N/A
     Preferred (more useful for reviewers):
         Issue: N/A — <one-line reason, e.g. "trivial docs typo" or "urgent hotfix">

     The following WILL fail CI:
       - leaving "Closes #" empty with no replacement
       - deleting the line entirely with nothing in its place
       - writing "Closes N/A" or "Closes #N/A" (malformed — use a standalone "Issue: N/A" instead) -->
Closes #
"""

BODY_STANDALONE_NA = """\
## Summary
- Fixed the thing

## Test Plan
- [x] Tested manually

Issue: N/A — internal tooling, no user-facing issue
"""

BODY_WITH_CLOSES = """\
## Summary
- Added new feature

## Test Plan
- [x] Tests pass

Closes #42
"""


class TestStripHtmlComments:
    def test_removes_single_line_comment(self):
        assert strip_html_comments("<!-- foo -->bar") == "bar"

    def test_removes_multiline_comment(self):
        result = strip_html_comments("before\n<!-- \n  multi\n  line\n -->after")
        assert "Issue: N/A" not in result
        assert "after" in result

    def test_preserves_text_outside_comments(self):
        result = strip_html_comments("<!-- hidden -->visible")
        assert result == "visible"


class TestPr127Regression:
    """PR #127 was merged with unfilled template — validate-pr CI passed incorrectly
    because 'Issue: N/A' inside an HTML comment matched the opt-out regex."""

    def test_na_inside_comment_does_not_trigger_optout(self):
        visible = strip_html_comments(PR_127_BODY)
        assert not _na_optout(visible), (
            "Issue: N/A inside an HTML comment must NOT trigger the opt-out"
        )

    def test_na_inside_comment_does_not_match_closing_keyword(self):
        visible = strip_html_comments(PR_127_BODY)
        assert not has_closing_keyword(visible), (
            "'Closes #' with no number must NOT match the closing-keyword pattern"
        )


class TestValidOptout:
    def test_standalone_na_triggers_optout(self):
        visible = strip_html_comments(BODY_STANDALONE_NA)
        assert _na_optout(visible), "Standalone 'Issue: N/A' must trigger the opt-out"

    def test_standalone_na_with_reason_triggers_optout(self):
        body = "## Summary\n- x\n\nIssue: N/A — internal tooling\n"
        visible = strip_html_comments(body)
        assert _na_optout(visible)

    def test_closes_with_number_matches(self):
        visible = strip_html_comments(BODY_WITH_CLOSES)
        assert has_closing_keyword(visible), "'Closes #42' must match the closing-keyword pattern"

    def test_fixes_with_number_matches(self):
        body = "## Summary\n- x\n\nFixes #99\n"
        visible = strip_html_comments(body)
        assert has_closing_keyword(visible)
