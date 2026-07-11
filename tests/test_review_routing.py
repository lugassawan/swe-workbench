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
        for mode in ("general", "security", "accessibility", "dependency", "performance", "tests",
                     "contributor-trust", "ux"):
            assert mode in text, f"--mode {mode} must be documented"

    def test_short_aliases_present(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for alias in ("a11y", "deps", "perf", "sec", "trust"):
            assert alias in text, f"alias '{alias}' must be documented"

    def test_all_auditors_referenced(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        for agent in ("reviewer", "security-auditor", "accessibility-auditor",
                      "dependency-auditor", "performance-tuner", "test-reviewer",
                      "contributor-auditor", "product-designer"):
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

    def test_pr_mode_specialist_post_subflow_documented(self):
        """Since #499, postable specialist modes offer to post via workflow-pr-review-post
        (behind a confirmation gate) instead of always skipping inline-comment posting."""
        text = REVIEW_PATH.read_text(encoding="utf-8")
        lower = text.lower()
        assert "postable" in lower, \
            "PR-mode + --mode must document which specialist modes are postable"
        assert "reply `post`" in lower, \
            "PR-mode + --mode must document the post/skip confirmation prompt"
        assert "swe-workbench:workflow-pr-review-post" in text, \
            "PR-mode + --mode specialist sub-flow must invoke swe-workbench:workflow-pr-review-post"

    def test_contributor_trust_signal_only_documented(self):
        """contributor-trust stays advisory-only — its own branch must state this,
        distinct from the postable specialist set."""
        text = REVIEW_PATH.read_text(encoding="utf-8")
        trust_idx = text.find("`--mode contributor-trust`")
        assert trust_idx != -1, "PR-mode contributor-trust branch not found"
        paragraph_end = text.find("\n\n", trust_idx)
        paragraph = text[trust_idx:paragraph_end if paragraph_end != -1 else None]
        assert "advisory" in paragraph.lower(), (
            "the contributor-trust paragraph itself must document its advisory-only, "
            "never-post contract"
        )
        assert "sub-flow below entirely" in paragraph or "skips the sub-flow" in paragraph, (
            "the contributor-trust paragraph must state it skips the postable sub-flow entirely"
        )

    def test_ux_in_postable_specialist_set(self):
        """ux must be enumerated in the postable specialist set (not just the mode table)."""
        text = REVIEW_PATH.read_text(encoding="utf-8")
        postable_idx = text.find("postable specialist value")
        assert postable_idx != -1, "postable specialist set sentence not found"
        # ux must appear in the same sentence/line as the postable set enumeration
        line_end = text.find("\n", postable_idx)
        assert "ux" in text[postable_idx:line_end], \
            "ux must be enumerated in the postable specialist set"

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


class TestContributorTrustMode:
    """Assert /review.md and agents/contributor-auditor.md satisfy issue #243 requirements."""

    CONTRIBUTOR_AUDITOR_PATH = AGENTS_DIR / "contributor-auditor.md"

    def test_contributor_trust_in_routing_table(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        assert "contributor-trust" in text, \
            "commands/review.md routing table must include contributor-trust mode"

    def test_trust_alias_in_routing_table(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        assert "`trust`" in text, \
            "commands/review.md must document 'trust' as a backtick-formatted alias in the routing table"

    def test_contributor_auditor_agent_referenced(self):
        text = REVIEW_PATH.read_text(encoding="utf-8")
        assert "contributor-auditor" in text, \
            "commands/review.md must reference the contributor-auditor agent"

    def test_contributor_trust_not_in_auto_inference(self):
        """contributor-trust is explicit-only — same posture as tests mode.

        The auto-inference numbered rules (1-5) must not include contributor-trust.
        It may appear in the explanatory note that follows the rules.
        """
        text = REVIEW_PATH.read_text(encoding="utf-8")
        rules_start = text.find("Apply these inference rules")
        rules_end = text.find("> **Note:**")
        assert rules_start != -1, "inference rules block not found"
        assert rules_end != -1, "> **Note:** block not found"
        inference_rules = text[rules_start:rules_end]
        assert "contributor-trust" not in inference_rules, \
            "contributor-trust must not appear in the numbered auto-inference rules (explicit-only mode)"

    def test_contributor_auditor_agent_file_exists(self):
        assert self.CONTRIBUTOR_AUDITOR_PATH.exists(), \
            "agents/contributor-auditor.md must exist"

    @pytest.mark.parametrize("field,value", [
        ("name", "contributor-auditor"),
        ("model", "sonnet"),
    ])
    def test_contributor_auditor_frontmatter(self, field, value):
        text = self.CONTRIBUTOR_AUDITOR_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "agents/contributor-auditor.md must have frontmatter"
        assert f"{field}: {value}" in match.group(1), \
            f"frontmatter must contain '{field}: {value}'"

    def test_contributor_auditor_reachable_via(self):
        text = self.CONTRIBUTOR_AUDITOR_PATH.read_text(encoding="utf-8")
        assert "**Reachable via:**" in text, \
            "contributor-auditor.md must declare **Reachable via:**"
        assert "contributor-trust" in text, \
            "contributor-auditor.md Reachable via must reference --mode contributor-trust"

    def test_contributor_auditor_four_lenses(self):
        text = self.CONTRIBUTOR_AUDITOR_PATH.read_text(encoding="utf-8")
        for lens in ("Author signal", "Diff signal", "Repo posture", "Pattern risk"):
            assert lens in text, \
                f"contributor-auditor.md must document the '{lens}' lens"

    def test_contributor_auditor_merge_confidence_footer(self):
        text = self.CONTRIBUTOR_AUDITOR_PATH.read_text(encoding="utf-8")
        assert "Merge confidence" in text, \
            "contributor-auditor.md must describe the Merge confidence footer"

    def test_contributor_auditor_read_only_enforcement(self):
        text = self.CONTRIBUTOR_AUDITOR_PATH.read_text(encoding="utf-8")
        assert "Read-only" in text or "read-only" in text, \
            "contributor-auditor.md must have a read-only enforcement section"

    def test_contributor_auditor_advisory_only(self):
        text = self.CONTRIBUTOR_AUDITOR_PATH.read_text(encoding="utf-8")
        lower = text.lower()
        assert "no comment" in lower or "advisory" in lower or "never post" in lower or \
               "does not post" in lower or "never comments" in lower, \
            "contributor-auditor.md must state it never posts to the PR"


class TestAgentReachableVia:
    """Assert every agent file declares its entry-point via **Reachable via:** annotation."""

    def test_all_agents_have_reachable_via(self):
        for agent_file in sorted(AGENTS_DIR.glob("*.md")):
            text = agent_file.read_text(encoding="utf-8")
            assert "**Reachable via:**" in text, \
                f"{agent_file.name} must have a '**Reachable via:**' annotation"
