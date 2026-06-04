"""Regression tests for workflow-development rimba add documentation defects.

Defects addressed:
1. SKILL.md and plan-workflow-section.md never document the five branch-prefix flags
   (--bugfix, --hotfix, --docs, --test, --chore), so agents always emit bare
   `rimba add <task>` and get feature/<slug> for every work type.
2. SKILL.md Phase 1 mentions `--skip-deps` / `--skip-hooks` nowhere, so TDD-heavy
   plans race against rimba's dep-install pipeline before the first test run.
3. SKILL.md line ~94 uses wrong prefixes `feat/`, `fix/` — rimba actually produces
   `feature/`, `bugfix/`, `hotfix/`, `docs/`, `test/`, `chore/`.
4. SKILL.md Phase 1 does not document the <service>/<task> monorepo scope pattern
   or the majority-service heuristic for cross-cutting changes.
5. SKILL.md and plan-workflow-section.md do not document that `Path:` is printed
   before deps finish, so agents idle during long installs instead of implementing
   in parallel and reconciling via `git stash` → RED → `git stash pop` → GREEN.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-development" / "SKILL.md"
TEMPLATE = ROOT / "skills" / "workflow-development" / "templates" / "plan-workflow-section.md"


def _phase1_section(text: str) -> str:
    """Extract the Phase 1 block from a document.

    Uses '### Phase 1' to avoid false matches in TOC/integration-map prose
    that references 'Phase 1' before the actual section heading.
    """
    marker = "### Phase 1"
    assert marker in text, "Document must contain a '### Phase 1' section heading"
    phase1 = text.split(marker)[1]
    if "### Phase 2" in phase1:
        phase1 = phase1.split("### Phase 2")[0]
    return phase1


# ---------------------------------------------------------------------------
# Defect 1 — Missing flag documentation
# ---------------------------------------------------------------------------


def test_skill_documents_all_five_branch_prefix_flags():
    """SKILL.md Phase 1 must enumerate all five rimba branch-prefix flags.

    Without these flags documented, agents always emit bare `rimba add <task>`
    and every branch gets the default `feature/` prefix regardless of work type.
    """
    body = SKILL.read_text()
    phase1 = _phase1_section(body)

    for flag in ("--bugfix", "--hotfix", "--docs", "--test", "--chore"):
        assert flag in phase1, (
            f"SKILL.md Phase 1 must document the rimba flag '{flag}' so agents "
            f"can pick the correct branch prefix for non-feature work"
        )


def test_skill_no_longer_uses_wrong_feat_fix_prefixes():
    """SKILL.md Phase 1 must not claim rimba produces `feat/` or `fix/` prefixes.

    Rimba's actual prefixes are feature/, bugfix/, hotfix/, docs/, test/, chore/.
    The wrong prefix names actively mislead agents building their mental model.
    Both correct prefixes (feature/ and bugfix/) must appear in Phase 1.
    """
    body = SKILL.read_text()
    phase1 = _phase1_section(body)

    # Wrong prefixes must be absent (backtick-quoted as they appear in the prose)
    assert "`feat/`" not in phase1, (
        "SKILL.md Phase 1 must not use `feat/` as a branch prefix — "
        "rimba produces `feature/`, not `feat/`"
    )
    assert "`fix/`" not in phase1, (
        "SKILL.md Phase 1 must not use `fix/` as a branch prefix — "
        "rimba produces `bugfix/`, not `fix/`"
    )

    # Correct prefixes must be present
    assert "feature/" in phase1, "SKILL.md Phase 1 must document the `feature/` prefix"
    assert "bugfix/" in phase1, "SKILL.md Phase 1 must document the `bugfix/` prefix"


def test_template_no_longer_uses_wrong_feat_fix_prefixes():
    """plan-workflow-section.md Phase 1 must not claim rimba produces `feat/` or `fix/` prefixes.

    Mirrors test_skill_no_longer_uses_wrong_feat_fix_prefixes for the template.
    Both files must be guarded — they are kept in sync by convention, not codegen.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)

    assert "`feat/`" not in phase1, (
        "plan-workflow-section.md Phase 1 must not use `feat/` as a branch prefix"
    )
    assert "`fix/`" not in phase1, (
        "plan-workflow-section.md Phase 1 must not use `fix/` as a branch prefix"
    )
    assert "feature/" in phase1, "plan-workflow-section.md Phase 1 must document the `feature/` prefix"
    assert "bugfix/" in phase1, "plan-workflow-section.md Phase 1 must document the `bugfix/` prefix"


def test_template_documents_all_five_branch_prefix_flags():
    """plan-workflow-section.md Phase 1 must enumerate all five rimba branch-prefix flags.

    The template is rendered verbatim into every generated plan, so any flag
    omitted here will be missing from every plan the orchestrator produces.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)

    for flag in ("--bugfix", "--hotfix", "--docs", "--test", "--chore"):
        assert flag in phase1, (
            f"plan-workflow-section.md Phase 1 must document the rimba flag '{flag}'"
        )


def test_template_has_work_type_to_flag_mapping():
    """plan-workflow-section.md must map commit-tags to rimba flags.

    Agents use the [type] commit taxonomy from workflow-commit-and-pr. Without
    an explicit mapping from e.g. [fix] → --bugfix, agents cannot mechanically
    derive the right flag from their work type.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)

    # At minimum, the [fix] → --bugfix mapping must be present (most common non-feature type)
    assert "[fix]" in phase1, (
        "plan-workflow-section.md Phase 1 must reference the [fix] commit tag "
        "to connect the commit taxonomy to the rimba --bugfix flag"
    )
    assert "--bugfix" in phase1, (
        "plan-workflow-section.md Phase 1 must include --bugfix in the work-type mapping"
    )


# ---------------------------------------------------------------------------
# Defect 4 — Monorepo scope undocumented
# ---------------------------------------------------------------------------


def test_skill_documents_monorepo_scope():
    """SKILL.md Phase 1 must document the <service>/<task> monorepo naming pattern
    and the majority-service heuristic for cross-cutting changes.

    Without the heuristic, agents omit the scope for any cross-cutting change —
    the old "omit for repo-wide changes" guidance was actively wrong because it
    ignores the repo's branch convention.
    """
    body = SKILL.read_text()
    phase1 = _phase1_section(body)

    assert "<service>/" in phase1, (
        "SKILL.md Phase 1 must document the <service>/<task> monorepo scope syntax"
    )
    # A concrete example must be present so agents can pattern-match
    assert "backend-api/" in phase1 or "frontend/" in phase1, (
        "SKILL.md Phase 1 must include a worked monorepo example "
        "(e.g. rimba add backend-api/auth-redirect --bugfix)"
    )
    # Must document the majority-service heuristic — "omit" alone is wrong advice
    lower = phase1.lower()
    assert "majority" in lower or "most" in lower, (
        "SKILL.md Phase 1 must explain the majority-service heuristic for "
        "cross-cutting changes (pick the service where most file edits land)"
    )


def test_template_documents_monorepo_scope():
    """plan-workflow-section.md Phase 1 must document the monorepo scope pattern
    and the majority-service heuristic.

    Mirrors test_skill_documents_monorepo_scope — the template is what lands in
    generated plans, so the guidance must appear there too.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)

    assert "<service>/" in phase1, (
        "plan-workflow-section.md Phase 1 must document the <service>/<task> monorepo scope syntax"
    )
    assert "backend-api/" in phase1 or "frontend/" in phase1 or "monorepo" in phase1.lower(), (
        "plan-workflow-section.md Phase 1 must include a monorepo scope example or explicit mention"
    )
    lower = phase1.lower()
    assert "majority" in lower or "most" in lower, (
        "plan-workflow-section.md Phase 1 must include the majority-service heuristic"
    )


# ---------------------------------------------------------------------------
# Defect 2 — Post-create timing undocumented
# ---------------------------------------------------------------------------


def test_skill_documents_post_create_timing():
    """SKILL.md Phase 1 must document --skip-deps/--skip-hooks with correct timing guidance.

    rimba add installs deps and runs post_create hooks after creating the worktree.
    Agents must wait for rimba to complete when deps are required (most stacks).
    --skip-deps/--skip-hooks is only for test suites that need no installation step;
    agents must never skip deps and then reinstall manually.
    """
    body = SKILL.read_text()
    phase1 = _phase1_section(body)

    assert "--skip-deps" in phase1, (
        "SKILL.md Phase 1 must document --skip-deps so agents know the flag exists "
        "and when it is appropriate (no-install test suites only)"
    )
    assert "--skip-hooks" in phase1, (
        "SKILL.md Phase 1 must document --skip-hooks alongside --skip-deps"
    )

    # Prose must tell agents to wait for rimba when deps are needed
    lower = phase1.lower()
    assert "wait" in lower, (
        "SKILL.md Phase 1 must instruct agents to wait for rimba add to complete "
        "when deps are required — 'wait' must appear in the timing guidance"
    )


def test_template_documents_post_create_timing():
    """plan-workflow-section.md Phase 1 must document --skip-deps/--skip-hooks with
    correct timing guidance: wait for rimba when deps are required; only skip when
    the test suite genuinely needs no installation step.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)

    assert "--skip-deps" in phase1, (
        "plan-workflow-section.md Phase 1 must document --skip-deps"
    )
    assert "--skip-hooks" in phase1, (
        "plan-workflow-section.md Phase 1 must document --skip-hooks"
    )
    lower = phase1.lower()
    assert "wait" in lower, (
        "plan-workflow-section.md Phase 1 must instruct agents to wait for rimba add "
        "to complete when deps are required — 'wait' must appear in the timing guidance"
    )


# ---------------------------------------------------------------------------
# Defect 5 — Parallel implementation during install undocumented
# ---------------------------------------------------------------------------


def test_skill_documents_parallel_impl_during_install():
    """SKILL.md Phase 1 must document that coding may begin before deps finish.

    rimba add prints Path: after creating/copying the worktree — before deps
    install and hooks run. The session should not idle; it can implement during
    the long install and reconcile with TDD via git stash once rimba completes.

    Required tokens: git stash, stash pop, red, green, background, before deps.
    """
    body = SKILL.read_text()
    phase1 = _phase1_section(body)
    lower = phase1.lower()

    assert "git stash" in phase1, (
        "SKILL.md Phase 1 must document 'git stash' as the TDD reconciliation mechanic"
    )
    assert "stash pop" in phase1, (
        "SKILL.md Phase 1 must document 'git stash pop' to restore implementation after RED"
    )
    assert "**RED**" in phase1, (
        "SKILL.md Phase 1 must reference the **RED** step so agents know verification is preserved"
    )
    assert "**GREEN**" in phase1, (
        "SKILL.md Phase 1 must reference the **GREEN** step so agents know verification is preserved"
    )
    assert "background" in lower, (
        "SKILL.md Phase 1 must document backgrounding the rimba call so the session is free to implement"
    )
    assert "path:" in lower, (
        "SKILL.md Phase 1 must state that Path: is available before deps finish "
        "so agents know when coding may begin"
    )
    assert "deps" in lower, (
        "SKILL.md Phase 1 must mention deps so agents know to wait for full completion"
    )


def test_template_documents_parallel_impl_during_install():
    """plan-workflow-section.md Phase 1 must document the parallel-impl pattern.

    Mirrors test_skill_documents_parallel_impl_during_install — the template is
    rendered verbatim into every generated plan, so agents need this guidance there.
    Asserts the same six behavioral tokens as the SKILL.md test.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)
    lower = phase1.lower()

    assert "git stash" in phase1, (
        "plan-workflow-section.md Phase 1 must document 'git stash' as TDD reconciliation mechanic"
    )
    assert "stash pop" in phase1, (
        "plan-workflow-section.md Phase 1 must document 'git stash pop' to restore implementation after RED"
    )
    assert "**RED**" in phase1, (
        "plan-workflow-section.md Phase 1 must reference the **RED** step so agents know verification is preserved"
    )
    assert "**GREEN**" in phase1, (
        "plan-workflow-section.md Phase 1 must reference the **GREEN** step so agents know verification is preserved"
    )
    assert "background" in lower, (
        "plan-workflow-section.md Phase 1 must document backgrounding the rimba call"
    )
    assert "path:" in lower, (
        "plan-workflow-section.md Phase 1 must state that Path: is available before deps finish"
    )
    assert "deps" in lower, (
        "plan-workflow-section.md Phase 1 must mention deps so agents know to wait for full completion"
    )
