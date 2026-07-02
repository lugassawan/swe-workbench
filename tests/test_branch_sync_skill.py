"""Structural tests for workflow-branch-sync/SKILL.md (issue #485).

Pins the two sharp edges from the plan:
1. git's --ours/--theirs inversion under rebase vs merge.
2. rimba's inverted sync defaults (rebase by default, pushes by default).
Plus the never-auto-push / force-with-lease-only-under-rebase invariants.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-branch-sync" / "SKILL.md"


def _body():
    return SKILL.read_text(encoding="utf-8")


def test_skill_file_exists():
    assert SKILL.is_file(), "skills/workflow-branch-sync/SKILL.md must exist"


def test_frontmatter_has_name_and_orchestrator():
    body = _body()
    assert body.startswith("---")
    frontmatter = body.split("---")[1]
    assert "name: workflow-branch-sync" in frontmatter
    assert "orchestrator: true" in frontmatter


def test_never_auto_push_documented():
    body = _body()
    assert "Never auto-push" in body or "never auto-push" in body.lower()
    assert "## What This Skill Does NOT Do" in body
    not_do = body.split("## What This Skill Does NOT Do")[1].split("##")[0]
    assert "push" in not_do.lower()


def test_rebase_push_uses_force_with_lease():
    body = _body()
    assert "--force-with-lease" in body
    # force-with-lease must appear specifically tied to the rebase push branch
    assert "SYNC_STRATEGY` was `rebase`" in body or "sync_strategy was rebase" in body.lower()


def test_step6_push_branches_on_sync_strategy_not_operation():
    """Regression: Step 6 must branch push logic on SYNC_STRATEGY, never OPERATION —
    OPERATION is `none` on a clean sync (the common case), so an OPERATION-keyed
    branch has no push path at all for a clean --rebase sync."""
    body = _body()
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]
    assert "SYNC_STRATEGY" in step3
    assert "merge|rebase" in step3 or "merge | rebase" in step3

    step6 = body.split("### Step 6")[1].split("## ")[0]
    push_lines = [ln for ln in step6.splitlines() if "git push" in ln]
    assert push_lines, "Step 6 must contain the push branching bullets"
    for ln in push_lines:
        # The decision clause is the first bolded span ("Yes, and X was Y") and
        # must key off SYNC_STRATEGY. OPERATION may still appear later in the
        # line as explanatory prose (contrasting why OPERATION would be wrong).
        parts = ln.split("**")
        decision_clause = parts[1] if len(parts) >= 2 else ln
        assert "SYNC_STRATEGY" in decision_clause, (
            f"push branch decision clause must key off SYNC_STRATEGY: {ln!r}"
        )
        assert "OPERATION" not in decision_clause, (
            f"push branch decision clause must not key off OPERATION: {ln!r}"
        )


def test_plain_force_push_never_used():
    body = _body()
    for line in body.splitlines():
        stripped = line.strip()
        if "git push --force" in stripped and "--force-with-lease" not in stripped:
            raise AssertionError(f"plain 'git push --force' found (must be --force-with-lease): {stripped!r}")


def test_guard_refuses_on_default_branch_and_detached_head():
    body = _body()
    assert "### Step 1" in body
    step1 = body.split("### Step 1")[1].split("### Step 2")[0]
    assert "IS_DEFAULT=1" in step1 and "refuse" in step1.lower()
    assert "DETACHED=1" in step1 and "refuse" in step1.lower()
    assert "DIRTY" in step1 and ("stash" in step1.lower())


def test_common_mistakes_documents_ours_theirs_inversion():
    body = _body()
    assert "## Common Mistakes" in body
    mistakes = body.split("## Common Mistakes")[1]
    assert "--ours" in mistakes and "--theirs" in mistakes
    assert "invert" in mistakes.lower()
    assert "apply-resolution.sh" in mistakes


def test_step1_stash_sets_flag_and_step6_restores_it():
    """Regression: a pre-sync stash must be restorable — Step 1 must set a
    STASHED flag when it stashes, and Step 6 must pop it before reporting,
    handling a conflicting pop the same way a file conflict is surfaced."""
    body = _body()
    step1 = body.split("### Step 1")[1].split("### Step 2")[0]
    assert "STASHED=1" in step1

    step6 = body.split("### Step 6")[1].split("## ")[0]
    assert "STASHED=1" in step6
    assert "git stash pop" in step6
    assert "git stash drop" in step6, "a conflicting pop must be followed by an explicit drop after resolution"


def test_common_mistakes_documents_rimba_inverted_defaults():
    body = _body()
    mistakes = body.split("## Common Mistakes")[1]
    assert "rebases by default" in mistakes.lower() or "rebase by default" in mistakes.lower()
    assert "pushes by default" in mistakes.lower() or "push by default" in mistakes.lower()
    assert "no_push" in mistakes or "--no-push" in mistakes


def test_common_mistakes_documents_no_hardcoded_main():
    body = _body()
    mistakes = body.split("## Common Mistakes")[1]
    assert "main" in mistakes.lower()
    assert "hardcode" in mistakes.lower() or "hard-code" in mistakes.lower()


def test_common_mistakes_documents_rebase_repauses():
    body = _body()
    mistakes = body.split("## Common Mistakes")[1]
    assert "rebase --continue" in mistakes
    assert "pause" in mistakes.lower() or "loop back" in mistakes.lower()


def test_step3_documents_rimba_no_push_always_passed():
    body = _body()
    assert "### Step 3" in body
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]
    assert "no_push: true" in step3
    assert "--no-push" in step3
    assert "always" in step3.lower()


def test_step3_translation_table_present():
    body = _body()
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]
    assert "merge: true" in step3
    assert "--merge --no-push" in step3
    assert "--no-push" in step3


def test_step5_never_calls_ours_theirs_inline():
    body = _body()
    assert "### Step 5" in body
    step5 = body.split("### Step 5")[1].split("### Step 6")[0]
    assert "apply-resolution.sh" in step5
    # The skill must not instruct calling git checkout --ours/--theirs as an
    # actual invocation (file-separator form) directly in this step — mentioning
    # the flag names in prose (e.g. "never call --ours/--theirs inline") is fine.
    assert "git checkout --ours --" not in step5
    assert "git checkout --theirs --" not in step5


def test_step5_shows_both_sides_before_prompting():
    body = _body()
    step5 = body.split("### Step 5")[1].split("### Step 6")[0]
    assert "keep-mine" in step5
    assert "keep-main" in step5
    assert "manual" in step5
    assert "both sides" in step5.lower()


def test_step6_never_auto_pushes():
    body = _body()
    assert "### Step 6" in body
    step6 = body.split("### Step 6")[1].split("## ")[0]
    assert "Never auto-push" in step6
    assert "Push now?" in step6 or "push now" in step6.lower()


def test_failure_mode_table_present():
    body = _body()
    assert "## Failure Mode Table" in body


def test_when_to_invoke_references_sync_command():
    body = _body()
    assert "/swe-workbench:sync" in body


def test_step3_task_id_derivation_documents_known_prefixes():
    """Regression: the task-ID derivation logic must pin the exact prefix
    list so it can't silently drift from workflow-development's branch-prefix
    taxonomy (feature/, bugfix/, hotfix/, docs/, test/, chore/)."""
    body = _body()
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]
    assert "task identifier" in step3.lower()
    for prefix in ("feature/", "bugfix/", "hotfix/", "docs/", "test/", "chore/"):
        assert f"`{prefix}`" in step3, f"Step 3 must document stripping the `{prefix}` prefix"


def test_step3_rimba_routing_is_try_then_fallback_not_precheck():
    """Regression: Step 3 must not gate the binary path on an unverifiable
    'is this a rimba worktree' precheck — it must try the call and fall
    through on rimba's actual 'worktree not found' error."""
    body = _body()
    step3 = body.split("### Step 3")[1].split("### Step 4")[0]
    assert "never pre-check" in step3.lower() or "not knowable in advance" in step3.lower()
    assert "worktree not found for task" in step3
    assert "fall through" in step3.lower()
    # The old ambiguous precheck phrasing must be gone.
    assert "current worktree is a rimba-managed task worktree" not in step3


def test_step4_captures_detect_conflicts_output_once():
    """Regression: detect-conflicts.sh must be invoked once and split, not
    called twice (which could observe different repo state between calls)."""
    body = _body()
    step4 = body.split("### Step 4")[1].split("### Step 5")[0]
    # Count actual invocations (the $_SCRIPTS/... call form), not prose mentions
    # of the filename in the explanatory sentence.
    assert step4.count("$_SCRIPTS/detect-conflicts.sh") == 1
    assert "_DETECT_OUT" in step4


def test_step5_manual_path_checks_for_conflict_markers_before_staging():
    """Regression: staging a manually-resolved file on confirmation alone can
    commit literal conflict-marker text if a hunk was missed."""
    body = _body()
    step5 = body.split("### Step 5")[1].split("### Step 6")[0]
    assert "manual" in step5.lower()
    manual_line = next(
        (ln for ln in step5.splitlines() if "**manual**:" in ln), ""
    )
    assert manual_line, "Step 5 must have a '- **manual**: ...' bullet"
    assert "marker" in manual_line.lower()
    assert "grep" in manual_line.lower()


def test_failure_mode_table_documents_delete_modify_and_rimba_fallback():
    body = _body()
    table = body.split("## Failure Mode Table")[1].split("## Common Mistakes")[0]
    assert "worktree not found for task" in table
    assert "does not have our/their version" in table or "does not have" in table
