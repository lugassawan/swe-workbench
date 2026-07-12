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
    """preflight-pr.sh must include a guard clause that exits if OWNER or REPO cannot be determined."""
    # Fix A moved the OWNER/REPO guard to runtime/preflight-pr.sh
    text = (ROOT / "runtime" / "preflight-pr.sh").read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "runtime/preflight-pr.sh must include the guard-clause error message for missing OWNER/REPO "
        "so failures produce an actionable error rather than silently misrouting API calls"
    )


# --- Cleanup call-site assertions (guard bypass fix) ---

def test_pr_review_skill_cleanup_uses_clean_ephemeral_script():
    """Step 7 background cleanup and pre-flight stale removal must use clean-ephemeral.sh, not bare rm -rf."""
    text = SKILL_MD.read_text()
    assert "clean-ephemeral.sh" in text, (
        "SKILL.md cleanup blocks must invoke runtime/clean-ephemeral.sh — "
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
    """Step 7 success-path must invoke clean-state-files.sh with this skill's own
    preflight state file. The threads-cache file moved to workflow-pr-review-post's
    own reap (#499) — it owns a distinct ${PR}-post-threads.json, not this file's job."""
    text = SKILL_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "SKILL.md Step 7 must call runtime/clean-state-files.sh to remove its own per-run state file"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}.json to clean-state-files.sh"
    )


def test_post_core_cleanup_deletes_own_threads_json():
    """workflow-pr-review-post owns its own threads-cache reap, distinct from either
    consumer's preflight-state file (issue #499). The filename is CALLER_TAG-scoped so
    concurrent callers (general/followup/specialist) reviewing the same PR never share
    (and can't clobber) each other's threads cache."""
    text = (ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md").read_text()
    assert "clean-state-files.sh" in text, (
        "workflow-pr-review-post/SKILL.md must call runtime/clean-state-files.sh to reap its own state"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json" in text, (
        "workflow-pr-review-post/SKILL.md must pass its own CALLER_TAG-scoped "
        "/tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json to clean-state-files.sh"
    )


def test_post_core_requires_caller_tag_input():
    """The core's input contract must require CALLER_TAG so the threads-cache filename
    stays scoped per caller (issue #499 follow-up fix)."""
    text = (ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md").read_text()
    assert "CALLER_TAG" in text, (
        "workflow-pr-review-post/SKILL.md input contract must document CALLER_TAG"
    )


def test_pr_review_skill_passes_caller_tag_general():
    """workflow-pr-review must pass CALLER_TAG=general when invoking the posting core."""
    text = SKILL_MD.read_text()
    assert "CALLER_TAG" in text and "general" in text, (
        "workflow-pr-review/SKILL.md must pass CALLER_TAG=general to workflow-pr-review-post"
    )


def test_pr_review_skill_state_cleanup_outside_background_subshell():
    """clean-state-files.sh must NOT appear inside the background ( ... ) & subshell.

    The reap must run in the foreground so failures surface immediately rather than being
    silently dropped by the backgrounded, output-suppressed worktree-teardown subshell.
    This is the inverse of the previous #428 assertion, which encoded the bug as correct.
    """
    text = SKILL_MD.read_text()
    subshell_match = re.search(r'\([^)]*clean-state-files\.sh[^)]*\)\s*&', text)
    assert not subshell_match, (
        "SKILL.md Step 7 clean-state-files.sh call must NOT be inside the background ( ... ) & "
        "subshell — the reap must run foreground so failures are visible (recurrence of #428/#429)"
    )


def test_pr_review_skill_state_cleanup_no_suppression():
    """clean-state-files.sh call must have NO 2>/dev/null and NO || true guard.

    The reap runs foreground (fix for #428/#429 recurrence): suppression guards would re-hide
    the same silent-orphan path. A non-zero exit from clean-state-files.sh is a real failure.
    """
    text = SKILL_MD.read_text()
    # Find the line(s) containing clean-state-files.sh and assert none carry 2>/dev/null
    lines_with_reap = [
        ln for ln in text.splitlines() if "clean-state-files.sh" in ln
    ]
    assert lines_with_reap, "SKILL.md must contain a clean-state-files.sh call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        f"clean-state-files.sh call must not carry 2>/dev/null (foreground reap must be visible):\n"
        + "\n".join(suppressed)
    )


def test_pr_review_skill_state_cleanup_has_post_check():
    """Step 7 must include a post-reap verification that reports each state file as reaped or not."""
    text = SKILL_MD.read_text()
    assert re.search(r'✓ state file reaped:', text), (
        "SKILL.md Step 7 must include a post-reap report line '✓ state file reaped: ...' "
        "so operators can verify cleanup completed without inspecting /tmp by hand"
    )
