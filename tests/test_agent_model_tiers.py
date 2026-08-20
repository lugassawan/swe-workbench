"""Ratchet test for agents/*.md model tier assignments (issue #612)."""

from pathlib import Path

import pytest

import validate

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
COST_AUDIT = ROOT / "docs" / "cost-audit.md"

VALID_TIERS = {"haiku", "sonnet", "opus"}

# Encodes the #612 keep/bump pass; rationale lives in docs/cost-audit.md's
# re-tier section. Bumped to opus: architect, migrator, security-auditor, senior-engineer.
EXPECTED_TIERS = {
    "accessibility-auditor": "sonnet",
    "architect": "opus",
    "auditor": "sonnet",
    "code-impl": "sonnet",
    "conflict-resolver": "sonnet",
    "contributor-auditor": "sonnet",
    "debugger": "sonnet",
    "dependency-auditor": "haiku",
    "e2e-test-verifier": "haiku",
    "e2e-test-writer": "sonnet",
    "migrator": "opus",
    "performance-tuner": "sonnet",
    "product-designer": "sonnet",
    "product-manager": "haiku",
    "redundancy-assessor": "sonnet",
    "refactorer": "sonnet",
    "reviewer": "sonnet",
    "security-auditor": "opus",
    "senior-engineer": "opus",
    "tech-writer": "haiku",
    "test-reviewer": "sonnet",
    "test-writer": "haiku",
}


def _agent_files():
    return sorted(AGENTS_DIR.glob("*.md"))


def test_every_agent_model_is_a_known_tier():
    for path in _agent_files():
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        model = fm.get("model")
        assert model in VALID_TIERS, (
            f"{path.name}: model '{model}' is not one of {sorted(VALID_TIERS)}"
        )


@pytest.mark.parametrize("agent_name", sorted(EXPECTED_TIERS))
def test_agent_model_matches_expected_tier(agent_name):
    path = AGENTS_DIR / f"{agent_name}.md"
    assert path.exists(), f"agents/{agent_name}.md must exist"
    fm = validate.parse_frontmatter(path)
    assert fm is not None, f"{path.name} has no parseable frontmatter"
    assert fm.get("model") == EXPECTED_TIERS[agent_name], (
        f"{agent_name}: expected model '{EXPECTED_TIERS[agent_name]}', "
        f"got '{fm.get('model')}'"
    )


def test_expected_tiers_matches_agents_directory():
    on_disk = {path.stem for path in _agent_files()}
    expected = set(EXPECTED_TIERS)
    assert on_disk == expected, (
        "agents/ directory and EXPECTED_TIERS have diverged — "
        f"only on disk: {sorted(on_disk - expected)}, "
        f"only in EXPECTED_TIERS: {sorted(expected - on_disk)}"
    )


RETIER_SECTION_HEADING = "## Re-tier pass — 2026-08-21 (#612)"


def test_every_opus_agent_is_recorded_in_cost_audit():
    opus_agents = sorted(name for name, tier in EXPECTED_TIERS.items() if tier == "opus")
    assert COST_AUDIT.exists(), "docs/cost-audit.md must exist"
    text = COST_AUDIT.read_text(encoding="utf-8")
    assert RETIER_SECTION_HEADING in text, (
        f"docs/cost-audit.md must have a {RETIER_SECTION_HEADING!r} section "
        "recording the #612 decisions — the pre-existing 2026-05-10 snapshot "
        "does not count, since agent names it lists don't reflect this pass"
    )
    section = text.split(RETIER_SECTION_HEADING, 1)[1]
    for name in opus_agents:
        assert name in section, (
            f"{name} is tiered opus but is not recorded in docs/cost-audit.md's "
            f"{RETIER_SECTION_HEADING!r} section"
        )
