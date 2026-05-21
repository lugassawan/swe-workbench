# tests/test_workflow_pr_review_skill.py

"""Tests for the workflow-pr-review skill — base-repo extraction (issue #289)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-pr-review"
SKILL_MD = SKILL_DIR / "SKILL.md"


def test_pr_review_skill_file_exists():
    """skills/workflow-pr-review/SKILL.md must exist with valid frontmatter."""
    assert SKILL_MD.exists(), "skills/workflow-pr-review/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert "name" in fm, "SKILL.md frontmatter must have a name field"
    assert "description" in fm, "SKILL.md frontmatter must have a description field"
    assert fm.get("orchestrator") == "true", (
        "SKILL.md frontmatter must have orchestrator: true"
    )


def test_pr_review_skill_uses_base_repository_in_json_fields():
    """Step 1 gh pr view --json must include baseRepository (not headRepository) for OWNER/REPO."""
    text = SKILL_MD.read_text()
    assert "baseRepository" in text, (
        "SKILL.md Step 1 gh pr view --json field list must include baseRepository "
        "so that $OWNER and $REPO target the base (receiving) repo, not the fork"
    )


def test_pr_review_skill_owner_repo_extracted_via_jq_from_base():
    """OWNER and REPO must be extracted from baseRepository via a jq expression."""
    text = SKILL_MD.read_text()
    assert re.search(r"OWNER\s*=.*\$\(jq[^\n]*baseRepository", text), (
        "SKILL.md must extract OWNER from baseRepository via jq "
        "(e.g. jq -r '.baseRepository.owner.login // ...'), not prose or Python"
    )
    assert re.search(r"REPO\s*=.*\$\(jq[^\n]*baseRepository", text), (
        "SKILL.md must extract REPO from baseRepository via jq "
        "(e.g. jq -r '.baseRepository.name // ...'), not prose or Python"
    )


def test_pr_review_skill_no_fragile_owner_extraction():
    """SKILL.md must not contain fragile Python-dict or headRepository-owner extraction patterns."""
    text = SKILL_MD.read_text()
    assert "['owner']['login']" not in text, (
        "SKILL.md must not contain Python-dict extraction ['owner']['login'] — "
        "this pattern threw KeyError on fork PRs where headRepository lacks an owner key"
    )
    assert not re.search(r"headRepository[^`\n]*owner[^`\n]*login", text), (
        "SKILL.md must not reference headRepository.owner.login — "
        "use baseRepository.owner.login instead"
    )


def test_pr_review_skill_has_owner_repo_guard_clause():
    """SKILL.md must include a guard clause that exits if OWNER or REPO cannot be determined."""
    text = SKILL_MD.read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "SKILL.md must include the guard-clause error message for missing OWNER/REPO "
        "so fork-PR failures produce an actionable error rather than silently misrouting API calls"
    )
