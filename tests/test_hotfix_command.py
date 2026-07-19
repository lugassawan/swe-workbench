"""Tests for the /swe-workbench:hotfix command and workflow-hotfix skill (closes #533)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
SKILLS_DIR = ROOT / "skills"
HOTFIX_CMD = COMMANDS_DIR / "hotfix.md"
WORKFLOW_HOTFIX = SKILLS_DIR / "workflow-hotfix"
SKILL_MD = WORKFLOW_HOTFIX / "SKILL.md"
TRIGGERS_TXT = WORKFLOW_HOTFIX / "triggers.txt"
CLEANUP_MERGED_SKILL = SKILLS_DIR / "workflow-cleanup-merged" / "SKILL.md"
DEFERRED_FOLLOWUP_REF = (
    SKILLS_DIR / "workflow-cleanup-merged" / "reference" / "deferred-verification-followup.md"
)
AGENTS_SKILLS = ROOT / "agents" / "shared" / "workflows.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"

MARKER = "<!-- swe-workbench:deferred-verification -->"


def test_hotfix_command_file_exists():
    """commands/hotfix.md must exist, have valid frontmatter, and reference workflow-hotfix."""
    assert HOTFIX_CMD.exists(), "commands/hotfix.md must exist"
    text = HOTFIX_CMD.read_text()
    fm = validate.parse_frontmatter(HOTFIX_CMD, text=text)
    assert fm is not None, "hotfix.md must have valid frontmatter"
    assert "description" in fm, "hotfix.md frontmatter must have a description field"
    assert "swe-workbench:workflow-hotfix" in text, (
        "hotfix.md must reference `swe-workbench:workflow-hotfix`"
    )


def test_hotfix_skill_referenced_in_command(monkeypatch):
    """validate.check_command_skill_refs must find no missing workflow-hotfix refs."""
    monkeypatch.setattr(validate, "ROOT", ROOT)
    validate.FAILURES.clear()
    validate.check_command_skill_refs()
    hotfix_failures = [
        f for f in validate.FAILURES
        if "workflow-hotfix" in f and "does not exist" in f
    ]
    assert not hotfix_failures, (
        f"check_command_skill_refs found unresolved workflow-hotfix refs: {hotfix_failures}"
    )


def test_hotfix_skill_frontmatter():
    """SKILL.md must have name=workflow-hotfix and orchestrator=true."""
    assert SKILL_MD.exists(), "skills/workflow-hotfix/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert fm.get("name") == "workflow-hotfix", (
        f"SKILL.md name must be 'workflow-hotfix', got {fm.get('name')!r}"
    )
    assert fm.get("orchestrator", "").lower() == "true", (
        "SKILL.md must have 'orchestrator: true'"
    )


def test_hotfix_skill_has_triggers():
    """triggers.txt must exist, have ≥2 non-comment lines, each ≤200 chars."""
    assert TRIGGERS_TXT.exists(), "skills/workflow-hotfix/triggers.txt must exist"
    raw_lines = TRIGGERS_TXT.read_text().splitlines()
    lines = [
        ln.strip() for ln in raw_lines
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2, (
        f"triggers.txt must have ≥2 non-comment lines; found {len(lines)}"
    )
    overlong = [ln for ln in lines if len(ln) > 200]
    assert not overlong, (
        f"triggers.txt has lines exceeding 200 chars: {[ln[:60] + '…' for ln in overlong]}"
    )


def test_hotfix_skill_under_orchestrator_cap():
    """SKILL.md must be ≤300 lines (orchestrator cap enforced by validate.check_skills)."""
    line_count = len(SKILL_MD.read_text().splitlines())
    assert line_count <= 300, (
        f"skills/workflow-hotfix/SKILL.md has {line_count} lines — "
        f"exceeds the 300-line orchestrator cap"
    )


def test_hotfix_skill_in_catalog():
    """agents/shared/workflows.md must have an em-dash entry for workflow-hotfix (required by
    check_catalog_completeness)."""
    text = AGENTS_SKILLS.read_text()
    assert "`swe-workbench:workflow-hotfix`" in text and "—" in text, (
        "agents/shared/workflows.md must contain an em-dash (—) entry for "
        "`swe-workbench:workflow-hotfix`"
    )


def test_hotfix_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:hotfix in the Commands table."""
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:hotfix" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:hotfix in the Commands table"
    )


def test_hotfix_in_readme():
    """README.md Commands bullet must include /swe-workbench:hotfix."""
    text = README.read_text()
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, "README.md must have a '- **Commands**' bullet line"
    assert "/swe-workbench:hotfix" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:hotfix"
    )


def test_hotfix_never_creates_worktree():
    """SKILL.md Phase 1 must explicitly forbid the worktree provider — hotfix is branch-only."""
    text = SKILL_MD.read_text()
    assert "never invoke the worktree provider" in text.lower(), (
        "SKILL.md Phase 1 must explicitly state it never invokes the worktree provider"
    )


def test_hotfix_pr_opened_before_verify_review():
    """SKILL.md must order Phase 3 (Deliver) before Phase 4 (Verify + Review) — the reordering
    is this command's entire reason to exist."""
    text = SKILL_MD.read_text()
    phase3_idx = text.find("## Phase 3")
    phase4_idx = text.find("## Phase 4")
    assert phase3_idx != -1 and phase4_idx != -1, "SKILL.md must have Phase 3 and Phase 4 sections"
    assert phase3_idx < phase4_idx, (
        "Phase 3 (Deliver the PR first) must appear before Phase 4 (Verify + Review) — "
        "verify-before-PR belongs to /swe-workbench:implement, not /swe-workbench:hotfix"
    )


# --- Deferred-verification marker consistency (issue #533 acceptance criterion) -----------------


def test_deferred_verification_marker_is_byte_identical_everywhere():
    """The exact marker string must appear identically in every file that embeds it.

    workflow-cleanup-merged Step 8 and workflow-hotfix Phase 5 both gate on this exact
    string — a single copy drifting out of sync silently breaks the whole
    deferred-verification detection path with no test to catch it.
    """
    files = [HOTFIX_CMD, SKILL_MD, CLEANUP_MERGED_SKILL, DEFERRED_FOLLOWUP_REF]
    missing = [f for f in files if MARKER not in f.read_text()]
    assert not missing, (
        f"Marker {MARKER!r} not found verbatim in: "
        f"{[str(f.relative_to(ROOT)) for f in missing]}"
    )


def test_hotfix_marker_stamped_after_pr_creation_not_before():
    """SKILL.md Phase 3 must stamp the marker via a post-creation gh pr edit, not by
    pre-writing it into a body file handed to workflow-commit-and-pr (which has no input
    hook for injected content, so a pre-creation marker would silently never land)."""
    text = SKILL_MD.read_text()
    phase3 = text.split("## Phase 3")[1].split("## Phase 4")[0]
    assert "gh pr edit" in phase3, (
        "Phase 3 must stamp the marker via `gh pr edit` after PR creation"
    )
    assert "gh pr create" not in phase3 or "workflow-commit-and-pr" in phase3, (
        "Phase 3 must delegate PR creation to workflow-commit-and-pr, not call gh pr create directly"
    )


def test_cleanup_merged_step8_gates_on_marker():
    """workflow-cleanup-merged SKILL.md Step 8 must be gated on the exact marker string and
    must not gate cleanup Steps 3-6."""
    text = CLEANUP_MERGED_SKILL.read_text()
    assert "### Step 8" in text, "workflow-cleanup-merged SKILL.md must have a Step 8 section"
    step8 = text.split("### Step 8")[1]
    assert MARKER in step8, "Step 8 must reference the exact deferred-verification marker string"
    assert "never gates cleanup" in step8, (
        "Step 8 must explicitly document that it never gates cleanup Steps 3-6"
    )


# --- Temp-file reap assertions (address-feedback fix for PR #540 review findings) ---------------


def test_hotfix_skill_reaps_marker_stamp_temp_file():
    """SKILL.md Phase 3 must reap /tmp/hotfix-pr-body-<N>.txt via clean-state-files.sh after
    the marker lands — otherwise every hotfix PR leaves a stray temp file behind."""
    text = SKILL_MD.read_text()
    phase3 = text.split("## Phase 3")[1].split("## Phase 4")[0]
    assert "clean-state-files.sh" in phase3, (
        "Phase 3 must call runtime/clean-state-files.sh to reap /tmp/hotfix-pr-body-<N>.txt"
    )
    assert "/tmp/hotfix-pr-body-<N>.txt" in phase3, (
        "Phase 3 must pass /tmp/hotfix-pr-body-<N>.txt to clean-state-files.sh"
    )


def test_hotfix_skill_phase5_names_and_reaps_its_temp_file():
    """SKILL.md Phase 5 must name an explicit temp-file path (not leave it implicit) and
    reap it via clean-state-files.sh, same as Phase 3."""
    text = SKILL_MD.read_text()
    phase5 = text.split("## Phase 5")[1].split("## Project Detection")[0]
    assert "/tmp/hotfix-pr-body-<N>.txt" in phase5, (
        "Phase 5 must name its temp-file path explicitly, not leave it as an unnamed "
        "'a temp file'"
    )
    assert "clean-state-files.sh" in phase5, (
        "Phase 5 must reap its temp file via runtime/clean-state-files.sh, same as Phase 3"
    )
