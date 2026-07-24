"""Structural tests — language-skill under-selection fix.

T1: Every code-touching agent body contains @./shared/languages.md.
T2: Every code-touching agent body directly contains a mandatory language-skill
    gate marker (`language-*`) in its consultation section, signalling required
    (not optional) language-skill loading.
T5: Every rules/language-*.md rule is registered in docs/catalog.md and
    hooks/skill_autoload_hint.sh's ext_to_rule() case map.

T4 ('every principle-*/language-* SKILL.md description contains "Auto-load
when"') was retired along with the skill model itself: principle-*/language-*
are now plain rules/*.md files with no frontmatter at all, and the conversion
deliberately dropped the "Auto-load when ..." clause from every one of them —
these rules don't auto-trigger via description-matching anymore (that
mechanism, and the BM25 harness it fed, only applied to skills/triggers.txt).
See docs/superpowers/specs/2026-07-24-principles-languages-as-rules-design.md.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
RULES_DIR = ROOT / "rules"

# Agents that review, write, or diagnose code — must consult language skills.
# product-manager is excluded (files GitHub issues; never touches source).
CODE_TOUCHING_AGENTS = [
    "accessibility-auditor",
    "architect",
    "auditor",
    "code-impl",
    "contributor-auditor",
    "debugger",
    "dependency-auditor",
    "migrator",
    "performance-tuner",
    "refactorer",
    "reviewer",
    "security-auditor",
    "senior-engineer",
    "tech-writer",
    "test-reviewer",
    "test-writer",
    "product-designer",
]


def _agent_text(name: str) -> str:
    path = AGENTS_DIR / f"{name}.md"
    assert path.exists(), f"agents/{name}.md does not exist"
    return path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# T1 — @./shared/languages.md present in every code-touching agent
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", CODE_TOUCHING_AGENTS)
def test_agent_has_languages_catalog_include(agent_name):
    """T1: code-touching agent body must contain @./shared/languages.md."""
    text = _agent_text(agent_name)
    assert "@./shared/languages.md" in text, (
        f"agents/{agent_name}.md is missing '@./shared/languages.md'. "
        "All code-touching agents must include the language-skill catalog."
    )


# ──────────────────────────────────────────────────────────────
# T2 — mandatory language-skill gate present in consultation section
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", CODE_TOUCHING_AGENTS)
def test_agent_has_mandatory_language_gate(agent_name):
    """T2: consultation section must gate on language-* (required, not optional)."""
    text = _agent_text(agent_name)
    # The mandatory gate paragraph uses `language-*` (with the asterisk) to
    # indicate the required invocation pattern. This is the specific signal
    # added by the fix; it is NOT present in the @./shared/languages.md include.
    assert "language-*" in text, (
        f"agents/{agent_name}.md is missing a mandatory language-skill gate "
        "('language-*'). Add a required consultation paragraph that instructs "
        "the agent to detect the language and invoke the matching language-* skill."
    )


# ──────────────────────────────────────────────────────────────
# T5 — language-* rules registered in catalog.md and skill_autoload_hint.sh
# ──────────────────────────────────────────────────────────────

CATALOG_MD = ROOT / "docs" / "catalog.md"
HOOK_SH = ROOT / "hooks" / "skill_autoload_hint.sh"


def _rule_files_with_prefix(prefix: str):
    if not RULES_DIR.is_dir():
        return []
    return sorted(RULES_DIR.glob(f"{prefix}*.md"))


@pytest.mark.parametrize(
    "rule_file",
    _rule_files_with_prefix("language-"),
    ids=lambda p: p.stem,
)
def test_language_rule_in_catalog(rule_file):
    """T5a: every rules/language-*.md must have a row marker in docs/catalog.md."""
    rule_name = rule_file.stem
    catalog_text = CATALOG_MD.read_text(encoding="utf-8")
    row_marker = f"| `{rule_name}` |"
    assert row_marker in catalog_text, (
        f"docs/catalog.md is missing a row for '{rule_name}'. "
        "Add the rule to the Languages table."
    )


@pytest.mark.parametrize(
    "rule_file",
    _rule_files_with_prefix("language-"),
    ids=lambda p: p.stem,
)
def test_language_rule_in_hook(rule_file):
    """T5b: every rules/language-*.md must appear in hooks/skill_autoload_hint.sh."""
    rule_name = rule_file.stem
    hook_text = HOOK_SH.read_text(encoding="utf-8")
    assert rule_name in hook_text, (
        f"hooks/skill_autoload_hint.sh is missing '{rule_name}'. "
        "Add the rule to the ext_to_rule() case map."
    )
