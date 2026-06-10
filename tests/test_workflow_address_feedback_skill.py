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


# --- Cleanup (Phase 6) tests — AC#1, AC#2, AC#3 from issue #291 ---

def test_address_feedback_skill_cleans_up_worktree():
    """Phase 6 must include rimba remove "address-feedback-$PR" --force (AC#1)."""
    text = SKILL_MD.read_text()
    assert re.search(r'rimba remove ["\']?address-feedback-\$PR["\']? --force', text), (
        'SKILL.md Phase 6 must include: rimba remove "address-feedback-$PR" --force — '
        "the worktree is disposable; fixes are on the remote branch after Phase 4"
    )


def test_address_feedback_skill_cleanup_failure_tolerant():
    """Phase 6 cleanup must include a git-worktree fallback and must not block on failure (AC#2)."""
    text = SKILL_MD.read_text()
    assert "git worktree remove" in text, (
        "SKILL.md Phase 6 must include a 'git worktree remove' fallback for when rimba is absent"
    )
    assert re.search(
        r"warn|do not block|never block|not block|continue|non.blocking|emit.*notice",
        text, re.IGNORECASE
    ), (
        "SKILL.md Phase 6 must state that cleanup failure is non-blocking (warn, do not block, continue)"
    )


def test_address_feedback_skill_cleanup_preserves_pr_branch():
    """Phase 6 fallback must NEVER contain git branch -D \"$PR_BRANCH\" — that deletes the real PR head branch."""
    text = SKILL_MD.read_text()
    assert not re.search(r'branch\s+-D\s+["\']?\$PR_BRANCH', text), (
        'SKILL.md must NOT contain: git branch -D "$PR_BRANCH" — '
        "the git-worktree fallback in Phase 6 only removes the worktree dir; "
        "deleting $PR_BRANCH would destroy the owner's actual PR head branch"
    )


def test_address_feedback_skill_drops_durable_no_cleanup_claim():
    """SKILL.md must NOT contain the old 'no auto-cleanup' claim (stance reversal for issue #291)."""
    text = SKILL_MD.read_text()
    assert "no auto-cleanup" not in text, (
        "SKILL.md must not claim 'no auto-cleanup' — issue #291 reversed this stance; "
        "Phase 6 always removes the worktree on exit"
    )


def test_address_feedback_skill_has_cleanup_phase():
    """SKILL.md must have a Phase 6 / Cleanup section that runs on every post-Phase-2 exit (AC#3)."""
    text = SKILL_MD.read_text()
    assert re.search(r"Phase 6|## Phase 6|### Phase 6", text), (
        "SKILL.md must include a Phase 6 (Cleanup) section — "
        "it must run on success, Q-exit, and error paths after a worktree has been created (AC#3)"
    )


def test_address_feedback_skill_cleanup_uses_existing_wt():
    """Phase 6 fallback must use $WT from Phase 2 — must not re-assign WT= in the else branch."""
    text = SKILL_MD.read_text()
    phase6_match = re.search(r"### Phase 6.*", text, re.DOTALL)
    assert phase6_match, "Phase 6 section must exist for this check"
    phase6_text = phase6_match.group(0)
    assert not re.search(r'\bWT\s*=\s*["\'\$]', phase6_text), (
        "Phase 6 must not re-assign $WT — use the value set in Phase 2 so the fallback "
        "targets the correct worktree directory regardless of which Phase 2 branch (rimba vs. git) ran"
    )


def test_address_feedback_skill_reuses_worktree_when_on_pr_branch():
    """Phase 2 must reuse the current worktree when the branch matches the PR head (closes #295)."""
    text = SKILL_MD.read_text()
    # Assignment line must exist in the code block.
    assert "CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)" in text, (
        "SKILL.md Phase 2 must assign: CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)"
    )
    # Comparison must test $CURRENT_BRANCH against $PR_BRANCH in the if-condition.
    assert re.search(r'"\$CURRENT_BRANCH"\s*=\s*"\$PR_BRANCH"', text), (
        "SKILL.md Phase 2 must compare $CURRENT_BRANCH against $PR_BRANCH in the if-condition"
    )
    # Skip path: reuse the current directory instead of creating a worktree.
    assert "WT=$(pwd)" in text, (
        "SKILL.md Phase 2 must set WT=$(pwd) to reuse the current worktree when "
        "already on the PR branch, skipping 'rimba add'"
    )


def test_address_feedback_skill_phase6_skips_cleanup_on_reuse():
    """Phase 6 must not run git worktree remove / rm -rf when the worktree was reused (closes #295)."""
    text = SKILL_MD.read_text()
    phase6_idx = text.find("### Phase 6")
    assert phase6_idx != -1, "Phase 6 section must exist"
    phase6_text = text[phase6_idx:]
    # Phase 6 must reference REUSED_WT so the cleanup is skipped for the reuse path.
    assert "REUSED_WT" in phase6_text, (
        "SKILL.md Phase 6 must guard cleanup with REUSED_WT — when the reuse-guard "
        "fires (WT=$(pwd)), rimba remove will fail for an unregistered task, causing "
        "git worktree remove --force / rm -rf to run against the user's live checkout"
    )


def test_address_feedback_skill_reuses_existing_worktree_on_main():
    """Phase 2 must find and reuse an existing worktree for PR_BRANCH when session is not on that branch."""
    text = SKILL_MD.read_text()
    # Must use git worktree list --porcelain to locate an existing worktree for the branch.
    assert "git worktree list --porcelain" in text, (
        "SKILL.md Phase 2 must scan 'git worktree list --porcelain' to find an existing "
        "worktree for $PR_BRANCH when the current branch does not match (e.g. session on main)"
    )
    # Must look up the branch ref inside the porcelain output (awk escapes the slashes).
    assert r"refs\/heads\/" in text, (
        r"SKILL.md Phase 2 must match 'refs\/heads\/$PR_BRANCH' in the awk pattern "
        "to locate the correct registered worktree in porcelain output"
    )
    # Must set REUSED_WT=1 on a match, same as the first guard.
    assert re.search(r"EXISTING_WT.*\n.*REUSED_WT=1|REUSED_WT=1.*EXISTING_WT", text, re.DOTALL), (
        "SKILL.md Phase 2 must set REUSED_WT=1 when an existing worktree is found via "
        "git worktree list, so Phase 6 skips the destructive cleanup"
    )


def test_address_feedback_skill_skips_already_clarified_threads():
    """Phase 3 must skip unresolved threads already replied to by $CURRENT_USER (closes #296)."""
    text = SKILL_MD.read_text()
    # Detection must compare comment authorship against the current user.
    assert re.search(r"author\.login.*CURRENT_USER|CURRENT_USER.*author\.login", text), (
        "SKILL.md Phase 3 must detect already-clarified threads by comparing "
        "comments.nodes[*].author.login against $CURRENT_USER"
    )
    # The skip must be described as 'already clarified' within the Phase 3 section.
    phase3_match = re.search(r"### Phase 3.*?(?=###|^##)", text, re.DOTALL | re.MULTILINE)
    assert phase3_match, "Phase 3 section must exist for this check"
    phase3_text = phase3_match.group(0)
    assert "already clarified" in phase3_text.lower(), (
        "SKILL.md Phase 3 must describe skipping threads the owner already clarified on re-runs"
    )
    # The transparency note format must appear before the triage digest within Phase 3.
    idx_skipped = phase3_text.lower().find("thread(s) skipped")
    idx_digest = phase3_text.find("For each remaining thread")
    assert idx_skipped != -1, (
        "SKILL.md Phase 3 must include the transparency note format: "
        "'(N thread(s) skipped — already clarified.)'"
    )
    assert idx_digest != -1, "Phase 3 must contain 'For each remaining thread'"
    assert idx_skipped < idx_digest, (
        "SKILL.md Phase 3 transparency note must appear before 'For each remaining thread'"
    )


# --- Cleanup call-site assertions (guard bypass fix) ---

def test_address_feedback_skill_cleanup_uses_clean_ephemeral_script():
    """Phase 6 fallback must invoke clean-ephemeral.sh, not bare rm -rf "$WT"."""
    text = SKILL_MD.read_text()
    assert "clean-ephemeral.sh" in text, (
        "SKILL.md Phase 6 fallback must use scripts/clean-ephemeral.sh — "
        "bare 'rm -rf $WT' under /Users/... (rimba worktree root) is blocked by the bash guard"
    )


def test_address_feedback_skill_no_bare_rm_rf_wt():
    """Phase 6 must not contain a bare 'rm -rf \"$WT\"' that the bash guard would block."""
    text = SKILL_MD.read_text()
    lines_with_rm = [
        line for line in text.splitlines()
        if re.search(r'rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF]', line)
        and '"$WT"' in line
        and "clean-ephemeral" not in line
    ]
    assert not lines_with_rm, (
        f"Found bare rm -rf \"$WT\" lines in Phase 6 (should use clean-ephemeral.sh):\n"
        + "\n".join(lines_with_rm)
    )


# --- State-file cleanup assertions (issue #428) ---

def test_address_feedback_skill_deletes_three_state_files():
    """Phase 5 success path must invoke clean-state-files.sh with all three state files."""
    text = SKILL_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "SKILL.md must call scripts/clean-state-files.sh to remove address-feedback state files"
    )
    assert "/tmp/swe-workbench-address-feedback/${PR}.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-address-feedback/${PR}.json to clean-state-files.sh"
    )
    assert "/tmp/swe-workbench-address-feedback/${PR}-threads.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-address-feedback/${PR}-threads.json to clean-state-files.sh"
    )
    assert "/tmp/swe-workbench-address-feedback/${PR}-triage.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-address-feedback/${PR}-triage.json to clean-state-files.sh"
    )


def test_address_feedback_skill_triage_cleanup_before_phase6():
    """${PR}-triage.json removal must appear BEFORE ### Phase 6 (Q-quit safety invariant).

    Phase 6 fires on Q-quit too.  triage.json is durable resume state that must survive Q-quit
    so the user can resume from Phase 3.  Removing it on the Phase 5 success path (before Phase 6)
    ensures Q-quit leaves it intact.
    """
    text = SKILL_MD.read_text()
    triage_cleanup_idx = text.find("/tmp/swe-workbench-address-feedback/${PR}-triage.json")
    phase6_idx = text.find("### Phase 6")
    assert triage_cleanup_idx != -1, (
        "SKILL.md must reference /tmp/swe-workbench-address-feedback/${PR}-triage.json for cleanup"
    )
    assert phase6_idx != -1, "SKILL.md must have a ### Phase 6 section"
    assert triage_cleanup_idx < phase6_idx, (
        "triage.json cleanup must appear BEFORE ### Phase 6 — "
        "Phase 6 also fires on Q-quit; triage.json must survive Q-quit for resume"
    )


def test_address_feedback_skill_phase6_does_not_delete_triage_json():
    """Phase 6 code block must NOT contain a triage.json deletion (Q-quit must leave it intact)."""
    text = SKILL_MD.read_text()
    phase6_idx = text.find("### Phase 6")
    assert phase6_idx != -1, "Phase 6 section must exist"
    # Extract only up to the next top-level section (## Failure modes or ## Common mistakes).
    next_section = re.search(r'\n## ', text[phase6_idx:])
    phase6_text = text[phase6_idx: phase6_idx + next_section.start()] if next_section else text[phase6_idx:]
    # triage.json must not appear in the Phase 6 action blocks (only in the failure-modes table which follows)
    # Filter out lines that are in a table row referencing the failure-mode description
    phase6_lines_with_triage = [
        line for line in phase6_text.splitlines()
        if "triage.json" in line
        and not line.lstrip().startswith("|")   # table rows describe the failure, not Phase 6 actions
    ]
    assert not phase6_lines_with_triage, (
        "Phase 6 action blocks must NOT delete triage.json — Phase 6 runs on Q-quit too, and "
        "triage.json is durable resume state that must survive Q-quit.\n"
        "Lines found: " + "\n".join(phase6_lines_with_triage)
    )
