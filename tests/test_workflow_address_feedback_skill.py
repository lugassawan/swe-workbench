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
    """SKILL.md must reference the reply REST endpoint directly or via reply-and-resolve.sh."""
    text = SKILL_MD.read_text()
    assert re.search(r"pulls/.*comments/.*replies", text) or "reply-and-resolve.sh" in text, (
        "SKILL.md must either reference the REST reply endpoint pattern "
        "(pulls/{N}/comments/{id}/replies) or invoke runtime/reply-and-resolve.sh"
    )


def test_address_feedback_skill_references_resolve_mutation():
    """SKILL.md must reference resolveReviewThread directly or via reply-and-resolve.sh."""
    text = SKILL_MD.read_text()
    assert "resolveReviewThread" in text or "reply-and-resolve.sh" in text, (
        "SKILL.md must reference the resolveReviewThread GraphQL mutation "
        "or delegate to runtime/reply-and-resolve.sh"
    )


def test_address_feedback_skill_uses_three_way_triage():
    """SKILL.md must define the ADDRESSED / CLARIFIED / DEFERRED three-way triage."""
    text = SKILL_MD.read_text()
    assert "ADDRESSED" in text, "SKILL.md must reference ADDRESSED triage state"
    assert "CLARIFIED" in text, "SKILL.md must reference CLARIFIED triage state"
    assert "DEFERRED" in text, "SKILL.md must reference DEFERRED triage state"



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
    """preflight-pr.sh must include a guard clause that exits if OWNER or REPO cannot be determined."""
    # Fix A moved the OWNER/REPO guard to runtime/preflight-pr.sh
    text = (ROOT / "runtime" / "preflight-pr.sh").read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "runtime/preflight-pr.sh must include the guard-clause error message for missing OWNER/REPO "
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


# --- Phase 6 — Sync PR metadata (issue #454) ---


def _phase6_sync_text(text: str) -> str:
    """Extract the Phase 6 Sync PR metadata section (between ### Phase 6 and ### Phase 7)."""
    start = text.find("### Phase 6")
    assert start != -1, "### Phase 6 section must exist"
    end = text.find("### Phase 7", start)
    return text[start:end] if end != -1 else text[start:]


def test_address_feedback_skill_has_phase6_sync_section():
    """SKILL.md must have a Phase 6 Sync PR metadata section (closes #454)."""
    text = SKILL_MD.read_text()
    assert re.search(r"### Phase 6.*Sync PR metadata", text), (
        "SKILL.md must include '### Phase 6 — Sync PR metadata' section (closes #454)"
    )


def test_address_feedback_skill_phase6_skips_when_no_fix_sha():
    """Phase 6 must be skipped entirely when $FIX_SHA is unset (no fixes committed)."""
    text = SKILL_MD.read_text()
    phase6 = _phase6_sync_text(text)
    assert "FIX_SHA" in phase6, (
        "Phase 6 Sync section must reference $FIX_SHA to decide whether to run"
    )
    assert re.search(r"[Ss]kip|unset|not set", phase6), (
        "Phase 6 must describe skipping when $FIX_SHA is unset (no commits in Phase 4)"
    )


def test_address_feedback_skill_phase6_detects_drift_against_diff_and_subjects():
    """Phase 6 must compare title + ## Summary against the cumulative diff and commit subjects."""
    text = SKILL_MD.read_text()
    phase6 = _phase6_sync_text(text)
    assert "git diff" in phase6 or "--stat" in phase6, (
        "Phase 6 must fetch the cumulative diff (git diff or --stat) as drift signal"
    )
    assert "git log" in phase6 or "commit subjects" in phase6.lower(), (
        "Phase 6 must fetch commit subjects (git log --format='%s') as drift signal"
    )
    assert "## Summary" in phase6, (
        "Phase 6 must compare against the ## Summary section of the PR body"
    )


def test_address_feedback_skill_phase6_apply_is_preview_gated():
    """Phase 6 revision must be preview-gated with Reply `yes` before applying."""
    text = SKILL_MD.read_text()
    phase6 = _phase6_sync_text(text)
    assert re.search(r"Reply\s+`yes`", phase6), (
        "Phase 6 must gate the metadata update behind 'Reply `yes`' (same convention as Phase 1)"
    )
    assert "sync-pr-metadata.sh" in phase6, (
        "Phase 6 must apply the revision via runtime/sync-pr-metadata.sh"
    )


def test_address_feedback_skill_phase6_preserves_trailer():
    """Phase 6 body rewrite must preserve the Closes #/Fixes #/Issue: N/A trailer."""
    text = SKILL_MD.read_text()
    phase6 = _phase6_sync_text(text)
    assert re.search(r"Closes #|trailer|scaffold", phase6, re.IGNORECASE), (
        "Phase 6 must describe preserving the 'Closes #' trailer and PR template scaffolding "
        "when rewriting the ## Summary section"
    )


# --- Cleanup (Phase 7) tests — AC#1, AC#2, AC#3 from issue #291 ---

def test_address_feedback_skill_cleans_up_worktree():
    """Phase 7 must include rimba remove "address-feedback-$PR" --force (AC#1)."""
    text = SKILL_MD.read_text()
    assert re.search(r'rimba remove ["\']?address-feedback-\$PR["\']? --force', text), (
        'SKILL.md Phase 7 must include: rimba remove "address-feedback-$PR" --force — '
        "the worktree is disposable; fixes are on the remote branch after Phase 4"
    )


def test_address_feedback_skill_cleanup_failure_tolerant():
    """Phase 7 cleanup must include a git-worktree fallback and must not block on failure (AC#2)."""
    text = SKILL_MD.read_text()
    assert "git worktree remove" in text, (
        "SKILL.md Phase 7 must include a 'git worktree remove' fallback for when rimba is absent"
    )
    assert re.search(
        r"warn|do not block|never block|not block|continue|non.blocking|emit.*notice",
        text, re.IGNORECASE
    ), (
        "SKILL.md Phase 7 must state that cleanup failure is non-blocking (warn, do not block, continue)"
    )


def test_address_feedback_skill_cleanup_preserves_pr_branch():
    """Phase 7 fallback must NEVER contain git branch -D \"$PR_BRANCH\" — that deletes the real PR head branch."""
    text = SKILL_MD.read_text()
    assert not re.search(r'branch\s+-D\s+["\']?\$PR_BRANCH', text), (
        'SKILL.md must NOT contain: git branch -D "$PR_BRANCH" — '
        "the git-worktree fallback in Phase 7 only removes the worktree dir; "
        "deleting $PR_BRANCH would destroy the owner's actual PR head branch"
    )


def test_address_feedback_skill_drops_durable_no_cleanup_claim():
    """SKILL.md must NOT contain the old 'no auto-cleanup' claim (stance reversal for issue #291)."""
    text = SKILL_MD.read_text()
    assert "no auto-cleanup" not in text, (
        "SKILL.md must not claim 'no auto-cleanup' — issue #291 reversed this stance; "
        "Phase 7 always removes the worktree on exit"
    )


def test_address_feedback_skill_has_cleanup_phase():
    """SKILL.md must have a Phase 7 / Cleanup section that runs on every post-Phase-2 exit (AC#3)."""
    text = SKILL_MD.read_text()
    assert re.search(r"Phase 7|## Phase 7|### Phase 7", text), (
        "SKILL.md must include a Phase 7 (Cleanup) section — "
        "it must run on success, Q-exit, and error paths after a worktree has been created (AC#3)"
    )


def test_address_feedback_skill_cleanup_uses_existing_wt():
    """Phase 7 fallback must use $WT from Phase 2 — must not re-assign WT= in the else branch."""
    text = SKILL_MD.read_text()
    phase7_match = re.search(r"### Phase 7.*", text, re.DOTALL)
    assert phase7_match, "Phase 7 section must exist for this check"
    phase7_text = phase7_match.group(0)
    assert not re.search(r'\bWT\s*=\s*["\'\$]', phase7_text), (
        "Phase 7 must not re-assign $WT — use the value set in Phase 2 so the fallback "
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
    """Phase 7 must not run git worktree remove / rm -rf when the worktree was reused (closes #295)."""
    text = SKILL_MD.read_text()
    phase7_idx = text.find("### Phase 7")
    assert phase7_idx != -1, "Phase 7 section must exist"
    phase7_text = text[phase7_idx:]
    # Phase 7 must reference REUSED_WT so the cleanup is skipped for the reuse path.
    assert "REUSED_WT" in phase7_text, (
        "SKILL.md Phase 7 must guard cleanup with REUSED_WT — when the reuse-guard "
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
        "SKILL.md Phase 6 fallback must use runtime/clean-ephemeral.sh — "
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
        "SKILL.md must call runtime/clean-state-files.sh to remove address-feedback state files"
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
    """${PR}-triage.json removal must appear BEFORE ### Phase 7 (Q-quit safety invariant).

    Phase 7 fires on Q-quit too.  triage.json is durable resume state that must survive Q-quit
    so the user can resume from Phase 3.  Removing it on the Phase 5 success path (before Phase 7)
    ensures Q-quit leaves it intact.
    """
    text = SKILL_MD.read_text()
    triage_cleanup_idx = text.find("/tmp/swe-workbench-address-feedback/${PR}-triage.json")
    phase7_idx = text.find("### Phase 7")
    assert triage_cleanup_idx != -1, (
        "SKILL.md must reference /tmp/swe-workbench-address-feedback/${PR}-triage.json for cleanup"
    )
    assert phase7_idx != -1, "SKILL.md must have a ### Phase 7 section"
    assert triage_cleanup_idx < phase7_idx, (
        "triage.json cleanup must appear BEFORE ### Phase 7 — "
        "Phase 7 also fires on Q-quit; triage.json must survive Q-quit for resume"
    )


def test_address_feedback_skill_phase6_does_not_delete_triage_json():
    """Phase 7 code block must NOT contain a triage.json deletion (Q-quit must leave it intact)."""
    text = SKILL_MD.read_text()
    phase7_idx = text.find("### Phase 7")
    assert phase7_idx != -1, "Phase 7 section must exist"
    # Extract only up to the next top-level section (## Failure modes or ## Common mistakes).
    next_section = re.search(r'\n## ', text[phase7_idx:])
    phase7_text = text[phase7_idx: phase7_idx + next_section.start()] if next_section else text[phase7_idx:]
    # triage.json must not appear in the Phase 7 action blocks (only in the failure-modes table which follows)
    # Filter out lines that are in a table row referencing the failure-mode description
    phase7_lines_with_triage = [
        line for line in phase7_text.splitlines()
        if "triage.json" in line
        and not line.lstrip().startswith("|")   # table rows describe the failure, not Phase 7 actions
    ]
    assert not phase7_lines_with_triage, (
        "Phase 7 action blocks must NOT delete triage.json — Phase 7 runs on Q-quit too, and "
        "triage.json is durable resume state that must survive Q-quit.\n"
        "Lines found: " + "\n".join(phase7_lines_with_triage)
    )


# ── Foreground-reap assertions (Fix C, recurrence of #428/#429) ─────────────


def test_address_feedback_skill_phase5_reap_no_suppression():
    """Phase 5 clean-state-files.sh call must have NO 2>/dev/null suppression.

    The reap runs foreground; suppression would recreate the silent-orphan path
    that was the root cause of the #428/#429 recurrence.
    """
    text = SKILL_MD.read_text()
    lines_with_reap = [ln for ln in text.splitlines() if "clean-state-files.sh" in ln]
    assert lines_with_reap, "SKILL.md must contain a clean-state-files.sh call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        "clean-state-files.sh call must not carry 2>/dev/null — "
        "foreground reap must be visible so orphaned state files surface as failures:\n"
        + "\n".join(suppressed)
    )


def test_address_feedback_skill_phase5_reap_has_post_check():
    """Phase 5 must include a post-reap report line confirming each state file was reaped."""
    text = SKILL_MD.read_text()
    assert re.search(r'✓ state file reaped:', text), (
        "SKILL.md Phase 5 must include a post-reap report line "
        "'✓ state file reaped: ...' so operators can verify cleanup completed"
    )
