"""Structural tests: documented rimba invocations match the v1.9.x CLI."""
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOC_DIRS = [ROOT / "skills", ROOT / "commands"]
WORKFLOW_DEV = ROOT / "skills" / "workflow-development" / "SKILL.md"


def test_rimba_add_task_flag_requires_pr_mode():
    """`rimba add --task` is only valid in pr:<num> mode (rimba v1.9.x)."""
    offenders = []
    for d in DOC_DIRS:
        for path in d.rglob("*.md"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "rimba add" in line and "--task" in line and "pr:" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not offenders, "rimba add --task used outside pr: mode:\n" + "\n".join(offenders)


def test_workflow_development_documents_all_add_modes():
    """workflow-development must document task, pr:, and branch: add modes."""
    text = WORKFLOW_DEV.read_text(encoding="utf-8")
    for token in ("rimba add", "pr:", "branch:"):
        assert token in text, f"workflow-development SKILL.md must document `{token}` add mode"
