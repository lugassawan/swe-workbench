"""Tests for the /swe-workbench:test --mode e2e-live path (issue #474)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
COMMANDS_DIR = ROOT / "commands"
TEST_CMD = COMMANDS_DIR / "test.md"
DOCS_CATALOG = ROOT / "docs" / "catalog.md"
DOCS_DEPENDENCIES = ROOT / "docs" / "dependencies.md"


def _text():
    assert TEST_CMD.exists(), "commands/test.md must exist"
    return TEST_CMD.read_text(encoding="utf-8")


def _section(text, heading):
    match = re.search(
        rf"##\s*{heading}(.*?)(?=\n##\s|\Z)", text, re.IGNORECASE | re.DOTALL
    )
    assert match, f"commands/test.md must have a '## {heading}' section"
    return match.group(1)


def test_argument_hint_names_e2e_live():
    text = _text()
    fm = validate.parse_frontmatter(TEST_CMD, text=text)
    assert fm is not None, "test.md must have valid frontmatter"
    assert "e2e-live" in fm.get("argument-hint", ""), (
        "argument-hint must name the e2e-live mode"
    )


def test_e2e_live_path_section_exists():
    text = _text()
    assert re.search(r"##\s*E2E-live path", text, re.IGNORECASE), (
        "commands/test.md must have an '## E2E-live path' section"
    )


def test_mode_resolution_orders_e2e_live_before_bare_e2e():
    """`--mode e2e-live` must be matched before the `--mode e2e` branch,
    guarding against e2e-live falling through to the e2e branch via substring match."""
    text = _text()
    section = _section(text, "Mode resolution")

    live_idx = section.find("e2e-live")
    assert live_idx != -1, "Mode resolution section must mention --mode e2e-live"

    bare_e2e_idx = None
    for match in re.finditer(r"e2e", section):
        idx = match.start()
        # Skip occurrences that are part of "e2e-live"
        if section[idx:idx + len("e2e-live")] == "e2e-live":
            continue
        bare_e2e_idx = idx
        break

    assert bare_e2e_idx is not None, "Mode resolution section must mention the bare e2e mode"
    assert live_idx < bare_e2e_idx, (
        "--mode e2e-live must be resolved before the bare --mode e2e branch "
        "to avoid a substring false-trip"
    )


def test_e2e_live_path_is_backend_agnostic():
    text = _text()
    section = _section(text, "E2E-live path")

    assert "browser_snapshot" in section or "browser_" in section, (
        "E2E-live path must reference Playwright MCP tools"
    )
    assert "mcp__claude-in-chrome" in section, (
        "E2E-live path must reference claude-in-chrome MCP tools"
    )


def test_e2e_live_path_states_ephemeral_invariant():
    text = _text()
    section = _section(text, "E2E-live path")

    assert re.search(r"no.{0,10}spec|ephemeral", section, re.IGNORECASE), (
        "E2E-live path must state the ephemeral / no-spec-file invariant"
    )


def test_e2e_live_path_does_not_invoke_subagent():
    """The e2e-live path has no durable artifact and no verifier — the human watching is
    the verifier, so it must never dispatch e2e-test-writer/e2e-test-verifier (#474)."""
    text = _text()
    section = _section(text, "E2E-live path")

    assert "e2e-test-writer" not in section, (
        "E2E-live path must not dispatch e2e-test-writer — it is driven inline, not via subagent"
    )
    assert "e2e-test-verifier" not in section, (
        "E2E-live path must not dispatch e2e-test-verifier — no durable spec means nothing to verify"
    )
    assert re.search(r"no subagent", section, re.IGNORECASE), (
        "E2E-live path must explicitly state it invokes no subagent"
    )


def test_e2e_path_pipeline_unchanged_by_e2e_live_addition():
    """The pre-existing `--mode e2e` path must keep dispatching its writer/verifier pipeline
    and must not be contaminated by e2e-live content (#474)."""
    text = _text()
    section = _section(text, r"E2E path \(`--mode e2e`\)")

    assert "e2e-test-writer" in section, "E2E path must still dispatch e2e-test-writer"
    assert "e2e-test-verifier" in section, "E2E path must still dispatch e2e-test-verifier"
    assert "e2e-live" not in section, (
        "E2E path section must not mention e2e-live — the two paths must stay independent"
    )


def test_file_still_carries_browser_gate_sentinel():
    """Adding the e2e-live path must not break the shared hard-gate contract (#364) —
    the file must still carry a BLOCKED: sentinel and the @playwright/mcp install hint."""
    text = _text()
    assert "BLOCKED:" in text, "commands/test.md must carry a BLOCKED: sentinel"
    assert "claude mcp add" in text and "@playwright/mcp" in text, (
        "commands/test.md must carry the @playwright/mcp install hint"
    )


def test_docs_catalog_distinguishes_e2e_and_e2e_live():
    assert DOCS_CATALOG.exists(), "docs/catalog.md must exist"
    text = DOCS_CATALOG.read_text(encoding="utf-8")
    assert "e2e-live" in text, (
        "docs/catalog.md must mention e2e-live to distinguish it from --mode e2e"
    )


def test_docs_dependencies_mentions_e2e_live_as_optional_backend():
    assert DOCS_DEPENDENCIES.exists(), "docs/dependencies.md must exist"
    text = DOCS_DEPENDENCIES.read_text(encoding="utf-8")
    assert "e2e-live" in text, (
        "docs/dependencies.md must note Playwright MCP / claude-in-chrome as optional "
        "either-or backends for /test --mode e2e-live"
    )
