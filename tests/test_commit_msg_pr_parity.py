"""Parity guard: the commit-msg hook and PR-title CI check must use the same regex."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _extract_pattern(path: Path) -> str:
    matches = re.findall(r"PATTERN='([^']+)'", path.read_text())  # single-quoted shell assignment
    assert len(matches) == 1, (
        f"Expected exactly one PATTERN='...' assignment in {path}, found {len(matches)}"
    )
    return matches[0]


class TestCommitMsgPrParity:
    def test_hook_and_ci_patterns_match(self):
        """Assert structural parity only — pattern correctness is out of scope here.
        Add behavioral tests in test_pr_validation.py if the pattern semantics change."""
        hook = _extract_pattern(REPO / ".githooks/commit-msg")
        ci = _extract_pattern(REPO / ".github/workflows/pr.yml")
        assert hook == ci, (
            f"commit-msg hook and pr.yml regexes have drifted.\n"
            f"  hook ({len(hook)} chars): {hook}\n"
            f"  ci   ({len(ci)} chars): {ci}"
        )
