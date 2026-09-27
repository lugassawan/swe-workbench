from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def test_alignment_flag_is_documented():
    skill_content = (ROOT / "skills/workflow-branch-sync/SKILL.md").read_text()
    assert "CHECK_ALIGNMENT=on|off" in skill_content
    assert "Step 7 — Alignment Assessment (opt-in, flag-gated)" in skill_content

def test_alignment_captures_history_and_dispatches_subagent():
    skill_content = (ROOT / "skills/workflow-branch-sync/SKILL.md").read_text()
    assert "MAIN_HISTORY=\"$(git log -n 100 --no-merges --stat \"$MERGE_BASE..origin/$DEFAULT_BRANCH\")\"" in skill_content
    assert "BRANCH_DIFF=\"$(git diff \"$MERGE_BASE..$PRE_SYNC_HEAD\")\"" in skill_content
    assert "swe-workbench:alignment-assessor" in skill_content
