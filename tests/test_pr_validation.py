"""
Regression tests for the validate-pr CI issue-reference check.

These tests replicate the strip-then-match pipeline from
.github/workflows/pr.yml so the logic is verifiable without CI.
"""
import re
from pathlib import Path

import pytest

_PR_YML_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "pr.yml"
try:
    _PR_YML_TEXT: str | None = _PR_YML_PATH.read_text(encoding="utf-8")
except OSError:
    _PR_YML_TEXT = None


def _extract_pr_yml_pattern(anchor: str) -> str:
    """Extract the first capture group from pr.yml using a stable anchor regex.

    Uses re.DOTALL so anchors can span lines. Skips the test (pytest.skip) if
    pr.yml is absent — avoids a FileNotFoundError at collection time for partial
    checkouts. Raises AssertionError if the anchor cannot be located.
    """
    if _PR_YML_TEXT is None:
        pytest.skip(f"pr.yml not found at {_PR_YML_PATH} — skipping sync tests")
    m = re.search(anchor, _PR_YML_TEXT, re.DOTALL)
    if not m:
        raise AssertionError(
            f"could not locate anchor {anchor!r} in pr.yml — "
            "did the workflow change? Update the test or sync the drift."
        )
    return m.group(1)


def strip_html_comments(text: str) -> str:
    """Strip <!-- ... --> blocks. Unterminated comments are stripped to end-of-string."""
    return re.sub(r"<!--.*?(?:-->|$)", "", text, flags=re.DOTALL)


def _na_optout(visible: str) -> bool:
    """Python-native equivalent of the bash grep -iqE N/A opt-out pattern."""
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

    def test_unterminated_comment_stripped_to_end(self):
        body = "## Summary\n- x\n\n<!-- Issue: N/A\n(no closing tag)"
        result = strip_html_comments(body)
        assert "Issue: N/A" not in result

    def test_closing_keyword_inside_comment_not_visible(self):
        body = "## Summary\n- x\n\n<!-- Closes #42 -->\n"
        visible = strip_html_comments(body)
        assert not has_closing_keyword(visible), (
            "'Closes #42' inside an HTML comment must NOT match after stripping"
        )


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


class TestPrYamlSync:
    """Tie Python helper functions to the source-of-truth regexes in pr.yml.

    If someone edits a pattern in pr.yml without updating its Python mirror
    (or vice-versa), these tests fail with a clear diagnostic.
    """

    def test_html_stripper_matches_pr_yml(self):
        """strip_html_comments() must use the exact same regex as pr.yml."""
        # Anchor includes 'python3 -c' context so a future re.sub addition
        # above line 61 in pr.yml doesn't silently redirect extraction.
        extracted = _extract_pr_yml_pattern(r"python3 -c.*?re\.sub\(r'([^']+)'")
        # No POSIX classes — pattern is byte-identical between shell and Python.
        assert extracted == r"<!--.*?(?:-->|$)", (
            f"pr.yml HTML-stripper pattern {extracted!r} diverged from the "
            "pattern used in strip_html_comments() — sync one of them."
        )

    def test_na_optout_matches_pr_yml(self):
        """_na_optout() behaviour must match the pr.yml grep -iqE N/A pattern."""
        raw = _extract_pr_yml_pattern(
            r"Allow ad-hoc PRs.*?grep -iqE '([^']+)'"
        )
        # Translate POSIX [[:space:]] → [ \t] for Python re.
        py_pattern = raw.replace("[[:space:]]", r"[ \t]")
        yml_re = re.compile(py_pattern, re.IGNORECASE | re.MULTILINE)

        samples = [
            ("N/A",                                      True),
            ("Issue: N/A",                               True),
            ("Issue: N/A — internal tooling",            True),
            ("Issue: N/A — reason with trailing space ", True),
            ("\tN/A",                                    True),
            ("  N/A  ",                                  True),
            ("This is N/A",                              False),
            ("Closes #42",                               False),
            ("Fix N/A issue",                            False),
        ]
        for text, expected in samples:
            yml_result = bool(yml_re.search(text))
            py_result = _na_optout(text)
            assert yml_result == py_result, (
                f"yml_re and _na_optout() disagree on {text!r}: "
                f"yml={yml_result}, py={py_result}"
            )
            assert yml_result == expected, (
                f"yml regex gave {yml_result!r} for {text!r}, expected {expected}"
            )
            assert py_result == expected, (
                f"_na_optout() gave {py_result!r} for {text!r}, expected {expected}"
            )

    def test_closing_keyword_matches_pr_yml(self):
        """has_closing_keyword() behaviour must match the pr.yml grep -iqE closing pattern."""
        raw = _extract_pr_yml_pattern(
            r"Require a GitHub closing keyword.*?grep -iqE '([^']+)'"
        )
        yml_re = re.compile(raw, re.IGNORECASE)

        samples = [
            ("Closes #42",         True),
            ("closes #1",          True),
            ("Fixes #99",          True),
            ("Fixed #7",           True),
            ("Resolves #100",      True),
            ("resolved #99",       True),   # resolve[sd]? matches 'resolved' and 'resolves'
            ("resolves #99",       True),
            ("Fix #5",             True),   # fix(e[sd])? matches plain 'fix'
            ("Close #3",           True),   # close[sd]? matches plain 'close'
            ("see Closes #42",     True),   # keyword not required at line start
            ("Closes N/A",         False),
            ("Closes #N/A",        False),
            ("fixes the bug",      False),  # no #number
        ]
        for text, expected in samples:
            yml_result = bool(yml_re.search(text))
            py_result = has_closing_keyword(text)
            assert yml_result == py_result, (
                f"yml_re and has_closing_keyword() disagree on {text!r}: "
                f"yml={yml_result}, py={py_result}"
            )
            assert yml_result == expected, (
                f"yml regex gave {yml_result!r} for {text!r}, expected {expected}"
            )

    def test_title_pattern_locks_allowed_types(self):
        """PR title regex in pr.yml must accept only defined types."""
        pattern = _extract_pr_yml_pattern(r"Validate PR title.*?PATTERN='([^']+)'")
        title_re = re.compile(pattern)

        positives = [
            "[feat] Add something",
            "[fix] Fix the bug",
            "[refactor] Clean up code",
            "[test] Add tests",
            "[ci] Update workflow",
            "[docs] Update readme",
            "[perf] Improve speed",
            "[chore] Bump deps",
            "[polish] Minor cleanup",
            "[breaking] Remove old API",
            "[feat]: Add something with colon",
            "[fix]: Fix with colon",
        ]
        negatives = [
            "feat: foo",        # no brackets
            "[unknown] foo",    # unknown type
            "[fix]foo",         # missing space after bracket
            "[fix] ",           # empty description (only a space)
            "Fix the bug",      # no brackets at all
            "[FEAT] uppercase", # case-sensitive — uppercase not in allowed list
        ]

        for title in positives:
            assert title_re.match(title), (
                f"Expected {title!r} to match PR title pattern"
            )
        for title in negatives:
            assert not title_re.match(title), (
                f"Expected {title!r} NOT to match PR title pattern"
            )
