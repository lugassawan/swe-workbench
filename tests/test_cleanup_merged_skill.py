"""Regression tests for workflow-cleanup-merged and plan-workflow-section fixes.

Defects addressed:
1. cleanup-merged Step 3 must call ExitWorktree action=keep BEFORE cwd anchor and BEFORE
   git pull — the rimba post-merge hook fires during the pull, which can strand the session
   at $HOME if the session is still inside the worktree being deleted.
2. cleanup-merged rimba binary path must handle partial success (worktree gone, branch
   undeleted) by falling through to Step 5 rather than aborting.
3. plan-workflow-section Phase 1 must not present using-git-worktrees as a peer-primary
   path alongside rimba — it causes EnterWorktree to mangle branch names.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-cleanup-merged" / "SKILL.md"
TEMPLATE = ROOT / "skills" / "workflow-development" / "templates" / "plan-workflow-section.md"


def test_cleanup_merged_step3_calls_exit_worktree_before_cwd_anchor():
    """Step 3 must call ExitWorktree action=keep BEFORE MAIN_REPO derivation.

    The rimba post-merge hook fires during git pull in Step 3. If the session is still
    inside the worktree when pull runs, the hook deletes the cwd and rimba's subsequent
    git branch -D fires from a dead directory — leaving the branch alive and the session
    stranded at $HOME. ExitWorktree action=keep must precede MAIN_REPO derivation.
    """
    body = SKILL.read_text()
    assert "### Step 3" in body, "Step 3 section must exist"
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]

    # Structural check: ExitWorktree must be in sub-section 3a (before 3b)
    assert "**3a." in step3, "Step 3 must have a **3a. sub-section"
    assert "**3b." in step3, "Step 3 must have a **3b. sub-section"
    section_3a = step3.split("**3b.")[0]
    assert "ExitWorktree" in section_3a, (
        "ExitWorktree must be in sub-section 3a (before **3b.), not a later section"
    )
    assert "action=keep" in section_3a, (
        "ExitWorktree action=keep must appear in sub-section 3a"
    )

    # Ordering check: MAIN_REPO= and git pull are in 3b/3c, after 3a
    section_3bc = step3.split("**3b.")[1]
    assert "MAIN_REPO=" in section_3bc, "MAIN_REPO= derivation must be in 3b or later"
    assert "git pull" in section_3bc, "git pull must be in 3b or later (after ExitWorktree)"


def test_cleanup_merged_step3_exit_worktree_is_no_op_when_not_entered():
    """Step 3 ExitWorktree instruction must explicitly note it is a no-op when
    EnterWorktree was never called, so agents don't abort when the tool is absent."""
    body = SKILL.read_text()
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]

    assert "no-op" in step3.lower() or "not entered" in step3.lower() or "never called" in step3.lower(), (
        "Step 3 must clarify that ExitWorktree is a no-op when the session did not "
        "enter via EnterWorktree — agents must not abort if the tool is unavailable"
    )


def test_cleanup_merged_rimba_path_handles_partial_success():
    """rimba binary path must recover from 'worktree gone but branch undeleted'.

    When rimba's child process inherits a dead cwd (the worktree directory was already
    removed by the hook fast path), rimba remove can succeed at deleting the worktree
    directory but fail at git branch -D because the subprocess cwd is gone. The skill
    must treat this as partial success and fall through to Step 5 for branch cleanup.
    """
    body = SKILL.read_text()
    assert "### rimba (MCP / binary)" in body, "rimba strategy section must exist"
    assert "### shell fallback" in body, "shell fallback section must exist as boundary"
    rimba_block = body.split("### rimba (MCP / binary)")[1].split("### shell fallback")[0]

    has_partial = "partial" in rimba_block.lower()
    has_fallthrough = "fall through to Step 5" in rimba_block or "fall through to step 5" in rimba_block.lower()

    assert has_partial and has_fallthrough, (
        "rimba strategy Failure handling must mention both 'partial' (success) "
        "and 'fall through to Step 5' — both phrases are required to catch "
        "regressions where only one phrase is present but not the other"
    )


def test_cleanup_merged_common_mistakes_covers_exit_worktree():
    """Common Mistakes table must warn about skipping ExitWorktree before rimba."""
    body = SKILL.read_text()
    assert "## Common Mistakes" in body, "Common Mistakes section must exist"
    mistakes = body.split("## Common Mistakes")[1]

    assert "ExitWorktree" in mistakes, (
        "Common Mistakes must include a row about skipping ExitWorktree action=keep "
        "before rimba removal in a session entered via EnterWorktree"
    )


def test_phase1_template_rimba_is_primary_not_peer():
    """Phase 1 template must present rimba as the primary path.

    The plan-workflow-section template must not list using-git-worktrees as a peer-primary
    path alongside rimba add. When agents see them as peers, they invoke
    superpowers:using-git-worktrees, whose Step 1a steers toward EnterWorktree name=…
    which mangles slash-containing branch names (e.g. feature/101-foo becomes
    worktree-feature+101-foo).
    """
    body = TEMPLATE.read_text()

    # Phase 1 content: between "Phase 1" and "Phase 2"
    assert "### Phase 1" in body, "Template must contain ### Phase 1 section"
    phase1 = body.split("### Phase 1")[1]
    if "### Phase 2" in phase1:
        phase1 = phase1.split("### Phase 2")[0]

    assert "rimba" in phase1, "Phase 1 must mention rimba as the branch creation tool"

    rimba_idx = phase1.find("rimba")
    superp_idx = phase1.find("using-git-worktrees")

    # using-git-worktrees must either be absent from Phase 1, or appear AFTER rimba
    # and only in a fallback/conditional context
    if superp_idx != -1:
        assert rimba_idx < superp_idx, (
            "rimba must appear before using-git-worktrees in Phase 1 "
            f"(rimba at {rimba_idx}, using-git-worktrees at {superp_idx})"
        )
        # Verify using-git-worktrees is framed as a fallback (not a peer primary)
        context_around = phase1[max(0, superp_idx - 80):superp_idx + 80].lower()
        fallback_keywords = ["fallback", "else", "absent", "without", "only when", "not found", "unavailable"]
        assert any(kw in context_around for kw in fallback_keywords), (
            "using-git-worktrees in Phase 1 must be framed as a fallback "
            "(preceded by a conditional like 'else', 'fallback', 'absent', etc.), "
            f"not as a peer primary option. Context: '{context_around}'"
        )


def test_cleanup_merged_documents_hook_interrupted_recovery():
    """SKILL.md must document the HOOK_INTERRUPTED signal and its recovery (issue #496).

    sync-and-verify.sh now emits a second stdout field, HOOK_INTERRUPTED=0|1, detecting
    a registered worktree whose directory is missing on disk (a timeout or external kill
    landed mid-rm inside the rimba post-merge hook). The skill must document the signal,
    the Failure Mode Table row, and the manual `git worktree prune` recovery — the script
    is verify-only and never auto-remediates.
    """
    body = SKILL.read_text()

    assert "HOOK_INTERRUPTED" in body, (
        "SKILL.md must mention the HOOK_INTERRUPTED stdout field"
    )

    assert "## Failure Mode Table" in body, "Failure Mode Table section must exist"
    failure_table = body.split("## Failure Mode Table")[1].split("## Common Mistakes")[0]

    assert "HOOK_INTERRUPTED=1" in failure_table, (
        "Failure Mode Table must have a row keyed on HOOK_INTERRUPTED=1"
    )
    assert "git worktree prune" in failure_table, (
        "Failure Mode Table's partial-deletion row must name the recovery command "
        "git worktree prune"
    )


def test_cleanup_merged_step5_delegates_to_delete_branches_script():
    """Step 5 must delegate branch deletion to delete-branches.sh via eval.

    The inline git branch -D / git push origin --delete commands were extracted
    into delete-branches.sh (issue #449). The skill slice for Step 5 must
    reference the script and document both KEY=VALUE outputs; the old inline
    commands must not appear within the Step 5 slice (they may still appear in
    prose tables elsewhere, so the check is slice-scoped).
    """
    body = SKILL.read_text()

    assert "### Step 5 — Delete Branches" in body, (
        "Step 5 heading must be '### Step 5 — Delete Branches'"
    )
    assert "### Step 6 — Report" in body, (
        "Step 7 must be renumbered to Step 6 after the merge"
    )

    step5_slice = body.split("### Step 5 — Delete Branches")[1].split("### Step 6")[0]

    assert "delete-branches.sh" in step5_slice, (
        "Step 5 slice must reference delete-branches.sh"
    )
    assert "LOCAL_DELETED" in step5_slice, (
        "Step 5 slice must document LOCAL_DELETED output"
    )
    assert "REMOTE_DELETED" in step5_slice, (
        "Step 5 slice must document REMOTE_DELETED output"
    )

    # The old inline commands must not appear within Step 5 (they were extracted)
    assert "git branch -D <headRefName>" not in step5_slice, (
        "git branch -D <headRefName> must not appear inline in Step 5 — "
        "it was extracted into delete-branches.sh"
    )
    assert "git push origin --delete <headRefName>" not in step5_slice, (
        "git push origin --delete <headRefName> must not appear inline in Step 5 — "
        "it was extracted into delete-branches.sh"
    )


# ---------------------------------------------------------------------------
# No-op ambiguity reframe (#497)
# ---------------------------------------------------------------------------

def test_step3_no_longer_claims_no_op_confirms_cd_entry():
    """Step 3a must not assert an ExitWorktree no-op as definitive proof of cd-entry.

    A no-op means only "no active EnterWorktree session" — caused by either
    cd-fallback entry OR compaction dropping harness-level tracking (#497). The
    two are indistinguishable from ExitWorktree's output alone.
    """
    body = SKILL.read_text()
    assert "confirming cd-entry" not in body, (
        "SKILL.md must not claim an ExitWorktree no-op confirms cd-entry with "
        "certainty — compaction-dropped tracking presents identically."
    )


def test_step3_names_compaction_as_alternative_cause():
    body = SKILL.read_text()
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]
    assert "compaction" in step3.lower(), (
        "Step 3 must name compaction as an alternative cause of an ExitWorktree no-op."
    )


def test_common_mistakes_no_op_row_reframed():
    """The Common Mistakes row about cd-fallback ExitWorktree must not assert
    cd-entry with certainty either — same reframe as Step 3."""
    body = SKILL.read_text()
    assert "## Common Mistakes" in body, "Common Mistakes section must exist"
    mistakes = body.split("## Common Mistakes")[1]
    assert "confirming cd-entry" not in mistakes and "confirms cd-entry" not in mistakes, (
        "Common Mistakes table must not assert an ExitWorktree no-op confirms "
        "cd-entry with certainty."
    )
    assert "compaction" in mistakes.lower(), (
        "Common Mistakes table must name compaction as an alternative cause "
        "wherever it discusses the ExitWorktree no-op."
    )
