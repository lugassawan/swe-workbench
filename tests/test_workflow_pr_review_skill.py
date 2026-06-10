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


def test_pr_review_skill_owner_repo_from_gh_repo_view():
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


def test_pr_review_skill_no_invalid_json_field():
    """Step 1 gh pr view --json must NOT include baseRepository (it is not a valid gh CLI field)."""
    text = SKILL_MD.read_text()
    assert not re.search(r"gh pr view[^\n]*--json[^\n]*baseRepository", text), (
        "SKILL.md must not use baseRepository in gh pr view --json — "
        "that field is unsupported and causes gh to exit with 'Unknown JSON field'"
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
        "use gh repo view instead"
    )


def test_pr_review_skill_has_owner_repo_guard_clause():
    """SKILL.md must include a guard clause that exits if OWNER or REPO cannot be determined."""
    text = SKILL_MD.read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "SKILL.md must include the guard-clause error message for missing OWNER/REPO "
        "so failures produce an actionable error rather than silently misrouting API calls"
    )


# --- Cleanup call-site assertions (guard bypass fix) ---

def test_pr_review_skill_cleanup_uses_clean_ephemeral_script():
    """Step 7 background cleanup and pre-flight stale removal must use clean-ephemeral.sh, not bare rm -rf."""
    text = SKILL_MD.read_text()
    assert "clean-ephemeral.sh" in text, (
        "SKILL.md cleanup blocks must invoke scripts/clean-ephemeral.sh — "
        "bare 'rm -rf $WT' under /Users/... is blocked by the bash guard (exit 2)"
    )


def test_pr_review_skill_no_bare_rm_rf_wt():
    """SKILL.md must not contain a bare 'rm -rf \"$WT\"' that the bash guard would block."""
    text = SKILL_MD.read_text()
    assert not re.search(r'rm\s+-[rR][fF]\s+"?\$WT"?(?!\s*2>)', text) or \
           not re.search(r'rm\s+-[rR][fF]\s+"?\$WT"?\s*(?:2>/dev/null\s*)?(?:;|\))', text), (
        "SKILL.md must not use 'rm -rf \"$WT\"' directly — "
        "route through clean-ephemeral.sh to avoid the bash guard blocking home-tree paths"
    )
    # Stricter: no standalone rm -rf "$WT" outside of clean-ephemeral.sh invocations
    lines_with_rm = [
        line for line in text.splitlines()
        if re.search(r'rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF]', line)
        and '"$WT"' in line
        and "clean-ephemeral" not in line
    ]
    assert not lines_with_rm, (
        f"Found bare rm -rf \"$WT\" lines (should use clean-ephemeral.sh):\n"
        + "\n".join(lines_with_rm)
    )


# --- State-file cleanup assertions (issue #428) ---

def test_pr_review_skill_cleanup_deletes_pr_json():
    """Step 7 success-path subshell must invoke clean-state-files.sh with the PR state files."""
    text = SKILL_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "SKILL.md Step 7 must call scripts/clean-state-files.sh to remove per-run state files"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}.json to clean-state-files.sh"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}-threads.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}-threads.json to clean-state-files.sh"
    )


def test_pr_review_skill_state_cleanup_inside_background_subshell():
    """clean-state-files.sh must appear inside the background ( ... ) & subshell (success-path only)."""
    text = SKILL_MD.read_text()
    # The subshell is opened with '(' and closed with ') &' — find it
    subshell_match = re.search(r'\(\s*bash.*?clean-state-files\.sh.*?\)\s*&', text, re.DOTALL)
    assert subshell_match, (
        "SKILL.md Step 7 clean-state-files.sh call must be inside the background ( ... ) & subshell"
    )


def test_pr_review_skill_state_cleanup_has_or_true_guard():
    """clean-state-files.sh call must be followed by || true so set -e in the subshell cannot
    abort rimba remove when the state files are already absent or fail validation."""
    text = SKILL_MD.read_text()
    assert re.search(r'clean-state-files\.sh.*?\|\|\s*true', text, re.DOTALL), (
        "SKILL.md Step 7 clean-state-files.sh call must use '|| true' so a non-zero exit "
        "does not abort rimba remove via set -e propagation into the background subshell"
    )
