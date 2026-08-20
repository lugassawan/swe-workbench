"""Acceptance-pinning tests — LSP code-intelligence literacy (#559).

Pins the real, already-shipped content added across Tasks 1-4 of this
feature: the four agents that grant LSP in their tools: frontmatter and
reference the shared LSP doc, shared/agents/lsp.md's nine named operations,
the three orchestrator skills' LSP-unavailable fallback sentence, and
docs/dependencies.md's Language servers section.

This is a regression suite against the real repo tree, not a red-green
TDD exercise — every test here should pass immediately and simply guard
against future drift. Matches the style of test_agent_language_catalog.py:
module-level ROOT constant, direct .read_text() on real files, no tmp_path
or reset_validate fixture.
"""

from pathlib import Path

import pytest

from helpers import sentinel_block

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"
SHARED_DIR = ROOT / "shared"
LSP_SRC = SHARED_DIR / "agents" / "lsp.md"

# The four agents this feature grants LSP to.
LSP_AGENTS = ["reviewer", "auditor", "debugger", "refactorer"]

# The nine LSP operations named in shared/agents/lsp.md.
LSP_OPERATIONS = [
    "goToDefinition",
    "findReferences",
    "hover",
    "documentSymbol",
    "workspaceSymbol",
    "goToImplementation",
    "prepareCallHierarchy",
    "incomingCalls",
    "outgoingCalls",
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


def _agent_frontmatter(name: str) -> str:
    """Return the raw text between the first two '---' lines."""
    text = _agent_text(name)
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"agents/{name}.md has no closed frontmatter block"
    return parts[1]


# ──────────────────────────────────────────────────────────────
# Agent tools: grants LSP + references @../shared/agents/lsp.md
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", LSP_AGENTS)
def test_agent_grants_lsp_tool(agent_name):
    """Each LSP agent's tools: frontmatter scalar lists LSP."""
    frontmatter = _agent_frontmatter(agent_name)
    tools_line = next(
        (line for line in frontmatter.splitlines() if line.strip().startswith("tools:")),
        None,
    )
    assert tools_line is not None, f"agents/{agent_name}.md has no tools: line in frontmatter"
    tools = [t.strip() for t in tools_line.split(":", 1)[1].split(",")]
    assert "LSP" in tools, (
        f"agents/{agent_name}.md tools: frontmatter is missing 'LSP': {tools_line!r}"
    )


@pytest.mark.parametrize("agent_name", LSP_AGENTS)
def test_agent_references_shared_lsp_doc(agent_name):
    """Each LSP agent's body carries the lsp.md sentinel block, byte-identical
    to shared/agents/lsp.md (#619 — a plain include string never proved the
    include actually resolved to real content)."""
    text = _agent_text(agent_name)
    block = sentinel_block(text, "lsp.md")
    assert block is not None, (
        f"agents/{agent_name}.md is missing the "
        "'<!-- BEGIN shared/agents/lsp.md -->' sentinel block."
    )
    source = LSP_SRC.read_text(encoding="utf-8")
    assert block == source, (
        f"agents/{agent_name}.md's lsp.md block has drifted from shared/agents/lsp.md — "
        "run python3 scripts/sync-shared-blocks.py --write"
    )


# ──────────────────────────────────────────────────────────────
# No background: key (pins Spike 3's resolution)
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_name", LSP_AGENTS)
def test_agent_has_no_background_key(agent_name):
    """No LSP agent carries a background: key in frontmatter.

    An agent with no `background` key keeps `LSP` intact (Spike 3's
    resolution). This guards against a future regression that adds one.
    """
    frontmatter = _agent_frontmatter(agent_name)
    has_background_key = any(
        line.strip().startswith("background:") for line in frontmatter.splitlines()
    )
    assert not has_background_key, (
        f"agents/{agent_name}.md unexpectedly has a 'background:' key in "
        "frontmatter — this key is known to strip LSP from an agent's "
        "effective toolset."
    )


# ──────────────────────────────────────────────────────────────
# shared/agents/lsp.md names all nine operations
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("operation", LSP_OPERATIONS)
def test_shared_lsp_doc_names_operation(operation):
    """shared/agents/lsp.md names every one of the nine LSP operations."""
    path = SHARED_DIR / "agents" / "lsp.md"
    assert path.exists(), "shared/agents/lsp.md does not exist"
    text = path.read_text(encoding="utf-8")
    assert operation in text, (
        f"shared/agents/lsp.md is missing the operation name '{operation}'."
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
