# tests/test_workflow_address_feedback_skill.py

"""Tests for the workflow-address-feedback skill (closes #218)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-address-feedback"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS_TXT = SKILL_DIR / "triggers.txt"


def test_address_feedback_skill_file_exists():
    """skills/workflow-address-feedback/SKILL.md must exist with valid frontmatter."""
    assert SKILL_MD.exists(), "skills/workflow-address-feedback/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert "name" in fm, "SKILL.md frontmatter must have a name field"
    assert "description" in fm, "SKILL.md frontmatter must have a description field"
    assert fm.get("orchestrator") == "true", (
        "SKILL.md frontmatter must have orchestrator: true"
    )


def test_address_feedback_triggers_txt():
    """triggers.txt must exist and have at least 2 non-comment, non-blank lines."""
    assert TRIGGERS_TXT.exists(), "skills/workflow-address-feedback/triggers.txt must exist"
    lines = [
        ln.strip()
        for ln in TRIGGERS_TXT.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2, (
        f"triggers.txt must have at least 2 non-comment lines, got {len(lines)}: {lines}"
    )


def test_address_feedback_skill_references_reply_rest_endpoint():
    """SKILL.md must reference the per-thread reply REST endpoint for inline replies."""
    text = SKILL_MD.read_text()
    assert re.search(r"pulls/.*comments/.*replies", text), (
        "SKILL.md must reference the REST reply endpoint pattern: "
        "pulls/{N}/comments/{id}/replies"
    )


def test_address_feedback_skill_references_resolve_mutation():
    """SKILL.md must reference the resolveReviewThread GraphQL mutation."""
    text = SKILL_MD.read_text()
    assert "resolveReviewThread" in text, (
        "SKILL.md must reference the resolveReviewThread GraphQL mutation"
    )


def test_address_feedback_skill_uses_three_way_triage():
    """SKILL.md must define the ADDRESSED / CLARIFIED / DEFERRED three-way triage."""
    text = SKILL_MD.read_text()
    assert "ADDRESSED" in text, "SKILL.md must reference ADDRESSED triage state"
    assert "CLARIFIED" in text, "SKILL.md must reference CLARIFIED triage state"
    assert "DEFERRED" in text, "SKILL.md must reference DEFERRED triage state"


def test_address_feedback_skill_owner_repo_from_gh_repo_view():
    """OWNER and REPO must be derived from 'gh repo view' (not from headRepository or baseRepository)."""
    text = SKILL_MD.read_text()
    assert re.search(r"OWNER\s*=.*\$\(gh repo view[^\n]*owner", text), (
        "SKILL.md must derive OWNER via 'gh repo view --json owner' — "
        "gh pr view --json has no baseRepository field; gh repo view resolves the base remote correctly"
    )
    assert re.search(r"REPO\s*=.*\$\(gh repo view[^\n]*name", text), (
        "SKILL.md must derive REPO via 'gh repo view --json name' — "
        "gh pr view --json has no baseRepository field; gh repo view resolves the base remote correctly"
    )


def test_address_feedback_skill_no_invalid_json_field():
    """Phase 1 gh pr view --json must NOT include baseRepository (it is not a valid gh CLI field)."""
    text = SKILL_MD.read_text()
    assert not re.search(r"gh pr view[^\n]*--json[^\n]*baseRepository", text), (
        "SKILL.md must not use baseRepository in gh pr view --json — "
        "that field is unsupported and causes gh to exit with 'Unknown JSON field'"
    )


def test_address_feedback_skill_no_fragile_owner_extraction():
    """SKILL.md must not contain fragile Python-dict or headRepository-owner extraction patterns."""
    text = SKILL_MD.read_text()
    assert "['owner']['login']" not in text, (
        "SKILL.md must not contain Python-dict extraction ['owner']['login'] — "
        "this pattern threw KeyError on fork PRs where headRepository lacks an owner key"
    )
    assert not re.search(r"headRepository[^`\n]*owner[^`\n]*login", text), (
        "SKILL.md must not derive OWNER from headRepository.owner.login — "
        "use gh repo view instead"
    )


def test_address_feedback_skill_has_owner_repo_guard_clause():
    """SKILL.md must include a guard clause that exits if OWNER or REPO cannot be determined."""
    text = SKILL_MD.read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "SKILL.md must include the guard-clause error message for missing OWNER/REPO "
        "so failures produce an actionable error rather than silently misrouting API calls"
    )


def test_address_feedback_skill_no_literal_pr_branch_placeholder():
    """Phase 2 rimba code block must not contain the literal <pr-branch> placeholder."""
    text = SKILL_MD.read_text()
    assert "<pr-branch>" not in text, (
        "SKILL.md Phase 2 rimba code block must use $PR_BRANCH (extracted via jq), "
        "not the literal <pr-branch> placeholder"
    )


def test_address_feedback_skill_captures_fix_sha():
    """Phase 4 must specify a git rev-parse step to capture $FIX_SHA after workflow-commit-and-pr."""
    text = SKILL_MD.read_text()
    assert "rev-parse HEAD" in text, (
        "SKILL.md Phase 4 must capture $FIX_SHA via 'git ... rev-parse HEAD' after "
        "workflow-commit-and-pr returns, so the ADDRESSED reply template is populated"
    )


def test_address_feedback_skill_binds_comment_databaseid():
    """Phase 5 must specify that COMMENT_DATABASEID comes from comments.nodes[0] (thread root)."""
    text = SKILL_MD.read_text()
    assert "nodes[0]" in text or "thread root" in text or "first comment" in text, (
        "SKILL.md Phase 5 must specify that $COMMENT_DATABASEID is populated from "
        "comments.nodes[0].databaseId (the thread root), not a subsequent reply"
    )


def test_address_feedback_skill_clarified_no_resolve():
    """SKILL.md must state that CLARIFIED threads are not resolved (reply only)."""
    text = SKILL_MD.read_text()
    assert re.search(r"CLARIFIED.*[Nn]o resolve|[Nn]o resolve.*CLARIFIED|CLARIFIED.*reply only", text), (
        "SKILL.md must state that CLARIFIED threads get a reply but are NOT resolved "
        "(only ADDRESSED threads trigger resolveReviewThread)"
    )
