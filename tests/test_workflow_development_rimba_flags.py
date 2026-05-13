"""Regression tests for workflow-development rimba add documentation defects.

Defects addressed:
1. SKILL.md and plan-workflow-section.md never document the five branch-prefix flags
   (--bugfix, --hotfix, --docs, --test, --chore), so agents always emit bare
   `rimba add <task>` and get feature/<slug> for every work type.
2. SKILL.md Phase 1 mentions `--skip-deps` / `--skip-hooks` nowhere, so TDD-heavy
   plans race against rimba's dep-install pipeline before the first test run.
3. SKILL.md line ~94 uses wrong prefixes `feat/`, `fix/` — rimba actually produces
   `feature/`, `bugfix/`, `hotfix/`, `docs/`, `test/`, `chore/`.
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
    """SKILL.md Phase 1 must document the <service>/<task> monorepo naming pattern.

    Without this, agents working in a monorepo always produce flat branch names
    (e.g. bugfix/auth-redirect) instead of service-scoped ones
    (e.g. bugfix/backend-api/auth-redirect), losing branch grouping by service.
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


def test_template_documents_monorepo_scope():
    """plan-workflow-section.md Phase 1 must document the monorepo scope pattern.

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


# ---------------------------------------------------------------------------
# Defect 2 — Post-create timing undocumented
# ---------------------------------------------------------------------------


def test_skill_documents_post_create_timing():
    """SKILL.md Phase 1 must document --skip-deps and --skip-hooks with TDD guidance.

    rimba add runs dep install and post_create hooks after creating the worktree.
    TDD-heavy plans that run the test suite before deps finish get spurious failures.
    The skill must tell agents when to pass --skip-deps / --skip-hooks.
    """
    body = SKILL.read_text()
    phase1 = _phase1_section(body)

    assert "--skip-deps" in phase1, (
        "SKILL.md Phase 1 must document --skip-deps so agents know to pass it "
        "when starting a TDD red-first loop before deps are installed"
    )
    assert "--skip-hooks" in phase1, (
        "SKILL.md Phase 1 must document --skip-hooks alongside --skip-deps"
    )

    # Surrounding prose must reference TDD / test-first timing context
    lower = phase1.lower()
    assert any(kw in lower for kw in ("tdd", "test", "wait")), (
        "SKILL.md Phase 1 must explain the timing trade-off — mention 'tdd', 'test', "
        "or 'wait' in the context of --skip-deps / --skip-hooks guidance"
    )


def test_template_documents_post_create_timing():
    """plan-workflow-section.md Phase 1 must document --skip-deps and --skip-hooks.

    The template is what rendered plans contain. Without this note, every generated
    plan omits the TDD timing guidance, leaving agents to discover the race condition
    the hard way.
    """
    body = TEMPLATE.read_text()
    phase1 = _phase1_section(body)

    assert "--skip-deps" in phase1, (
        "plan-workflow-section.md Phase 1 must document --skip-deps"
    )
    assert "--skip-hooks" in phase1, (
        "plan-workflow-section.md Phase 1 must document --skip-hooks"
    )
