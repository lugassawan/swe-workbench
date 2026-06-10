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
