"""Behavioural guards for skills/workflow-worktree-session/SKILL.md.

Tests assert that:
1. Mode A trigger list covers resume/continue cues so the skill fires even
   when the user never says the word "worktree" explicitly (e.g. "I've been
   cd-ing into the worktree", "continue work in the worktree I made").
2. The Forbidden-pattern section names EnterWorktree as the active remedy —
   not just a prohibition — so a session that has already been cd-prefixing
   commands gets a concrete next action.
"""

from pathlib import Path

SKILL = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-worktree-session"
    / "SKILL.md"
)


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Mode A trigger breadth
# ---------------------------------------------------------------------------

class TestModeATriggers:
    """Mode A must advertise resume/continue cues, not only explicit 'worktree' words."""

    def test_skill_file_exists(self):
        assert SKILL.exists(), f"Missing skill file: {SKILL}"

    def test_triggers_mention_resume(self):
        text = _text()
        assert "resume" in text.lower(), (
            "Mode A triggers must include a 'resume' cue so the skill fires "
            "when a user wants to re-enter an existing worktree after compaction."
        )

    def test_triggers_mention_continue(self):
        text = _text()
        assert "continue" in text.lower(), (
            "Mode A triggers must include a 'continue' cue so the skill fires "
            "for prompts like 'continue work in the worktree I made'."
        )

    def test_triggers_mention_cd_prefix_cue(self):
        """Skill must acknowledge the cd-prefix symptom as a Mode A trigger signal."""
        text = _text()
        assert "cd" in text and ("cd-ing" in text or "cd-prefix" in text or "been cd" in text or
                                  "been using cd" in text or "prefixing" in text), (
            "Mode A triggers must call out the 'I've been cd-ing / cd-prefixing' "
            "pattern as a cue that the skill should activate."
        )


# ---------------------------------------------------------------------------
# Forbidden-pattern active remedy
# ---------------------------------------------------------------------------

class TestForbiddenPatternRemedy:
    """The Forbidden-pattern section must name EnterWorktree as the active fix."""

    def test_forbidden_pattern_section_exists(self):
        text = _text()
        assert "Forbidden" in text or "forbidden" in text, (
            "SKILL.md must contain a 'Forbidden pattern' section."
        )

    def test_forbidden_pattern_names_enter_worktree_remedy(self):
        text = _text()
        # The remedy must appear in proximity to the forbidden-pattern discussion.
        # We assert that EnterWorktree is mentioned as the corrective action.
        assert "EnterWorktree" in text, (
            "Forbidden-pattern section must name EnterWorktree as the active remedy, "
            "not just prohibit cd."
        )

    def test_forbidden_pattern_active_remedy_present(self):
        """The section must tell the reader WHAT TO DO, not just what not to do."""
        text = _text()
        # The remedy should tell the user to call EnterWorktree now/stop
        remedy_phrases = [
            "stop and call",
            "call EnterWorktree",
            "signal",
            "re-anchor",
        ]
        assert any(p in text for p in remedy_phrases), (
            "Forbidden-pattern section must include an active remedy instruction "
            f"(one of: {remedy_phrases!r}). Currently it only prohibits cd without "
            "telling the reader what to do when they've already been cd-prefixing."
        )

    def test_forbidden_pattern_mentions_lock_contract(self):
        """Remedy must explain WHY — the ExitWorktree lock contract bypass."""
        text = _text()
        assert "lock" in text or "ExitWorktree" in text, (
            "Forbidden-pattern section must mention the ExitWorktree lock contract "
            "so the reader understands the consequence of the cd-prefix pattern."
        )


# ---------------------------------------------------------------------------
# Switch-between-worktrees remedy
# ---------------------------------------------------------------------------

class TestSwitchBetweenWorktreesRemedy:
    """Switching from worktree A to B must prescribe ExitWorktree(keep)+retry,
    not a bare cd, when EnterWorktree is rejected because the session is already
    inside a different worktree."""

    def test_exit_then_retry_is_primary_remedy(self):
        text = _text()
        assert "ExitWorktree(action=keep)" in text or 'ExitWorktree(action: "keep")' in text

    def test_retry_enter_worktree_after_exit(self):
        text = _text()
        # scope assertion to the switch remedy paragraph, not the entire file
        switch_section = text[text.find("different worktree"):text.find("Do not auto-exit")]
        assert "retry" in switch_section.lower() and "EnterWorktree" in switch_section

    def test_cd_demoted_to_last_resort(self):
        assert "last resort" in _text().lower()

    def test_already_inside_different_worktree_named(self):
        assert "different worktree" in _text().lower()


# ---------------------------------------------------------------------------
# No-op ambiguity diagnostic (#497)
# ---------------------------------------------------------------------------

class TestNoOpAmbiguityDiagnostic:
    """Mode C must not assert an ExitWorktree no-op as definitive proof of cd-entry.

    A no-op means only "no active EnterWorktree session" — caused by either
    cd-entry OR compaction dropping harness-level EnterWorktree tracking, and the
    two present identically from ExitWorktree's output alone. Mode C must instruct
    an active probe (--git-dir vs --git-common-dir, plus a fresh sidecar's
    worktree_root) before diagnosing which cause applies.
    """

    @staticmethod
    def _mode_c_slice() -> str:
        text = _text()
        start = text.find("### Mode C")
        end = text.find("## Forbidden pattern")
        assert start != -1, "SKILL.md must contain a '### Mode C' section"
        assert end != -1, "SKILL.md must contain a '## Forbidden pattern' section"
        return text[start:end]

    def test_no_op_not_asserted_as_definitive_cd_entry(self):
        mode_c = self._mode_c_slice()
        assert "(confirms cd-entry)" not in mode_c and "(confirms `cd`-entry)" not in mode_c, (
            "Mode C must not assert an ExitWorktree no-op as definitive proof of "
            "cd-entry — compaction-dropped tracking presents identically."
        )

    def test_compaction_named_as_alternative_cause(self):
        mode_c = self._mode_c_slice()
        assert "compaction" in mode_c.lower(), (
            "Mode C must name compaction as an alternative cause of an ExitWorktree no-op."
        )

    def test_probe_instruction_present(self):
        mode_c = self._mode_c_slice()
        assert "--git-dir" in mode_c and "--git-common-dir" in mode_c, (
            "Mode C must instruct probing `git rev-parse --git-dir --git-common-dir` "
            "to determine whether cwd is a linked worktree."
        )

    def test_worktree_root_evidence_referenced(self):
        mode_c = self._mode_c_slice()
        assert "worktree_root" in mode_c, (
            "Mode C must reference the sidecar's context.worktree_root as "
            "corroborating evidence for diagnosing compaction-dropped tracking."
        )

    def test_likely_lost_to_compaction_framing_present(self):
        mode_c = self._mode_c_slice()
        assert "lost to compaction" in mode_c.lower(), (
            "Mode C must state the diagnostic conclusion 'tracking likely lost to "
            "compaction, not cd-entry' when probe evidence supports it."
        )

    def test_recovery_snippet_unchanged(self):
        """Recovery command must still work for both causes, unchanged."""
        mode_c = self._mode_c_slice()
        assert "_GCD=$(git rev-parse --git-common-dir)" in mode_c
        assert 'cd "${_GCD%/.git}"' in mode_c

    def test_quick_reference_row_no_longer_asserts_cd_entry_certainty(self):
        text = _text()
        assert "## Quick reference" in text, "SKILL.md must contain a Quick reference section"
        quick_ref = text.split("## Quick reference")[1]
        assert "confirms cd-entry" not in quick_ref and "confirms `cd`-entry" not in quick_ref, (
            "Quick reference row for Mode C must not assert cd-entry certainty either."
        )
