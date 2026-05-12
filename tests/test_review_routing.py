"""Structural tests for /review mode-routing (issue #172)."""
import re
from pathlib import Path


REVIEW_PATH = Path(__file__).parent.parent / "commands" / "review.md"
SECURITY_REVIEW_PATH = Path(__file__).parent.parent / "commands" / "security-review.md"


class TestReviewModeRouting:
    """Assert /review.md documents every routing rule from issue #172."""

    def test_argument_hint_advertises_mode(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match
        assert "--mode" in match.group(1)

    def test_all_five_modes_present(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for mode in ("general", "security", "accessibility", "dependency", "performance"):
            assert mode in text, f"--mode {mode} must be documented"

    def test_short_aliases_present(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for alias in ("a11y", "deps", "perf", "sec"):
            assert alias in text, f"alias '{alias}' must be documented"

    def test_all_five_auditors_referenced(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for agent in ("reviewer", "security-auditor", "accessibility-auditor",
                      "dependency-auditor", "performance-tuner"):
            assert agent in text, f"auditor '{agent}' must be referenced"

    def test_auto_inference_output_format(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        assert "Inferred mode:" in text
        assert "reason:" in text

    def test_explicit_mode_output_format(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        assert "(explicit)" in text

    def test_inference_rules_documented(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        # Manifest files for dependency mode
        for token in ("package.json", "Cargo.toml", "go.mod", "pyproject.toml"):
            assert token in text, f"{token} must appear in dependency-mode rules"
        # Frontend surfaces for a11y mode
        for token in ("jsx", "tsx", "aria-"):
            assert token in text
        # git diff --name-only must be used to drive inference
        assert "git diff --name-only" in text

    def test_inference_precedence_documented(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        # Locate each rule's bold header to assert precedence ordering is preserved
        indices = {
            name: text.find(f"**{name}**")
            for name in ("dependency", "security", "accessibility", "performance", "general")
        }
        assert all(v != -1 for v in indices.values()), \
            f"Missing bold rule header(s): {[k for k, v in indices.items() if v == -1]}"
        ordered = ["dependency", "security", "accessibility", "performance", "general"]
        for a, b in zip(ordered, ordered[1:]):
            assert indices[a] < indices[b], \
                f"Inference rule '{a}' must precede '{b}' in the document"

    def test_pr_mode_caveat_documented(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        lower = text.lower()
        # Must assert both that inline-comment posting is mentioned AND that it is skipped
        assert "inline-comment posting" in lower and "skipped" in lower, \
            "PR-mode + --mode must document that inline-comment posting is skipped"

    def test_existing_pr_mode_preserved(self):
        """Backward-compat: bare integer arg → PR mode still works."""
        text = REVIEW_PATH.read_text(encoding="utf-8")
        assert "[1-9][0-9]*" in text, "integer-arg PR-mode regex must survive"
        assert "swe-workbench:workflow-pr-review" in text


class TestSecurityReviewIsStub:
    """Assert /security-review.md is a thin alias for /review --mode security."""

    def test_delegates_to_review(self):
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        assert "/review --mode security" in text or "review --mode security" in text

    def test_does_not_invoke_security_auditor_directly(self):
        """Prevents stub from silently re-growing the dispatch logic."""
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        # The agent name must not appear — delegation lives in /review
        assert "security-auditor" not in text, \
            "security-review.md must not reference security-auditor directly; " \
            "delegation now lives in /review"

    def test_frontmatter_preserved(self):
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match
        assert "description:" in match.group(1)
