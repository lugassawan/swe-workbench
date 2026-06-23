"""Behavioural guards for skills/workflow-development/templates/plan-workflow-section.md.

Tests assert that:
1. The template no longer offers 'cd <path>' as an equivalent mechanism to
   'enter' the worktree (removing the false equivalence that normalised the
   cd-prefix anti-pattern).
2. The template includes a re-anchor/resume note so a continued session knows
   to call EnterWorktree before running commands.
3. The template header carries a 'do not abridge' instruction so the mandate
   travels with the template itself (#455).
"""

from pathlib import Path

TEMPLATE = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-development"
    / "templates"
    / "plan-workflow-section.md"
)


def _text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# No cd-as-enter equivalence
# ---------------------------------------------------------------------------

class TestNoCdEquivalence:
    """Template must not present cd as an equivalent to EnterWorktree."""

    def test_template_exists(self):
        assert TEMPLATE.exists(), f"Missing template: {TEMPLATE}"

    def test_no_cd_as_enter_alternative(self):
        """'or cd <path> in shell' (or similar) must be absent."""
        text = _text()
        bad_phrases = [
            "or `cd <path>` in shell",
            "or cd <path> in shell",
            "or `cd` in shell",
            "`cd <path>` in shell",
        ]
        for phrase in bad_phrases:
            assert phrase not in text, (
                f"Template must not offer 'cd' as an equivalent enter mechanism. "
                f"Found: {phrase!r}. Remove it and replace with a note that cd "
                f"only affects a single Bash subprocess."
            )

    def test_enter_worktree_is_the_session_switch(self):
        """Template must name EnterWorktree as the session switch mechanism."""
        text = _text()
        assert "EnterWorktree" in text, (
            "Template must name EnterWorktree as the session-switch mechanism "
            "in the Enter worktree step."
        )

    def test_cd_does_not_move_session_note_present(self):
        """Template must clarify that cd does NOT move the session."""
        text = _text()
        negative_cd_phrases = [
            "cd does not move",
            "cd only affects",
            "does not move the session",
            "cd` does not",
            "`cd` only",
        ]
        assert any(p in text for p in negative_cd_phrases), (
            "Template must explicitly state that cd does not move the session "
            "(it only affects a single Bash subprocess). This prevents the "
            "cd-prefix anti-pattern from being re-introduced by future plan authors."
        )


# ---------------------------------------------------------------------------
# Re-anchor / resume note
# ---------------------------------------------------------------------------

class TestReanchorNote:
    """Template must include a resume re-anchor note in Phase 1."""

    def test_resume_reanchor_note_present(self):
        """Phase 1 must tell the executor to EnterWorktree on resumed sessions."""
        text = _text()
        reanchor_phrases = [
            "resume",
            "re-anchor",
            "reanchor",
            "resumed session",
            "continued session",
            "EnterWorktree path",
        ]
        assert any(p.lower() in text.lower() for p in reanchor_phrases), (
            "Template Phase 1 must include a resume/re-anchor note so that a "
            "continued or resumed session knows to call EnterWorktree(path=…) "
            "before running commands."
        )

    def test_cd_prefix_signal_mentioned(self):
        """Template must name cd-prefixing as the signal to re-anchor."""
        text = _text()
        signal_phrases = [
            "cd-prefix",
            "cd-prefixing",
            "signal",
            "catch yourself cd",
        ]
        assert any(p in text for p in signal_phrases), (
            "Template must state that catching yourself cd-prefixing is the signal "
            "to stop and call EnterWorktree(path=…)."
        )


# ---------------------------------------------------------------------------
# Full-fidelity header mandate (#455)
# ---------------------------------------------------------------------------

class TestFullFidelityHeader:
    """Template header must instruct the orchestrator not to abridge."""

    def test_header_no_abridge_phrase(self):
        """Header region must carry 'do not abridge' before the fenced markdown block."""
        text = _text()
        # Slice header: everything before the first ````markdown fence
        fence_idx = text.find("````markdown")
        header = text[:fence_idx] if fence_idx >= 0 else text
        assert "do not abridge" in header, (
            "Template header must carry 'do not abridge' so the no-summarize "
            "instruction travels with the template itself (#455)."
        )


# ---------------------------------------------------------------------------
# Switch-between-worktrees remedy in template
# ---------------------------------------------------------------------------

class TestSwitchRemedyInTemplate:
    """Template Enter-worktree bullet must prescribe ExitWorktree+retry as primary
    and demote cd to a last resort."""

    def test_exit_worktree_retry_remedy_present(self):
        assert "ExitWorktree" in _text()

    def test_cd_is_last_resort(self):
        assert "last resort" in _text().lower()
