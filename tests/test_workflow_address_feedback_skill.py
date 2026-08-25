# tests/test_workflow_address_feedback_skill.py

"""Tests for the workflow-address-feedback skill (closes #218)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-address-feedback"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS_TXT = SKILL_DIR / "triggers.txt"
REFERENCE_DIR = SKILL_DIR / "reference"
REFERENCE_SYNC_PR_METADATA = REFERENCE_DIR / "sync-pr-metadata.md"
REFERENCE_RESOLVE_REVIEW_THREADS = REFERENCE_DIR / "resolve-review-threads.md"


def _skill_text_with_references() -> str:
    """SKILL.md text plus all reference/*.md content.

    Task 5 (#567) extracted Phase 6 and the Phase 5 resolve/reply mechanics out of
    SKILL.md into reference/ files; assertions on that content now check the combined
    text so they verify the skill package as a whole regardless of which file the
    content currently lives in.
    """
    text = SKILL_MD.read_text()
    if REFERENCE_DIR.is_dir():
        for ref in sorted(REFERENCE_DIR.glob("*.md")):
            text += "\n" + ref.read_text()
    return text


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
    """SKILL.md must reference the reply REST endpoint directly or via swe-workbench-reply-and-resolve."""
    text = SKILL_MD.read_text()
    assert re.search(r"pulls/.*comments/.*replies", text) or "swe-workbench-reply-and-resolve" in text, (
        "SKILL.md must either reference the REST reply endpoint pattern "
        "(pulls/{N}/comments/{id}/replies) or invoke swe-workbench-reply-and-resolve"
    )


def test_address_feedback_skill_references_resolve_mutation():
    """SKILL.md must reference resolveReviewThread directly or via swe-workbench-reply-and-resolve."""
    text = SKILL_MD.read_text()
    assert "resolveReviewThread" in text or "swe-workbench-reply-and-resolve" in text, (
        "SKILL.md must reference the resolveReviewThread GraphQL mutation "
        "or delegate to swe-workbench-reply-and-resolve"
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
    """preflight-pr must include a guard clause that exits if OWNER or REPO cannot be determined."""
    # Fix A moved the OWNER/REPO guard to bin/swe-workbench-preflight-pr
    text = (ROOT / "bin" / "swe-workbench-preflight-pr").read_text()
    assert re.search(r"Could not determine base repo owner", text), (
        "bin/swe-workbench-preflight-pr must include the guard-clause error message for missing "
        "OWNER/REPO so failures produce an actionable error rather than silently misrouting API calls"
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
    text = _skill_text_with_references()
    assert "nodes[0]" in text or "thread root" in text or "first comment" in text, (
        "SKILL.md Phase 5 must specify that $COMMENT_DATABASEID is populated from "
        "comments.nodes[0].databaseId (the thread root), not a subsequent reply"
    )


def test_address_feedback_skill_clarified_and_deferred_threads_now_resolve():
    """SKILL.md (and its reference/ files) must state that CLARIFIED and DEFERRED review
    threads now reply AND resolve — replaces the old CLARIFIED-no-resolve assertion
    with the opposite invariant, so a future regression is caught the same way this one was."""
    text = _skill_text_with_references()
    assert re.search(r"CLARIFIED.*resolve", text) or re.search(r"resolve.*CLARIFIED", text), (
        "SKILL.md (or its reference/ files) must state that CLARIFIED review threads "
        "now resolve — reply + resolve, same as ADDRESSED"
    )
    assert re.search(r"DEFERRED.*resolve", text) or re.search(r"resolve.*DEFERRED", text), (
        "SKILL.md (or its reference/ files) must state that DEFERRED review threads "
        "now resolve — reply + resolve, same as ADDRESSED/CLARIFIED"
    )


def test_address_feedback_skill_pr_comments_still_have_no_thread_to_resolve():
    """PR-level comments have no thread — the review-thread resolve change must not
    be implied to apply to PR comments, which keep their existing A/C-reply-only, D-skip
    behavior."""
    text = SKILL_MD.read_text()
    assert "have no thread to resolve" in text, (
        "SKILL.md must still document that PR-level comments have no thread to resolve "
        "— the resolve change is scoped to review threads only"
    )


# --- Phase 6 — Sync PR metadata (issue #454) ---


def _phase6_sync_text(text: str = "") -> str:
    """Full Phase 6 mechanics text.

    Task 5 (#567) extracted the Phase 6 body into reference/sync-pr-metadata.md,
    leaving only a heading + summary + pointer in SKILL.md; the detailed assertions
    below check the reference file, which is now the canonical source (unused `text`
    param kept so existing call sites `_phase6_sync_text(text)` still work).
    """
    assert REFERENCE_SYNC_PR_METADATA.exists(), (
        "skills/workflow-address-feedback/reference/sync-pr-metadata.md must exist "
        "(Phase 6 detail was extracted here — Task 5, #567)"
    )
    return REFERENCE_SYNC_PR_METADATA.read_text()


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
    assert "swe-workbench-sync-pr-metadata" in phase6, (
        "Phase 6 must apply the revision via swe-workbench-sync-pr-metadata"
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
    """Phase 7 must release the worktree via the runtime command but KEEP the PR branch (issue #643, #662)."""
    text = SKILL_MD.read_text()
    assert re.search(
        r'swe-workbench-address-feedback-worktree release\s*\\\s*\n\s*--pr "\$PR" --path "\$WT" --branch "\$PR_BRANCH" --created "\$CREATED_WT"',
        text,
    ), (
        'SKILL.md Phase 7 must call: swe-workbench-address-feedback-worktree release '
        '--pr "$PR" --path "$WT" --branch "$PR_BRANCH" --created "$CREATED_WT" — '
        "the worktree is disposable but the local PR head branch must be preserved "
        "(release is path-keyed and never issues a branch-deleting command)"
    )


def test_address_feedback_skill_cleanup_failure_tolerant():
    """Phase 7 cleanup must delegate to the release runtime command and must not block on failure (AC#2)."""
    text = SKILL_MD.read_text()
    assert "swe-workbench-address-feedback-worktree release" in text, (
        "SKILL.md Phase 7 must delegate worktree teardown to swe-workbench-address-feedback-worktree release"
    )
    assert re.search(
        r"warn|do not block|never block|not block|continue|non.blocking|emit.*notice",
        text, re.IGNORECASE
    ), (
        "SKILL.md Phase 7 must state that cleanup failure is non-blocking (warn, do not block, continue)"
    )


# --- Worktree create-path contract — issue #643, #662 ---

def test_address_feedback_skill_create_uses_pr_branch_task_form():
    """Phase 2 must acquire the worktree via the runtime command, not the retired pr:<num> task form (AC#1)."""
    text = _skill_text_with_references()
    assert 'swe-workbench-address-feedback-worktree acquire --pr "$PR" --branch "$PR_BRANCH"' in text, (
        'SKILL.md Phase 2 must invoke: swe-workbench-address-feedback-worktree acquire '
        '--pr "$PR" --branch "$PR_BRANCH" — the worktree always lands on the PR branch itself'
    )
    phase2_start = text.find("### Phase 2")
    phase2_end = text.find("### Phase 3")
    assert phase2_start != -1 and phase2_end != -1, "Phase 2/Phase 3 headings must exist"
    phase2 = text[phase2_start:phase2_end]
    assert "pr:$PR" not in phase2, (
        "Phase 2 must not use the pr:<num> task form for worktree creation — it creates a "
        "throwaway branch off the PR head, so pushes never update the PR"
    )
    assert '--task "address-feedback-$PR"' not in text, (
        "SKILL.md must not pass --task address-feedback-$PR — the worktree must land on "
        "the PR branch itself"
    )


def test_address_feedback_skill_disposable_paragraph_on_pr_branch():
    """Prose must state the worktree sits on the PR branch; cleanup keeps the branch (crash recovery)."""
    text = _skill_text_with_references()
    assert "on the PR branch itself" in text, (
        "SKILL.md must explain the worktree is on the PR branch itself — pushes update the PR directly"
    )
    assert "keeps the local" in text and "$PR_BRANCH" in text, (
        "SKILL.md must state cleanup keeps the local $PR_BRANCH (unpushed commits from a "
        "crashed run survive; the branch is the owner's PR head)"
    )


def test_address_feedback_skill_failure_modes_fork_limitation():
    """Failure modes must carry the cross-fork limitation note (forks out of scope, issue #643)."""
    text = _skill_text_with_references()
    assert "gh-fork-<owner>" in text, (
        "SKILL.md Failure modes must note the cross-fork limitation (gh-fork-<owner> manual "
        "workaround) — the create path sources from origin; fork-only branches are out of scope"
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


def test_address_feedback_skill_phase2_derives_created_wt_from_acquire_result():
    """Phase 2 must derive $CREATED_WT (inverse of the acquire envelope's reused field) and
    pass $WT/$CREATED_WT through to Phase 7 — replaces the old skill-level reuse-detection
    (CURRENT_BRANCH/WT=$(pwd)/git worktree list --porcelain scan), now internal to `acquire`
    and covered executably by tests/test_address_feedback_worktree_script.py's
    TestAcquireReuseCurrent/TestAcquireReuseExisting (closes #295, #662)."""
    text = SKILL_MD.read_text()
    assert 'WT=$(printf \'%s\' "$RESULT" | jq -r \'.data.path\')' in text, (
        "SKILL.md Phase 2 must extract $WT from the acquire envelope's .data.path"
    )
    assert 'CREATED_WT=$(printf \'%s\' "$RESULT" | jq -r \'if .data.reused then "false" else "true" end\')' in text, (
        "SKILL.md Phase 2 must derive $CREATED_WT as the inverse of the acquire envelope's .data.reused"
    )


def test_address_feedback_skill_phase7_release_passes_created_wt():
    """Phase 7 must pass $CREATED_WT to release — release itself no-ops for a reused worktree,
    replacing the old skill-level REUSED_WT guard (closes #295, #662)."""
    text = SKILL_MD.read_text()
    phase7_idx = text.find("### Phase 7")
    assert phase7_idx != -1, "Phase 7 section must exist"
    phase7_text = text[phase7_idx:]
    assert '--created "$CREATED_WT"' in phase7_text, (
        "SKILL.md Phase 7 must pass --created \"$CREATED_WT\" to "
        "swe-workbench-address-feedback-worktree release — the runtime command's own "
        "--created flag now carries the reuse-vs-created distinction, not a skill-level REUSED_WT variable"
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
        f"Found bare rm -rf \"$WT\" lines in Phase 6 (should use swe-workbench-clean-ephemeral):\n"
        + "\n".join(lines_with_rm)
    )


# --- State-file cleanup assertions (issue #428) ---

def test_address_feedback_skill_deletes_three_state_files():
    """Phase 7 must invoke swe-workbench-clean-state-files with the fetch-envelope-sourced
    $JSON/$THREADS_PATH/$PR_COMMENTS_PATH manifest (issue #667) — not re-hardcoded literals —
    and Phase 5 must still reap the literal triage resume-point path."""
    text = SKILL_MD.read_text()
    assert "swe-workbench-clean-state-files" in text, (
        "SKILL.md must call swe-workbench-clean-state-files to remove address-feedback state files"
    )
    assert 'swe-workbench-clean-state-files "$JSON" "$THREADS_PATH" "$PR_COMMENTS_PATH"' in text, (
        "SKILL.md Phase 7 must reap $JSON/$THREADS_PATH/$PR_COMMENTS_PATH — the paths the "
        "Phase 1 fetch envelope named, not re-hardcoded literals"
    )
    assert "/tmp/swe-workbench-address-feedback/${PR}-triage.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-address-feedback/${PR}-triage.json to swe-workbench-clean-state-files"
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
    """Phase 5 swe-workbench-clean-state-files call must have NO 2>/dev/null suppression.

    The reap runs foreground; suppression would recreate the silent-orphan path
    that was the root cause of the #428/#429 recurrence.
    """
    text = SKILL_MD.read_text()
    lines_with_reap = [ln for ln in text.splitlines() if "swe-workbench-clean-state-files" in ln]
    assert lines_with_reap, "SKILL.md must contain a swe-workbench-clean-state-files call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        "swe-workbench-clean-state-files call must not carry 2>/dev/null — "
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


# --- PR-level conversation comments (issue #473) ---


def test_address_feedback_skill_early_exit_accounts_for_pr_comments():
    """Phase 1 early-exit must also gate on eligible PR comments, not just unresolved threads."""
    text = SKILL_MD.read_text()
    assert "ELIGIBLE_PR_COMMENTS" in text, (
        "SKILL.md Phase 1 must compute $ELIGIBLE_PR_COMMENTS so the early-exit can "
        "account for PR-level comments, not only review threads"
    )
    early_exit_idx = text.find("No open threads — nothing to address")
    assert early_exit_idx != -1, "SKILL.md must contain the early-exit message"
    preceding = text[:early_exit_idx]
    assert "ELIGIBLE_PR_COMMENTS" in preceding[-600:], (
        "SKILL.md early-exit gate must reference $ELIGIBLE_PR_COMMENTS just before "
        "the 'No open threads — nothing to address' message"
    )


def test_address_feedback_skill_renders_pr_comment_block():
    """Phase 3 must render a distinct 'PR comment by @{author}' block with an [A] menu that skips resolve."""
    text = SKILL_MD.read_text()
    assert "PR comment by @{author}" in text, (
        "SKILL.md Phase 3 must render PR-level comments in a distinct "
        "'PR comment by @{author}' block (no path:line)"
    )
    pr_block_idx = text.find("PR comment by @{author}")
    assert pr_block_idx != -1
    following = text[pr_block_idx:pr_block_idx + 600]
    assert re.search(r"\[A\]ddressed.*no.*resolve|\[A\]ddressed.*no thread to resolve", following, re.IGNORECASE), (
        "SKILL.md PR comment menu's [A]ddressed option must state that PR comments "
        "have no thread to resolve — resolve must be suppressed"
    )


def test_address_feedback_skill_keys_pr_comments_namespaced():
    """Phase 3 must key PR comments as triage["prcomment:<id>"], namespaced from thread node IDs."""
    text = SKILL_MD.read_text()
    assert 'triage["prcomment:' in text, (
        'SKILL.md Phase 3 must key PR comments as triage["prcomment:<comment.id>"] — '
        "namespaced so they cannot collide with GraphQL review-thread node IDs in the same map"
    )


def test_address_feedback_skill_phase5_dispatches_issue_kind():
    """Phase 5 must dispatch swe-workbench-reply-and-resolve with KIND=issue and empty comment-id/thread-id for PR comments."""
    text = _skill_text_with_references()
    assert re.search(r'swe-workbench-reply-and-resolve.*\n.*"\$OWNER" "\$REPO" "\$PR" "" "" "\$REPLY_BODY" "issue"', text), (
        'SKILL.md Phase 5 must call swe-workbench-reply-and-resolve with '
        '"$OWNER" "$REPO" "$PR" "" "" "$REPLY_BODY" "issue" for PR comments — '
        "empty COMMENT_DATABASEID/THREAD_ID (PR comments have no thread) and explicit issue KIND"
    )


def test_address_feedback_skill_reply_body_embeds_handled_marker():
    """Phase 5 PR-comment reply body must embed the swe-workbench:handled:{id} marker used for re-run dedup."""
    text = _skill_text_with_references()
    assert "swe-workbench:handled:" in text, (
        "SKILL.md Phase 5 must compose the PR-comment reply body with a hidden "
        "<!-- swe-workbench:handled:{comment.id} --> marker — Phase 1's dedup filter "
        "matches on this marker to skip already-replied comments on re-runs"
    )


def test_address_feedback_skill_pr_comments_state_file_in_reap():
    """Phase 7 reap must include $PR_COMMENTS_PATH in both the swe-workbench-clean-state-files
    call and the report loop (issue #667 — sourced from the fetch envelope, not a re-hardcoded literal)."""
    text = SKILL_MD.read_text()
    lines_with_path = [ln for ln in text.splitlines() if "PR_COMMENTS_PATH" in ln]
    assert len(lines_with_path) >= 3, (
        "SKILL.md must reference $PR_COMMENTS_PATH at least three times — the Phase 1 "
        "assignment, the swe-workbench-clean-state-files call, and the post-reap report loop"
    )


def test_address_feedback_skill_pr_comment_skipped_transparency_note():
    """Phase 3 must emit a transparency note for PR comments skipped as already-handled."""
    text = SKILL_MD.read_text()
    assert "PR comment(s) skipped" in text, (
        "SKILL.md Phase 3 must emit a transparency note like "
        "'(N PR comment(s) skipped — already handled.)' since the marker/manual-reply "
        "dedup is lossy by construction"
    )


# --- Reap-on-reject ordering + Phase 7 run-scoped reap ---

def test_address_feedback_skill_state_gate_precedes_run_dir_allocation():
    """Phase 1's OPEN-state gate must be hoisted above swe-workbench-new-run-dir
    allocation — a rejected PR must never allocate $RUN_DIR at all, rather than
    allocating and then leaking it."""
    text = SKILL_MD.read_text()
    gate_idx = text.find('[ "$STATE" = "OPEN" ] ||')
    run_dir_idx = text.find('swe-workbench-new-run-dir address-feedback "$PR"')
    assert gate_idx != -1, "SKILL.md Phase 1 must contain the OPEN-state gate"
    assert run_dir_idx != -1, "SKILL.md Phase 1 must contain the swe-workbench-new-run-dir call"
    assert gate_idx < run_dir_idx, (
        "the OPEN-state gate must precede swe-workbench-new-run-dir allocation — "
        "otherwise a rejected PR leaks $RUN_DIR"
    )


def test_address_feedback_skill_state_gate_reject_reaps_json():
    """The OPEN-state gate's reject branch must reap $JSON before exiting."""
    text = SKILL_MD.read_text()
    line = next(
        (ln for ln in text.splitlines() if ln.strip().startswith('[ "$STATE" = "OPEN" ] ||')),
        None,
    )
    assert line is not None, "SKILL.md Phase 1 must contain the OPEN-state gate line"
    assert 'swe-workbench-clean-state-files "$JSON"' in line, (
        'the OPEN-state gate reject branch must call swe-workbench-clean-state-files "$JSON" '
        "before exiting, to avoid leaking the PR-keyed state file"
    )


def test_address_feedback_skill_phase7_reaps_run_scoped_files():
    """Phase 7 must reap all three run-scoped state files and guard the run-dir
    reap — the ownership-decline and no-open-threads early exits now route
    through Phase 7 before ever creating a worktree, so $RUN_DIR is guarded
    for the one exit (the OPEN-state gate) that precedes its allocation."""
    text = SKILL_MD.read_text()
    phase7_idx = text.find("### Phase 7")
    assert phase7_idx != -1, "SKILL.md must have a ### Phase 7 section"
    next_section = re.search(r'\n## ', text[phase7_idx:])
    phase7_text = text[phase7_idx: phase7_idx + next_section.start()] if next_section else text[phase7_idx:]
    for var in ["$JSON", "$THREADS_PATH", "$PR_COMMENTS_PATH"]:
        assert var in phase7_text, (
            f"Phase 7 must reap {var} — run-scoped state files are reaped on every exit"
        )
    assert "${RUN_DIR:-}" in phase7_text, (
        "Phase 7 must guard the run-dir reap with ${RUN_DIR:-} — $RUN_DIR is unset on "
        "the Phase 1 OPEN-state gate reject path, which never reaches Phase 7"
    )


def test_address_feedback_skill_phase7_worktree_removal_guards_on_wt_unset():
    """Phase 7's worktree-removal block must skip entirely when $WT was never set.

    A Phase-1-only exit (ownership decline, no-open-threads) leaves $WT unset since
    Phase 2 never ran. Without a guard, the block falls into its else branch and calls
    release with an empty --path, which is not a safe input to hand the runtime command.
    """
    text = SKILL_MD.read_text()
    phase7_idx = text.find("### Phase 7")
    assert phase7_idx != -1, "SKILL.md must have a ### Phase 7 section"
    next_section = re.search(r'\n## ', text[phase7_idx:])
    phase7_text = text[phase7_idx: phase7_idx + next_section.start()] if next_section else text[phase7_idx:]
    match = re.search(
        r'if \[ -z "\$\{WT:-\}" \]; then\n.*?\nelse\n.*?swe-workbench-address-feedback-worktree release',
        phase7_text, re.DOTALL,
    )
    assert match, (
        'Phase 7\'s worktree-removal block must open with `if [ -z "${WT:-}" ]; then` '
        "before the else branch that calls swe-workbench-address-feedback-worktree release — "
        "otherwise a Phase-1-only exit would call release with an unset --path"
    )


def test_address_feedback_skill_early_exits_name_phase7():
    """Both the ownership-decline and no-open-threads Phase 1 exits must route
    through Phase 7 — otherwise they leak $JSON, the threads/pr-comments state
    files, and $RUN_DIR."""
    text = SKILL_MD.read_text()
    decline_idx = text.find("Wait for confirmation before continuing.")
    assert decline_idx != -1, "SKILL.md must contain the ownership-decline confirmation prose"
    decline_window = text[decline_idx: decline_idx + 200]
    assert "Phase 7" in decline_window, (
        "the ownership-decline path must state that it runs Phase 7 — Cleanup before exiting"
    )
    no_threads_idx = text.find("No open threads — nothing to address")
    assert no_threads_idx != -1, "SKILL.md must contain the no-open-threads exit message"
    no_threads_window = text[no_threads_idx: no_threads_idx + 200]
    assert "Phase 7" in no_threads_window, (
        "the no-open-threads exit must state that it runs Phase 7 — Cleanup before exiting"
    )
