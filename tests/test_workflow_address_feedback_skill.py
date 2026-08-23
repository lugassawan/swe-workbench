# tests/test_workflow_address_feedback_skill.py

"""Tests for the workflow-address-feedback skill (closes #218)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import validate
from conftest import _CLEAN_ENV

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


def test_address_feedback_skill_clarified_no_resolve():
    """SKILL.md must state that CLARIFIED threads are not resolved (reply only)."""
    text = SKILL_MD.read_text()
    assert re.search(r"CLARIFIED.*[Nn]o resolve|[Nn]o resolve.*CLARIFIED|CLARIFIED.*reply only", text), (
        "SKILL.md must state that CLARIFIED threads get a reply but are NOT resolved "
        "(only ADDRESSED threads trigger resolveReviewThread)"
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
    """Phase 7 must remove the worktree via rimba but KEEP the PR branch (issue #643)."""
    text = SKILL_MD.read_text()
    assert re.search(
        r'rimba remove ["\']?\$PR_BRANCH["\']? --force --keep-branch', text
    ), (
        'SKILL.md Phase 7 must include: rimba remove "$PR_BRANCH" --force --keep-branch — '
        "the worktree is disposable but the local PR head branch must be preserved "
        "(rimba remove deletes the branch without --keep-branch)"
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


# --- Worktree create-path contract — issue #643 ---

def test_address_feedback_skill_create_uses_pr_branch_task_form():
    """Phase 2 must create the worktree from the PR branch name, not the pr:<num> task form (AC#1)."""
    text = _skill_text_with_references()
    assert 'rimba add "$PR_BRANCH" --source "origin/$PR_BRANCH"' in text, (
        'SKILL.md Phase 2 must invoke: rimba add "$PR_BRANCH" --source "origin/$PR_BRANCH" — '
        "the task-form add names the branch after the PR branch itself"
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


def test_address_feedback_skill_create_omits_skip_flags():
    """Phase 2 create must let rimba fully initialize — no --skip-deps/--skip-hooks (AC#2/#3)."""
    text = _skill_text_with_references()
    # No rimba add invocation may carry either skip flag.
    for m in re.finditer(r"rimba add[^\n]*", text):
        assert "--skip-deps" not in m.group(0), (
            f"rimba add must not pass --skip-deps: {m.group(0)!r}"
        )
        assert "--skip-hooks" not in m.group(0), (
            f"rimba add must not pass --skip-hooks: {m.group(0)!r}"
        )
    assert re.search(r"Never pass either flag|must not pass either", text), (
        "Common-mistakes table must forbid skip flags on the Phase 2 create so rimba "
        "installs deps and runs hooks with no separate bootstrap step"
    )


def test_address_feedback_skill_create_fetches_pr_branch_first():
    """Task-form rimba add does not fetch — Phase 2 must fetch origin/$PR_BRANCH itself."""
    text = _skill_text_with_references()
    assert 'git fetch origin "$PR_BRANCH"' in text, (
        'SKILL.md Phase 2 must run: git fetch origin "$PR_BRANCH" before rimba add — '
        "task-mode add never fetches, and --source origin/$PR_BRANCH must be current"
    )


def test_address_feedback_skill_create_handles_existing_local_branch():
    """Local branch already present → git worktree add checkout + rimba deps install (no re-add error)."""
    text = _skill_text_with_references()
    assert 'git show-ref --verify --quiet "refs/heads/$PR_BRANCH"' in text, (
        "SKILL.md Phase 2 must probe refs/heads/$PR_BRANCH — rimba add hard-errors "
        "'branch already exists' when the local PR branch is present"
    )
    assert 'git worktree add "$WT" "$PR_BRANCH"' in text, (
        'SKILL.md Phase 2 must check out the existing local branch: git worktree add "$WT" "$PR_BRANCH"'
    )
    assert 'rimba deps install "$PR_BRANCH"' in text, (
        "SKILL.md Phase 2 must run rimba deps install on the existing-branch path so it "
        "still gets dependency installation without a separate bootstrap step"
    )


def test_address_feedback_skill_create_verifies_branch_and_falls_back():
    """Post-create verification: worktree branch must equal $PR_BRANCH; mismatch → git fallback."""
    text = _skill_text_with_references()
    assert 'WT_BRANCH=$(git -C "$WT" rev-parse --abbrev-ref HEAD)' in text, (
        "SKILL.md Phase 2 must verify the checked-out branch after rimba add — rimba "
        "re-prefixes non-conventional branch names (DefaultPrefixType is feature/)"
    )
    assert 'git worktree add -b "$PR_BRANCH" "$WT" "origin/$PR_BRANCH"' in text, (
        'SKILL.md Phase 2 fallback must create the branch directly: '
        'git worktree add -b "$PR_BRANCH" "$WT" "origin/$PR_BRANCH"'
    )


def test_address_feedback_skill_create_reconciles_stale_local_branch():
    """Existing-branch checkout must reconcile against origin — ff-only when behind, warn when diverged."""
    text = _skill_text_with_references()
    assert 'git -C "$WT" merge --ff-only "origin/$PR_BRANCH"' in text, (
        "SKILL.md Phase 2 must fast-forward a strictly-behind local $PR_BRANCH — "
        "otherwise Phase 4 pushes are rejected non-FF when the PR advanced between runs"
    )
    assert 'diverged from origin' in text, (
        "SKILL.md Phase 2 must warn loudly when local $PR_BRANCH diverged from origin "
        "(needs rebase before Phase 4)"
    )
    assert '[ -e "$WT/.git" ]' in text, (
        'SKILL.md Phase 2 must gate on the worktree existing ([ -e "$WT/.git" ]) before '
        "proceeding — a dangling $WT fails confusingly in Phase 4 and mis-cleans in Phase 7"
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
    # Must look up the branch ref inside the porcelain output (branch passed as an awk
    # variable — a regex-interpolated branch name breaks on "/" in conventional names).
    assert 'awk -v b="refs/heads/$PR_BRANCH"' in text, (
        'SKILL.md Phase 2 must pass the branch to awk via -v (exact $0 == "branch " b match) — '
        "interpolating $PR_BRANCH into a regex literal dies on slashed branch names"
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
    """Phase 6 fallback must invoke swe-workbench-clean-ephemeral, not bare rm -rf "$WT"."""
    text = SKILL_MD.read_text()
    assert "swe-workbench-clean-ephemeral" in text, (
        "SKILL.md Phase 6 fallback must use swe-workbench-clean-ephemeral — "
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
        f"Found bare rm -rf \"$WT\" lines in Phase 6 (should use swe-workbench-clean-ephemeral):\n"
        + "\n".join(lines_with_rm)
    )


# --- State-file cleanup assertions (issue #428) ---

def test_address_feedback_skill_deletes_three_state_files():
    """Phase 5 success path must invoke swe-workbench-clean-state-files with all three state files."""
    text = SKILL_MD.read_text()
    assert "swe-workbench-clean-state-files" in text, (
        "SKILL.md must call swe-workbench-clean-state-files to remove address-feedback state files"
    )
    assert "/tmp/swe-workbench-address-feedback/${PR}.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-address-feedback/${PR}.json to swe-workbench-clean-state-files"
    )
    assert "/tmp/swe-workbench-address-feedback/${PR}-threads.json" in text, (
        "SKILL.md must pass /tmp/swe-workbench-address-feedback/${PR}-threads.json to swe-workbench-clean-state-files"
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


def test_address_feedback_skill_fetches_pr_comments_paginated():
    """Phase 1 must fetch PR-level conversation comments via the paginated issues comments endpoint."""
    text = SKILL_MD.read_text()
    assert "issues/${PR}/comments" in text, (
        "SKILL.md Phase 1 must fetch repos/{owner}/{repo}/issues/${PR}/comments "
        "(PR-level conversation comments, distinct from review-thread comments)"
    )
    assert "--paginate" in text, (
        "SKILL.md Phase 1 must paginate the issues/comments fetch (--paginate) — "
        "a PR can have more than one page of conversation comments"
    )


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


def test_address_feedback_skill_excludes_bots_and_author_from_pr_comments():
    """Phase 1's PR-comment filter must exclude bot comments and the PR author's own comments."""
    text = SKILL_MD.read_text()
    assert "Bot" in text and "[bot]" in text, (
        "SKILL.md must describe excluding bot comments (user.type == Bot or a "
        "login ending in [bot]) from PR-level comment triage"
    )
    assert "AUTHOR_LOGIN" in text and "eligible" in text, (
        "SKILL.md must describe excluding the PR author's own comments "
        "(user.login == $AUTHOR_LOGIN) via the eligible filter"
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
    """Phase 5 reap must include ${PR}-pr-comments.json in both the swe-workbench-clean-state-files call and the report loop."""
    text = SKILL_MD.read_text()
    assert "/tmp/swe-workbench-address-feedback/${PR}-pr-comments.json" in text, (
        "SKILL.md must reference /tmp/swe-workbench-address-feedback/${PR}-pr-comments.json "
        "for state-file cleanup"
    )
    lines_with_path = [ln for ln in text.splitlines() if "${PR}-pr-comments.json" in ln]
    assert len(lines_with_path) >= 2, (
        "SKILL.md must reference ${PR}-pr-comments.json at least twice — once in the "
        "swe-workbench-clean-state-files call and once in the post-reap report loop"
    )


def test_address_feedback_skill_pr_comment_skipped_transparency_note():
    """Phase 3 must emit a transparency note for PR comments skipped as already-handled."""
    text = SKILL_MD.read_text()
    assert "PR comment(s) skipped" in text, (
        "SKILL.md Phase 3 must emit a transparency note like "
        "'(N PR comment(s) skipped — already handled.)' since the marker/manual-reply "
        "dedup is lossy by construction"
    )


# --- Executable coverage of the embedded Phase 1 jq filter (issue #473) ---
#
# The filter's exclusion/dedup logic lives inside a jq program embedded in SKILL.md
# prose, not in a standalone script. Regex assertions on the surrounding text can't
# catch a logic bug inside that program (e.g. an unanchored substring match). These
# tests extract the actual program text and run it through real jq, so a regression
# in the embedded logic fails here instead of shipping silently.

_JQ_AVAILABLE = shutil.which("jq") is not None


def _extract_pr_comments_jq_program() -> str:
    text = SKILL_MD.read_text()
    block = re.search(r"```bash\ngh api --paginate.*?\n```", text, re.DOTALL)
    assert block, "Phase 1 PR-comments fetch code block not found in SKILL.md"
    program = re.search(r'--arg me "\$CURRENT_USER" \'\n(.*?)\n  \' >', block.group(0), re.DOTALL)
    assert program, "jq program not found within the Phase 1 fetch code block"
    return program.group(1)


def _run_pr_comments_filter(comments: list[dict], author: str, me: str) -> list[dict]:
    program = _extract_pr_comments_jq_program()
    result = subprocess.run(
        ["jq", "--arg", "author", author, "--arg", "me", me, program],
        input=json.dumps(comments), capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, f"jq filter failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.mark.skipif(not _JQ_AVAILABLE, reason="jq binary not available")
def test_pr_comments_jq_filter_drops_bots_and_author():
    comments = [
        {"id": 1, "user": {"login": "some-bot", "type": "Bot"}, "body": "lgtm", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "user": {"login": "renovate[bot]", "type": "User"}, "body": "bump", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 3, "user": {"login": "pr-author", "type": "User"}, "body": "self note", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 4, "user": {"login": "reviewer1", "type": "User"}, "body": "please fix X", "created_at": "2026-01-01T00:00:00Z"},
    ]
    result = _run_pr_comments_filter(comments, author="pr-author", me="pr-author")
    ids = {c["id"] for c in result}
    assert ids == {4}, f"bot/[bot]/author comments must be dropped entirely; got ids {ids}"
    assert result[0]["eligible"] is True


@pytest.mark.skipif(not _JQ_AVAILABLE, reason="jq binary not available")
def test_pr_comments_jq_filter_drops_current_user_on_non_author_run():
    """Regression test: on a non-author run, the runner's own past marker-bearing
    reply must not resurface as a fresh triage candidate (duplicate-reply spam)."""
    comments = [
        {"id": 20, "user": {"login": "reviewer6", "type": "User"}, "body": "please fix V", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 21, "user": {"login": "maintainer-x", "type": "User"}, "body": "done <!-- swe-workbench:handled:20 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = _run_pr_comments_filter(comments, author="pr-author", me="maintainer-x")
    by_id = {c["id"]: c for c in result}
    assert 21 not in by_id, (
        "comment 21 was authored by $me (the non-author runner) and must be dropped "
        "as a candidate entirely, not resurface with eligible: false"
    )
    assert by_id[20]["eligible"] is False, (
        "comment 20 must still be marker-deduped via owner comment 21's marker"
    )


@pytest.mark.skipif(not _JQ_AVAILABLE, reason="jq binary not available")
def test_pr_comments_jq_filter_marker_dedup():
    comments = [
        {"id": 5, "user": {"login": "reviewer2", "type": "User"}, "body": "please fix Y", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 6, "user": {"login": "pr-author", "type": "User"}, "body": "done <!-- swe-workbench:handled:5 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = _run_pr_comments_filter(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[5]["eligible"] is False, "a comment whose own marker is present must be ineligible"


@pytest.mark.skipif(not _JQ_AVAILABLE, reason="jq binary not available")
def test_pr_comments_jq_filter_marker_match_is_anchored():
    """Regression test: a marker for id 1234 must not dedup-suppress unrelated id 123
    via an unanchored substring match (id 123 is a numeric prefix of 1234)."""
    comments = [
        {"id": 123, "user": {"login": "reviewer3", "type": "User"}, "body": "please fix Z", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 999, "user": {"login": "pr-author", "type": "User"}, "body": "done <!-- swe-workbench:handled:1234 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = _run_pr_comments_filter(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[123]["eligible"] is True, (
        "comment 123 must stay eligible — the owner's marker is for a different "
        "comment (1234) that merely shares a numeric prefix; an unanchored "
        "contains() match would incorrectly suppress it"
    )


@pytest.mark.skipif(not _JQ_AVAILABLE, reason="jq binary not available")
def test_pr_comments_jq_filter_manual_reply_dedup():
    comments = [
        {"id": 7, "user": {"login": "reviewer4", "type": "User"}, "body": "please fix W", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 8, "user": {"login": "pr-author", "type": "User"}, "body": "thanks, will look", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = _run_pr_comments_filter(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[7]["eligible"] is False, (
        "a marker-less owner comment posted after the reviewer comment counts as a "
        "manual reply and must dedup-suppress it"
    )


@pytest.mark.skipif(not _JQ_AVAILABLE, reason="jq binary not available")
def test_pr_comments_jq_filter_own_marker_replies_excluded_from_manual_heuristic():
    """A prior marker-bearing tool reply must not itself count as a 'manual reply' that
    over-suppresses a different, still-open reviewer comment posted before it."""
    comments = [
        {"id": 9, "user": {"login": "reviewer5", "type": "User"}, "body": "issue A", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 10, "user": {"login": "reviewer5", "type": "User"}, "body": "issue B", "created_at": "2026-01-01T01:00:00Z"},
        {"id": 11, "user": {"login": "pr-author", "type": "User"}, "body": "done <!-- swe-workbench:handled:10 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = _run_pr_comments_filter(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[10]["eligible"] is False, "comment 10's own marker must dedup-suppress it"
    assert by_id[9]["eligible"] is True, (
        "comment 9 must stay eligible — the only later owner comment is a "
        "marker-bearing tool reply for a different comment, which the manual-reply "
        "heuristic must ignore (it only counts marker-less owner comments)"
    )
