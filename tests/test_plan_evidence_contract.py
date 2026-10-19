"""Prose pins for the plan-evidence gate.

The gate has three prose surfaces that must stay wired together:
1. skills/workflow-development/templates/plan-evidence-section.md — the `## Evidence`
   template whose `[[evidence:KEY]]` placeholders the orchestrator fills from the
   `swe-workbench-plan-evidence` envelope.
2. skills/workflow-development/SKILL.md Mode A — runs the script (never with `--fetch`,
   which is plan-time network I/O) and renders the template above `## Workflow`.
3. templates/plan-workflow-section.md Phase 1 — the implementation-time recheck, the one
   place `--fetch` is allowed.
Plus the shared evidence-discipline rule spliced into the planning agents.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "workflow-development"
EVIDENCE_TEMPLATE = SKILL / "templates" / "plan-evidence-section.md"
WORKFLOW_TEMPLATE = SKILL / "templates" / "plan-workflow-section.md"
SKILL_MD = SKILL / "SKILL.md"
SHARED = ROOT / "shared" / "agents" / "evidence-discipline.md"
PLANNING_AGENTS = ("senior-engineer", "architect", "debugger")

EVIDENCE_KEYS = ("head", "dirty", "target", "target-sha", "drift", "worktrees")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mode_a_section() -> str:
    text = _read(SKILL_MD)
    start = text.index("## Plan-Time Behavior (Mode A)")
    end = text.index("## Implementation-Time Behavior (Mode B)")
    return text[start:end]


def _phase1_refresh_bullet() -> str:
    for line in _read(WORKFLOW_TEMPLATE).splitlines():
        if line.startswith("- **Refresh evidence:**"):
            return line
    raise AssertionError("plan-workflow-section.md has no '- **Refresh evidence:**' bullet")


class TestEvidenceTemplate:
    def test_template_exists(self):
        assert EVIDENCE_TEMPLATE.exists()

    def test_carries_every_evidence_placeholder(self):
        text = _read(EVIDENCE_TEMPLATE)
        for key in EVIDENCE_KEYS:
            assert f"[[evidence:{key}]]" in text, key

    def test_requires_scoped_negative_findings_and_open_assumptions(self):
        text = _read(EVIDENCE_TEMPLATE)
        assert "not found in" in text
        assert "open assumption" in text

    def test_names_the_unknown_drift_assumption(self):
        assert "target not fetched" in _read(EVIDENCE_TEMPLATE)

    def test_introduced_identifiers_table_has_all_columns(self):
        text = _read(EVIDENCE_TEMPLATE)
        for column in ("collision check", "prior-art check", "version source"):
            assert column in text.lower(), column

    def test_section_is_headed_evidence(self):
        assert re.search(r"^## Evidence$", _read(EVIDENCE_TEMPLATE), re.M)


class TestModeA:
    def test_runs_the_script_and_renders_the_template(self):
        section = _mode_a_section()
        assert "swe-workbench-plan-evidence" in section
        assert "plan-evidence-section.md" in section

    def test_greps_draft_for_unsubstituted_evidence_markers(self):
        assert "[[evidence:" in _mode_a_section()

    def test_never_fetches_at_plan_time(self):
        assert "--fetch" not in _mode_a_section()

    def test_rereads_only_overlapping_paths(self):
        section = _mode_a_section()
        assert "overlap" in section
        assert "only" in section

    def test_summary_line_mentions_the_evidence_section(self):
        head = _read(SKILL_MD)[:_read(SKILL_MD).index("## Plan-Time Behavior (Mode A)")]
        assert "## Evidence" in head

    def test_skill_md_stays_under_the_line_warning(self):
        assert len(_read(SKILL_MD).splitlines()) < 270


class TestPhase1Recheck:
    def test_refresh_bullet_fetches_and_rechecks_from_inspected_revision(self):
        bullet = _phase1_refresh_bullet()
        assert "swe-workbench-plan-evidence" in bullet
        assert "--fetch" in bullet
        assert "--since" in bullet

    def test_refresh_bullet_reuses_the_plans_target_and_never_stalls(self):
        bullet = _phase1_refresh_bullet()
        assert "--target <target from ## Evidence>" in bullet
        assert "unknown" in bullet and "open assumption" in bullet

    def test_refresh_bullet_follows_enter_worktree_bullet(self):
        lines = _read(WORKFLOW_TEMPLATE).splitlines()
        enter = next(i for i, l in enumerate(lines) if l.startswith("- **Enter worktree:**"))
        refresh = next(i for i, l in enumerate(lines) if l.startswith("- **Refresh evidence:**"))
        assert refresh > enter


class TestEvidenceDisciplineSplice:
    def test_shared_rule_exists_and_states_the_forms(self):
        text = _read(SHARED)
        assert "not found in" in text
        assert "open assumption" in text
        assert "file:line" in text

    def test_evidence_subsection_is_not_a_competing_final_line(self):
        assert "End your response" not in _read(SHARED)

    def test_each_planning_agent_splices_it_before_the_canary_block(self):
        for agent in PLANNING_AGENTS:
            text = _read(ROOT / "agents" / f"{agent}.md")
            begin = text.find("<!-- BEGIN shared/agents/evidence-discipline.md -->")
            end = text.find("<!-- END shared/agents/evidence-discipline.md -->")
            canary = text.find("<!-- BEGIN shared/agents/preload-canary-citation.md -->")
            assert -1 < begin < end < canary, agent
