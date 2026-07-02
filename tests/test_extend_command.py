"""Tests for the /swe-workbench:extend command and workflow-extend skill (closes #207)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
SKILLS_DIR = ROOT / "skills"
EXTEND_CMD = COMMANDS_DIR / "extend.md"
WORKFLOW_EXTEND = SKILLS_DIR / "workflow-extend"
SKILL_MD = WORKFLOW_EXTEND / "SKILL.md"
TRIGGERS_TXT = WORKFLOW_EXTEND / "triggers.txt"
TEMPLATE_MD = WORKFLOW_EXTEND / "templates" / "plan-extend-section.md"
AGENTS_SKILLS = ROOT / "agents" / "shared" / "workflows.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
README = ROOT / "README.md"


def test_extend_command_file_exists():
    """commands/extend.md must exist, have valid frontmatter, and reference workflow-extend."""
    assert EXTEND_CMD.exists(), "commands/extend.md must exist"
    text = EXTEND_CMD.read_text()
    fm = validate.parse_frontmatter(EXTEND_CMD, text=text)
    assert fm is not None, "extend.md must have valid frontmatter"
    assert "description" in fm, "extend.md frontmatter must have a description field"
    assert "swe-workbench:workflow-extend" in text, (
        "extend.md must reference `swe-workbench:workflow-extend`"
    )


def test_extend_skill_referenced_in_command(monkeypatch):
    """validate.check_command_skill_refs must find no missing workflow-extend refs."""
    monkeypatch.setattr(validate, "ROOT", ROOT)
    validate.FAILURES.clear()
    validate.check_command_skill_refs()
    extend_failures = [
        f for f in validate.FAILURES
        if "workflow-extend" in f and "does not exist" in f
    ]
    assert not extend_failures, (
        f"check_command_skill_refs found unresolved workflow-extend refs: {extend_failures}"
    )


def test_extend_skill_frontmatter():
    """SKILL.md must have name=workflow-extend, orchestrator=true, and required description tokens."""
    assert SKILL_MD.exists(), "skills/workflow-extend/SKILL.md must exist"
    text = SKILL_MD.read_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None, "SKILL.md must have valid frontmatter"
    assert fm.get("name") == "workflow-extend", (
        f"SKILL.md name must be 'workflow-extend', got {fm.get('name')!r}"
    )
    assert fm.get("orchestrator", "").lower() == "true", (
        "SKILL.md must have 'orchestrator: true'"
    )
    desc = fm.get("description", "")
    required_tokens = ["mid-PR", "sub-idea", "existing PR", "same branch", "update existing PR"]
    missing = [t for t in required_tokens if t not in desc]
    assert not missing, (
        f"SKILL.md description missing BM25-differentiation tokens: {missing!r}\n"
        f"Current description: {desc!r}"
    )


def test_extend_skill_has_triggers():
    """triggers.txt must exist, have ≥2 non-comment lines, each ≤200 chars."""
    assert TRIGGERS_TXT.exists(), "skills/workflow-extend/triggers.txt must exist"
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


def test_extend_skill_in_catalog():
    """agents/shared/workflows.md must have an em-dash entry for workflow-extend (O3)."""
    assert AGENTS_SKILLS.exists(), "agents/shared/workflows.md must exist"
    text = AGENTS_SKILLS.read_text()
    entry_re = re.compile(
        r'^-\s+`swe-workbench:workflow-extend`\s+—\s+\S',
        re.MULTILINE,
    )
    assert entry_re.search(text), (
        "agents/shared/workflows.md must contain an em-dash (—) entry for "
        "`swe-workbench:workflow-extend` (required by check_catalog_completeness)"
    )


def test_extend_in_docs_catalog():
    """docs/catalog.md must have a row for /swe-workbench:extend in the Commands table."""
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text()
    assert "/swe-workbench:extend" in text, (
        "docs/catalog.md must contain a row for /swe-workbench:extend in the Commands table"
    )


def test_extend_in_readme():
    """README.md Commands bullet must include /swe-workbench:extend."""
    assert README.exists(), "README.md must exist"
    text = README.read_text()
    assert "/swe-workbench:extend" in text, (
        "README.md must mention /swe-workbench:extend"
    )
    lines = text.splitlines()
    commands_line = next(
        (ln for ln in lines if ln.strip().startswith("- **Commands**")),
        None,
    )
    assert commands_line is not None, (
        "README.md must have a '- **Commands**' bullet line"
    )
    assert "/swe-workbench:extend" in commands_line, (
        "README.md '- **Commands**' bullet must include /swe-workbench:extend"
    )


def test_extend_template_no_phase_1():
    """plan-extend-section.md must not contain a Phase 1 or Branch heading."""
    assert TEMPLATE_MD.exists(), (
        "skills/workflow-extend/templates/plan-extend-section.md must exist"
    )
    text = TEMPLATE_MD.read_text()
    assert not re.search(r'^#{1,4}\s+Phase 1', text, re.MULTILINE), (
        "plan-extend-section.md must not contain a '### Phase 1' heading — "
        "Phase 1 (Branch) is intentionally skipped by /extend"
    )
    phase1_heading = re.search(r'^#{1,4}\s+.*\bBranch\b', text, re.MULTILINE)
    assert not phase1_heading, (
        f"plan-extend-section.md must not contain a Branch heading; "
        f"found: {phase1_heading.group()!r}"
    )


def test_extend_command_no_open_pr_fallback():
    """extend.md must contain the AskUserQuestion fallback and prohibit gh pr create."""
    text = EXTEND_CMD.read_text()
    assert "AskUserQuestion" in text, (
        "extend.md must contain an AskUserQuestion block for the no-open-PR fallback"
    )
    assert "Abort" in text, (
        "extend.md fallback must include an Abort option"
    )
    # gh pr create must only appear in a prohibition context, never as a bare invocation
    assert re.search(r'[Nn]ever call.*gh pr create|do not.*gh pr create', text), (
        "extend.md must explicitly prohibit 'gh pr create' (e.g. 'Never call gh pr create')"
    )


def test_extend_command_inline_phases_2_through_5():
    """extend.md must show Phases 2-5 inline (issue #476), mirroring implement.md.

    Phase 1 (Branch) is intentionally skipped — the open PR branch is reused.
    Phase 5 must update the existing PR via workflow-commit-and-pr, never gh pr create.
    """
    text = EXTEND_CMD.read_text()
    for marker in (
        "**Phase 2 — Implement**",
        "**Phase 3 — Verify**",
        "**Phase 4 — Review**",
        "**Phase 5 — Deliver**",
    ):
        assert marker in text, f"extend.md must contain inline marker {marker!r}"

    assert re.search(r'Phase 1.{0,80}\b(skipped|reused)\b', text, re.IGNORECASE | re.DOTALL), (
        "extend.md must note that Phase 1 (Branch) is skipped/reused"
    )

    assert "swe-workbench:workflow-commit-and-pr" in text, (
        "extend.md Phase 5 must invoke swe-workbench:workflow-commit-and-pr to update the existing PR"
    )

    assert "swe-workbench:workflow-extend" in text, (
        "extend.md must still activate swe-workbench:workflow-extend — "
        "the inline block is a visible contract, not a replacement"
    )


def test_extend_commit_format_sub_idea_prefix():
    """SKILL.md and template must both mandate the 'sub-idea:' commit prefix."""
    assert "sub-idea:" in SKILL_MD.read_text(), (
        "SKILL.md Phase D must mandate the '[<type>] sub-idea: <restatement>' commit format"
    )
    assert "sub-idea:" in TEMPLATE_MD.read_text(), (
        "plan-extend-section.md Phase 5 must show the 'sub-idea:' commit format"
    )


def test_extend_skill_trunk_branch_guard():
    """SKILL.md must document the trunk-branch guard (main/master → fail loudly)."""
    text = SKILL_MD.read_text()
    assert re.search(r'main.*master|master.*main', text, re.IGNORECASE), (
        "SKILL.md Failure modes must document the trunk-branch guard "
        "(HEAD_REF is main or master → fail loudly)"
    )


def test_extend_skill_requires_ref_traceability():
    """SKILL.md must mandate 'Ref: extend-' in the commit body (Phase D traceability)."""
    assert SKILL_MD.exists(), "skills/workflow-extend/SKILL.md must exist"
    text = SKILL_MD.read_text()
    assert re.search(r'Ref:\s+extend-', text), (
        "SKILL.md must require 'Ref: extend-<ts>' in the commit body "
        "(traceability requirement from acceptance criterion #5)"
    )


def test_extend_skill_under_orchestrator_cap():
    """SKILL.md must be ≤300 lines (orchestrator cap enforced by validate.check_skills)."""
    assert SKILL_MD.exists(), "skills/workflow-extend/SKILL.md must exist"
    line_count = len(SKILL_MD.read_text().splitlines())
    assert line_count <= 300, (
        f"skills/workflow-extend/SKILL.md has {line_count} lines — "
        f"exceeds the 300-line orchestrator cap"
    )


# --- State-file cleanup assertions (issue #428) ---

def test_extend_skill_phase_d_deletes_tmp_file():
    """SKILL.md Phase D must invoke clean-state-files.sh on /tmp/extend-${TS}.md after delivery."""
    text = SKILL_MD.read_text()
    assert "clean-state-files.sh" in text, (
        "SKILL.md Phase D must call runtime/clean-state-files.sh to remove /tmp/extend-${TS}.md "
        "after successful delivery"
    )
    assert "/tmp/extend-${TS}.md" in text, (
        "SKILL.md must pass /tmp/extend-${TS}.md to clean-state-files.sh"
    )


def test_extend_skill_cleanup_after_delivery():
    """SKILL.md: clean-state-files.sh call must appear AFTER Phase D delivery text (success-only)."""
    text = SKILL_MD.read_text()
    phase_d_idx = text.find("## Phase D")
    cleanup_idx = text.find("clean-state-files.sh")
    assert phase_d_idx != -1, "SKILL.md must have a Phase D section"
    assert cleanup_idx != -1, "SKILL.md must reference clean-state-files.sh"
    assert cleanup_idx > phase_d_idx, (
        "clean-state-files.sh call must appear within/after Phase D — "
        "cleanup runs on the success delivery path only"
    )


# ── Foreground-reap assertions (Fix C, recurrence of #428/#429) ─────────────


def test_extend_skill_reap_no_suppression():
    """The clean-state-files.sh call in Phase D must have NO 2>/dev/null suppression.

    The reap must run without error suppression so orphaned spec-temp files surface as failures.
    """
    text = SKILL_MD.read_text()
    lines_with_reap = [ln for ln in text.splitlines() if "clean-state-files.sh" in ln]
    assert lines_with_reap, "SKILL.md must contain a clean-state-files.sh call"
    suppressed = [ln for ln in lines_with_reap if "2>/dev/null" in ln]
    assert not suppressed, (
        "clean-state-files.sh call must not carry 2>/dev/null — "
        "foreground reap must surface failures:\n" + "\n".join(suppressed)
    )
