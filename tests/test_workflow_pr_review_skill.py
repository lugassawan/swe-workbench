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
    """preflight-pr must include a guard clause that exits if OWNER or REPO cannot be determined."""
    # Fix A moved the OWNER/REPO guard to bin/swe-workbench-preflight-pr
    text = (ROOT / "bin" / "swe-workbench-preflight-pr").read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "bin/swe-workbench-preflight-pr must include the guard-clause error message for missing "
        "OWNER/REPO so failures produce an actionable error rather than silently misrouting API calls"
    )


# --- Cleanup call-site assertions (guard bypass fix) ---

def test_pr_review_skill_cleanup_uses_pr_review_worktree_script():
    """Since issue #666, worktree acquire/release (including the clean-ephemeral
    delegation and the collision-safe self-heal) live in
    bin/swe-workbench-pr-review-worktree, not inline SKILL.md prose. Step 2/7 must
    delegate to it rather than reimplementing rimba add / git worktree add / rm -rf."""
    text = SKILL_MD.read_text()
    assert "swe-workbench-pr-review-worktree" in text, (
        "SKILL.md Step 2/7 must invoke swe-workbench-pr-review-worktree acquire/release "
        "rather than inlining worktree create/teardown prose"
    )
    assert "swe-workbench-pr-review-worktree acquire" in text
    assert "swe-workbench-pr-review-worktree release" in text


def test_pr_review_skill_no_bare_rm_rf_wt():
    """SKILL.md must not contain a bare 'rm -rf \"$WT\"' that the bash guard would block."""
    text = SKILL_MD.read_text()
    assert not re.search(r'rm\s+-[rR][fF]\s+"?\$WT"?(?!\s*2>)', text) or \
           not re.search(r'rm\s+-[rR][fF]\s+"?\$WT"?\s*(?:2>/dev/null\s*)?(?:;|\))', text), (
        "SKILL.md must not use 'rm -rf \"$WT\"' directly — "
        "route through swe-workbench-clean-ephemeral to avoid the bash guard blocking home-tree paths"
    )
    # Stricter: no standalone rm -rf "$WT" outside of swe-workbench-clean-ephemeral invocations
    lines_with_rm = [
        line for line in text.splitlines()
        if re.search(r'rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF]', line)
        and '"$WT"' in line
        and "clean-ephemeral" not in line
    ]
    assert not lines_with_rm, (
        f"Found bare rm -rf \"$WT\" lines (should use swe-workbench-clean-ephemeral):\n"
        + "\n".join(lines_with_rm)
    )


# --- State-file cleanup assertions (issue #428) ---

def test_pr_review_skill_cleanup_deletes_pr_json():
    """Step 7 success-path must invoke swe-workbench-clean-state-files with this skill's own
    preflight state file. The threads-cache file moved to workflow-pr-review-post's
    own reap (#499) — it owns a distinct ${PR}-post-threads.json, not this file's job.

    Since #565 folded the standalone followup skill into this skill as a mode, the state-file
    path is templated via $STATE_SUFFIX (empty for first-pass, "-followup" for followup)
    rather than a literal ${PR}.json — first-pass mode's own mode-table row must resolve
    STATE_SUFFIX to empty."""
    text = SKILL_MD.read_text()
    assert "swe-workbench-clean-state-files" in text, (
        "SKILL.md Step 7 must call swe-workbench-clean-state-files to remove its own per-run state file"
    )
    assert "/tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json to "
        "swe-workbench-clean-state-files, so first-pass mode reaps ${PR}.json"
    )
    assert re.search(r'first-pass\)[^\n]*STATE_SUFFIX=""', text), (
        'SKILL.md mode table must set STATE_SUFFIX="" for first-pass mode, so '
        "${PR}${STATE_SUFFIX}.json resolves to ${PR}.json"
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
    """swe-workbench-clean-state-files must NOT appear inside the background ( ... ) & subshell.

    The reap must run in the foreground so failures surface immediately rather than being
    silently dropped by the backgrounded, output-suppressed worktree-teardown subshell.
    This is the inverse of the previous #428 assertion, which encoded the bug as correct.
    """
    text = SKILL_MD.read_text()
    subshell_match = re.search(r'\([^)]*swe-workbench-clean-state-files[^)]*\)\s*&', text)
    assert not subshell_match, (
        "SKILL.md Step 7 swe-workbench-clean-state-files call must NOT be inside the background ( ... ) & "
        "subshell — the reap must run foreground so failures are visible (recurrence of #428/#429)"
    )


def test_pr_review_skill_state_cleanup_no_suppression():
    """swe-workbench-clean-state-files call must have NO 2>/dev/null and NO || true guard.

    The reap runs foreground (fix for #428/#429 recurrence): suppression guards would re-hide
    the same silent-orphan path. A non-zero exit from swe-workbench-clean-state-files is a real failure.
    """
    text = SKILL_MD.read_text()
    # Find the line(s) containing swe-workbench-clean-state-files and assert none carry 2>/dev/null
    lines_with_reap = [
        ln for ln in text.splitlines() if "swe-workbench-clean-state-files" in ln
    ]
    assert lines_with_reap, "SKILL.md must contain a swe-workbench-clean-state-files call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        f"swe-workbench-clean-state-files call must not carry 2>/dev/null (foreground reap must be visible):\n"
        + "\n".join(suppressed)
    )


def test_pr_review_skill_state_cleanup_has_post_check():
    """Step 7 must include a post-reap verification that reports each state file as reaped or not."""
    text = SKILL_MD.read_text()
    assert re.search(r'✓ state file reaped:', text), (
        "SKILL.md Step 7 must include a post-reap report line '✓ state file reaped: ...' "
        "so operators can verify cleanup completed without inspecting /tmp by hand"
    )


# --- Reap-on-reject ordering ---

def test_pr_review_skill_followup_gate_precedes_run_dir_allocation():
    """The followup STATE gate must be hoisted above swe-workbench-new-run-dir
    allocation — a rejected followup PR must never allocate $RUN_DIR at all,
    rather than allocating and then leaking it."""
    text = SKILL_MD.read_text()
    gate_idx = text.find('[ "$MODE" = followup ] && [ "$STATE" != "OPEN" ]')
    run_dir_idx = text.find('swe-workbench-new-run-dir "$MODE_TAG" "$PR"')
    assert gate_idx != -1, "SKILL.md Step 1 must contain the followup STATE gate"
    assert run_dir_idx != -1, "SKILL.md Step 1 must contain the swe-workbench-new-run-dir call"
    assert gate_idx < run_dir_idx, (
        "the followup STATE gate must precede swe-workbench-new-run-dir allocation — "
        "otherwise a rejected followup PR leaks $RUN_DIR"
    )


def test_pr_review_skill_followup_reject_reaps_json():
    """The followup-reject branch must reap $JSON before exiting — the PR-keyed
    state file is otherwise abandoned when the PR turns out to be closed/merged."""
    text = SKILL_MD.read_text()
    match = re.search(
        r'if \[ "\$MODE" = followup \] && \[ "\$STATE" != "OPEN" \]; then\n(.*?)\nfi',
        text, re.DOTALL,
    )
    assert match, "SKILL.md Step 1 must contain the followup-reject if-block"
    assert 'swe-workbench-clean-state-files "$JSON"' in match.group(1), (
        'the followup-reject branch must call swe-workbench-clean-state-files "$JSON" '
        "before exiting, to avoid leaking the PR-keyed state file"
    )
