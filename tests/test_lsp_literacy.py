"""Acceptance-pinning tests — LSP code-intelligence literacy (#559, #621).

#559 pinned the native `LSP` harness tool's content across four agents
(`reviewer`, `auditor`, `debugger`, `refactorer`). #621 found that tool
main-loop-only on Claude Code 2.1.237 — unreachable from any subagent, on
any build, even at the maximum grant a subagent can hold — and replaced the
dependency on it with `bin/swe-workbench-lsp`, a stdlib-only script reachable
via `Bash` from any harness. This file now pins that script-based contract:
the four agents' shared prose still references it, the doc names its
subcommands, the three orchestrator skills still carry the fallback
sentence, and docs/dependencies.md still documents it.

Agent tools:/body content for these four agents is otherwise covered by
`scripts/validate.py`'s check_lsp_tool_gate() (self-disarms once no agent
grants `LSP`) and check_shared_blocks_in_sync() (generic sentinel-block sync
check for every agent) — not duplicated here.

This is a regression suite against the real repo tree, not a red-green
TDD exercise — every test here should pass immediately and simply guard
against future drift. Matches the style of test_agent_language_catalog.py:
module-level ROOT constant, direct .read_text() on real files, no tmp_path
or reset_validate fixture.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"
SHARED_DIR = ROOT / "shared"
LSP_SRC = SHARED_DIR / "agents" / "lsp.md"

# The four agents this feature's shared doc still targets.
LSP_AGENTS = ["reviewer", "auditor", "debugger", "refactorer"]

# The eight subcommands named in shared/agents/lsp.md.
SCRIPT_SUBCOMMANDS = [
    "refs",
    "def",
    "impl",
    "callers",
    "callees",
    "hover",
    "symbols",
    "wsymbols",
]

# The three orchestrator skills that carry the LSP-unavailable fallback hint.
ORCHESTRATOR_SKILLS = [
    "workflow-development",
    "workflow-pr-review",
    "workflow-codebase-audit",
]

FALLBACK_SENTENCE = "LSP unavailable — falling back to Grep"


def _agent_text(name: str) -> str:
    path = AGENTS_DIR / f"{name}.md"
    assert path.exists(), f"agents/{name}.md does not exist"
    return path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# shared/agents/lsp.md names the script and every subcommand
# ──────────────────────────────────────────────────────────────


def test_shared_lsp_doc_references_the_script():
    """shared/agents/lsp.md points at bin/swe-workbench-lsp, not the dead
    harness LSP tool."""
    assert LSP_SRC.exists(), "shared/agents/lsp.md does not exist"
    text = LSP_SRC.read_text(encoding="utf-8")
    assert "swe-workbench-lsp" in text, (
        "shared/agents/lsp.md is missing a reference to the bin/swe-workbench-lsp script."
    )


@pytest.mark.parametrize("subcommand", SCRIPT_SUBCOMMANDS)
def test_shared_lsp_doc_names_subcommand(subcommand):
    """shared/agents/lsp.md names every one of the script's subcommands."""
    text = LSP_SRC.read_text(encoding="utf-8")
    assert subcommand in text, (
        f"shared/agents/lsp.md is missing the subcommand name '{subcommand}'."
    )


def test_shared_lsp_doc_has_fallback_sentence():
    text = LSP_SRC.read_text(encoding="utf-8")
    assert FALLBACK_SENTENCE in text, (
        f"shared/agents/lsp.md is missing the literal fallback sentence "
        f"'{FALLBACK_SENTENCE}' (real em dash, U+2014)."
    )


# ──────────────────────────────────────────────────────────────
# The four agents no longer grant the native LSP tool
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", LSP_AGENTS)
def test_agent_does_not_grant_native_lsp_tool(agent_name):
    """None of the four agents should list the harness-native 'LSP' tool in
    tools: frontmatter any more — #621 replaced it with the bin/ script,
    reachable via the Bash tool every agent already holds."""
    text = _agent_text(agent_name)
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"agents/{agent_name}.md has no closed frontmatter block"
    frontmatter = parts[1]
    tools_line = next(
        (line for line in frontmatter.splitlines() if line.strip().startswith("tools:")),
        None,
    )
    assert tools_line is not None, f"agents/{agent_name}.md has no tools: line in frontmatter"
    tools = [t.strip() for t in tools_line.split(":", 1)[1].split(",")]
    assert "LSP" not in tools, (
        f"agents/{agent_name}.md still grants 'LSP' in tools: frontmatter — #621 dropped this "
        f"in favor of bin/swe-workbench-lsp, reachable via Bash: {tools_line!r}"
    )


# ──────────────────────────────────────────────────────────────
# Orchestrator skills carry the LSP-unavailable fallback sentence
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("skill_name", ORCHESTRATOR_SKILLS)
def test_orchestrator_skill_has_fallback_sentence(skill_name):
    """Each orchestrator skill's SKILL.md contains the literal fallback sentence."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    assert path.exists(), f"skills/{skill_name}/SKILL.md does not exist"
    text = path.read_text(encoding="utf-8")
    assert FALLBACK_SENTENCE in text, (
        f"skills/{skill_name}/SKILL.md is missing the literal fallback "
        f"sentence '{FALLBACK_SENTENCE}' (real em dash, U+2014)."
    )


# ──────────────────────────────────────────────────────────────
# docs/dependencies.md has the Language servers section
# ──────────────────────────────────────────────────────────────


def test_dependencies_doc_has_language_servers_section():
    """docs/dependencies.md contains the Language servers section header."""
    path = ROOT / "docs" / "dependencies.md"
    assert path.exists(), "docs/dependencies.md does not exist"
    text = path.read_text(encoding="utf-8")
    assert "## Language servers (optional, graceful-fallback)" in text, (
        "docs/dependencies.md is missing the "
        "'## Language servers (optional, graceful-fallback)' section."
    )
