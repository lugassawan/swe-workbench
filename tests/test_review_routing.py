"""Structural tests for /review mode-routing (issue #172)."""
import re
from pathlib import Path
import pytest


REVIEW_PATH = Path(__file__).parent.parent / "commands" / "review.md"
SECURITY_REVIEW_PATH = Path(__file__).parent.parent / "commands" / "security-review.md"
COMMANDS_DIR = Path(__file__).parent.parent / "commands"
AGENTS_DIR = Path(__file__).parent.parent / "agents"


class TestReviewModeRouting:
    """Assert /review.md documents every routing rule from issue #172."""

    def test_argument_hint_advertises_mode(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match
        assert "--mode" in match.group(1)

    def test_all_modes_present(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for mode in ("general", "security", "accessibility", "dependency", "performance", "tests"):
            assert mode in text, f"--mode {mode} must be documented"

    def test_short_aliases_present(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for alias in ("a11y", "deps", "perf", "sec"):
            assert alias in text, f"alias '{alias}' must be documented"

    def test_all_auditors_referenced(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for agent in ("reviewer", "security-auditor", "accessibility-auditor",
                      "dependency-auditor", "performance-tuner", "test-reviewer"):
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


class TestSecurityReviewCommand:
    """Assert /security-review.md delegates directly to the security-auditor agent.

    The command is no longer a stub alias for /review --mode security. Slash
    commands cannot chain slash commands — the harness does not expand inner
    slash references. The command now handles diff resolution itself and
    delegates to the security-auditor subagent directly (issue #234).
    """

    def test_delegates_to_security_auditor(self):
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        assert "security-auditor" in text, \
            "security-review.md must delegate to the security-auditor subagent directly"

    def test_does_not_chain_slash_command(self):
        """Slash-command chaining silently no-ops in the Claude Code harness."""
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        assert "Delegate to `/review" not in text and "delegate to `/review" not in text, \
            "security-review.md must not chain /review — slash commands cannot chain slash commands"

    def test_pr_number_arg_documented(self):
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        assert "PR number" in text or "PR diff" in text or "gh pr diff" in text, \
            "security-review.md must document PR-number argument support"

    def test_output_stanza_present(self):
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        assert "## Output" in text, "security-review.md must have an ## Output stanza"

    def test_frontmatter_preserved(self):
        text = SECURITY_REVIEW_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match
        assert "description:" in match.group(1)


class TestCommandOutputStanzas:
    """Assert every short command documented in issue #234 has an ## Output stanza."""

    @pytest.mark.parametrize("cmd", [
        "security-review.md",
        "cleanup-merged.md",
        "audit-codebase.md",
    ])
    def test_short_command_has_output_stanza(self, cmd):
        text = (COMMANDS_DIR / cmd).read_text(encoding="utf-8")
        assert "## Output" in text, f"{cmd} must have an ## Output stanza"


class TestAgentReachableVia:
    """Assert every agent file declares its entry-point via **Reachable via:** annotation."""

    def test_all_agents_have_reachable_via(self):
        for agent_file in sorted(AGENTS_DIR.glob("*.md")):
            text = agent_file.read_text(encoding="utf-8")
            assert "**Reachable via:**" in text, \
                f"{agent_file.name} must have a '**Reachable via:**' annotation"
