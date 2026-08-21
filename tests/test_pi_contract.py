"""Contract tests for the swe-workbench <-> Pi Coding Agent frontmatter boundary (issue #605).

ADR-0001's runtime adapter (pi/) reads agents/*.md, skills/*/SKILL.md, and commands/*.md
frontmatter through Pi's own YAML parser — which is strict. scripts/validate.py's
parse_frontmatter() is a hand-rolled, lenient parser: it accepted agents/architect.md's
former `description: ...existing code: authoring an ADR...` line (a colon-space inside a
plain scalar), which a real YAML 1.1/1.2 parser rejects outright (mapping values are not
allowed here). That divergence would have made Pi fail to load the agent silently — this
module is the anti-drift gate ADR-0001 promised for that coupling; it must go RED before a
future frontmatter edit can break Pi, not after.

Ratchet shape follows tests/test_agent_model_tiers.py: module-level dict/set literals record
what this repo's frontmatter currently uses. A new key/tool/skill only trips a test once
*this repo* writes it into a file — keeping the gate open-world per
docs/plugin-platform-decisions.md §2, rather than a closed-form schema.
"""

from pathlib import Path

import yaml

import validate

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"
COMMANDS_DIR = ROOT / "commands"
SHARED_DIR = ROOT / "shared"

# The complete key vocabulary agents/*.md frontmatter uses today. A new key (e.g. a future
# Phase 7 `pi:` override block) must be added here deliberately, not discovered by CI red.
FRONTMATTER_KEYS = {"name", "description", "model", "tools", "skills"}

# Union of every comma-separated token across all agents/*.md `tools:` lines. Grows only
# when an agent's frontmatter is edited to grant a new tool — not on every agent edit.
TOOL_TOKENS = {
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "LSP",
    "Read",
    "Skill",
    "WebFetch",
    "Write",
}

# Union of every `swe-workbench:<id>` entry across all agents/*.md `skills:` blocks.
SKILL_IDS = {
    "swe-workbench:language-typescript",
    "swe-workbench:principle-accessibility",
    "swe-workbench:principle-api-design",
    "swe-workbench:principle-clean-architecture",
    "swe-workbench:principle-clean-code",
    "swe-workbench:principle-code-review",
    "swe-workbench:principle-communication",
    "swe-workbench:principle-concurrency",
    "swe-workbench:principle-cost-awareness",
    "swe-workbench:principle-data-modeling",
    "swe-workbench:principle-ddd",
    "swe-workbench:principle-design-patterns",
    "swe-workbench:principle-distributed-systems",
    "swe-workbench:principle-error-handling",
    "swe-workbench:principle-event-driven",
    "swe-workbench:principle-observability",
    "swe-workbench:principle-performance",
    "swe-workbench:principle-postmortem",
    "swe-workbench:principle-product-design",
    "swe-workbench:principle-refactoring",
    "swe-workbench:principle-release-engineering",
    "swe-workbench:principle-resiliency",
    "swe-workbench:principle-security",
    "swe-workbench:principle-solid",
    "swe-workbench:principle-tdd",
    "swe-workbench:principle-testing",
    "swe-workbench:principle-version-control",
}


def _frontmatter_files():
    """Every file in the plan's Pi-relevant scope that may carry a --- frontmatter block."""
    files = list(AGENTS_DIR.glob("*.md"))
    files += list(SKILLS_DIR.glob("*/SKILL.md"))
    files += list(COMMANDS_DIR.glob("*.md"))
    files += list(SHARED_DIR.rglob("*.md"))
    return sorted(files)


def _frontmatter_block(path):
    """Return the raw text between the opening and closing '---' markers, or None.

    Mirrors validate.parse_frontmatter's own delimiter-finding logic so both parsers see
    exactly the same substring — the only fair way to compare "does this parse" and
    "what keys does this produce" across the two implementations.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[3:end]


def test_all_frontmatter_is_strict_yaml_parseable():
    failures = []
    for path in _frontmatter_files():
        block = _frontmatter_block(path)
        if block is None:
            continue
        try:
            yaml.safe_load(block)
        except yaml.YAMLError as e:
            failures.append(f"{path.relative_to(ROOT)}: {e}")
    assert not failures, (
        "frontmatter block(s) fail strict YAML parsing — Pi's real parser would reject "
        "these (a lenient hand-rolled parser accepting them is not enough):\n"
        + "\n".join(f"  {f}" for f in failures)
    )


def test_strict_and_lenient_parsers_agree_on_keys():
    """The only assertion that catches lenient-accepts / strict-rejects key drift.

    Schema conformance is not the gate here — key-set agreement between validate.py's
    hand-rolled parser and a real YAML parser is, since that is the one property that can
    silently diverge without either parser raising.
    """
    mismatches = []
    for path in _frontmatter_files():
        block = _frontmatter_block(path)
        if block is None:
            continue
        try:
            strict = yaml.safe_load(block)
        except yaml.YAMLError:
            continue  # reported by test_all_frontmatter_is_strict_yaml_parseable
        if not isinstance(strict, dict):
            continue
        strict_keys = {str(k).lower() for k in strict.keys()}
        lenient = validate.parse_frontmatter(path)
        lenient_keys = set(lenient.keys()) if lenient is not None else set()
        if strict_keys != lenient_keys:
            mismatches.append(
                f"{path.relative_to(ROOT)}: strict={sorted(strict_keys)} "
                f"lenient={sorted(lenient_keys)}"
            )
    assert not mismatches, (
        "strict (PyYAML) and lenient (validate.parse_frontmatter) parsers disagree on "
        "frontmatter keys — one accepts something the other doesn't:\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )


def test_agent_frontmatter_keys_are_inventoried():
    on_disk = set()
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        on_disk |= set(fm.keys())
    assert on_disk == FRONTMATTER_KEYS, (
        "agents/*.md frontmatter keys have drifted from the inventory — "
        f"only on disk: {sorted(on_disk - FRONTMATTER_KEYS)}, "
        f"only in FRONTMATTER_KEYS: {sorted(FRONTMATTER_KEYS - on_disk)}"
    )


def test_tool_tokens_and_skill_ids_are_inventoried():
    tool_tokens = set()
    skill_ids = set()
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        tools = fm.get("tools")
        if tools:
            tool_tokens |= {t.strip() for t in tools.split(",")}
        skills = fm.get("skills")
        if isinstance(skills, list):
            skill_ids |= {s for s in skills if s.startswith("swe-workbench:")}
    assert tool_tokens == TOOL_TOKENS, (
        "agents/*.md tool tokens have drifted from the inventory — "
        f"only on disk: {sorted(tool_tokens - TOOL_TOKENS)}, "
        f"only in TOOL_TOKENS: {sorted(TOOL_TOKENS - tool_tokens)}"
    )
    assert skill_ids == SKILL_IDS, (
        "agents/*.md skill ids have drifted from the inventory — "
        f"only on disk: {sorted(skill_ids - SKILL_IDS)}, "
        f"only in SKILL_IDS: {sorted(SKILL_IDS - skill_ids)}"
    )
