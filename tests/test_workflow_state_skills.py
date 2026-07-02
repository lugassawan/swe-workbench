"""Content assertions for workflow-state checkpoint instructions (issue #286).

These tests verify that the three wired workflow skills contain the checkpoint-write
instruction and the delete-on-terminal instruction, both referencing docs/workflow-state.md.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

_SKILLS = {
    "workflow-development": ROOT / "skills" / "workflow-development" / "SKILL.md",
    "workflow-bug-triage": ROOT / "skills" / "workflow-bug-triage" / "SKILL.md",
    "workflow-pr-review": ROOT / "skills" / "workflow-pr-review" / "SKILL.md",
}

_DOC_PATH = "docs/workflow-state.md"


@pytest.mark.parametrize("skill_name,skill_path", list(_SKILLS.items()))
class TestCheckpointInstructions:
    """Each wired skill must carry checkpoint-write and delete-on-terminal text."""

    def test_skill_file_exists(self, skill_name, skill_path):
        assert skill_path.exists(), f"{skill_name}: SKILL.md not found at {skill_path}"

    def test_checkpoint_write_instruction_present(self, skill_name, skill_path):
        text = skill_path.read_text(encoding="utf-8")
        assert "workflow-state" in text, (
            f"{skill_name}: missing checkpoint-write instruction referencing 'workflow-state'"
        )

    def test_delete_on_terminal_instruction_present(self, skill_name, skill_path):
        text = skill_path.read_text(encoding="utf-8")
        # The delete instruction uses "delete" or "remove" near "state file" or "checkpoint"
        lower = text.lower()
        has_delete = "delete the" in lower or "remove the" in lower
        has_target = "state file" in lower or "checkpoint" in lower
        assert has_delete and has_target, (
            f"{skill_name}: missing delete-on-terminal instruction for state file/checkpoint"
        )

    def test_doc_reference_present(self, skill_name, skill_path):
        text = skill_path.read_text(encoding="utf-8")
        assert _DOC_PATH in text, (
            f"{skill_name}: missing reference to {_DOC_PATH!r}"
        )


class TestDocPresence:
    """The workflow-state doc must exist and contain required sections."""

    DOC = ROOT / "docs" / "workflow-state.md"

    def test_doc_exists(self):
        assert self.DOC.exists(), f"Missing {self.DOC}"

    def test_doc_has_how_it_works(self):
        text = self.DOC.read_text(encoding="utf-8")
        assert "How it works" in text or "how it works" in text.lower(), (
            "workflow-state.md missing 'How it works' section"
        )

    def test_doc_has_schema(self):
        text = self.DOC.read_text(encoding="utf-8")
        assert '"version"' in text or "version" in text, (
            "workflow-state.md missing schema documentation"
        )

    def test_doc_has_lifecycle(self):
        text = self.DOC.read_text(encoding="utf-8")
        lower = text.lower()
        assert "lifecycle" in lower or "survives" in lower, (
            "workflow-state.md missing lifecycle / what-survives section"
        )

    def test_doc_has_troubleshooting(self):
        text = self.DOC.read_text(encoding="utf-8")
        assert "Troubleshooting" in text or "troubleshooting" in text.lower(), (
            "workflow-state.md missing Troubleshooting section"
        )


class TestReadmeEntries:
    """README.md and docs/README.md must reference workflow state persistence."""

    def test_readme_mentions_workflow_state(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "workflow-state" in readme or "workflow state" in readme.lower(), (
            "README.md missing workflow state persistence section"
        )

    def test_docs_readme_indexes_workflow_state_doc(self):
        docs_readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        assert "workflow-state" in docs_readme, (
            "docs/README.md missing index entry for workflow-state.md"
        )
