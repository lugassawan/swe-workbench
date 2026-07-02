"""Structural tests for agents/conflict-resolver.md (issue #485)."""

from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
AGENT = ROOT / "agents" / "conflict-resolver.md"


def _read() -> str:
    assert AGENT.exists(), "agents/conflict-resolver.md must exist"
    return AGENT.read_text(encoding="utf-8")


def test_agent_file_exists():
    assert AGENT.exists()


def test_frontmatter_name_and_model():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    assert fm is not None
    assert fm.get("name") == "conflict-resolver"
    assert fm.get("model") == "sonnet"


def test_tools_are_advisory_only_no_edit_or_write():
    body = _read()
    fm = validate.parse_frontmatter(AGENT, text=body)
    tools = fm.get("tools", "")
    for required in ("Read", "Grep", "Glob", "Bash", "Skill"):
        assert required in tools, f"tools: must include '{required}'"
    assert "Edit" not in tools, "conflict-resolver is advisory only — must not have Edit"
    assert "Write" not in tools, "conflict-resolver is advisory only — must not have Write"


def test_reachable_via_sync_command():
    body = _read()
    assert "**Reachable via:** `/swe-workbench:sync`" in body


def test_sentinel_line_formats_present():
    body = _read()
    assert "**Resolution: KEEP-MINE**" in body
    assert "**Resolution: KEEP-MAIN**" in body
    assert "**Resolution: MANUAL**" in body


def test_output_contract_requires_exactly_one_sentinel():
    body = _read()
    assert "## Output contract" in body
    contract = body.split("## Output contract")[1].split("## ")[0]
    assert "EXACTLY ONE" in contract
    assert "never omit" in contract.lower() or "never emit more than one" in contract.lower()


def test_cites_silence_rule():
    body = _read()
    assert "severity-output-contract.md" in body
    assert "silence rule" in body.lower()


def test_includes_both_catalog_slices():
    body = _read()
    assert "@./shared/principles.md" in body
    assert "@./shared/languages.md" in body


def test_requires_language_skill_statement():
    body = _read()
    assert "Language skill (required)" in body


def test_references_version_control_principle():
    body = _read()
    assert "swe-workbench:principle-version-control" in body


def test_never_calls_ours_theirs_directly():
    body = _read()
    assert "apply-resolution.sh" in body
    assert "never edit" in body.lower() or "never applies" in body.lower() or "you never" in body.lower()
