"""Structural tests: output-discipline block coverage per writer agent.

The writer set is derived from tools: frontmatter (Edit or Write), so the
matrix catches a brand-new writer with no tuple edit. Explicit exemptions:
product-manager (non-code), tech-writer (docs are its lane — comment-
discipline only, no scan, no docs-discipline), and code-impl is forbidden
from docs-discipline (file_set binds strictly harder).
"""

from pathlib import Path

import validate

WRITER_TOOLS = "Read, Write, Edit, Grep, Glob, Bash"
NON_WRITER_TOOLS = "Read, Grep, Bash"

WRITERS = {
    "code-impl": {"comment-discipline.md", "comment-scan.md"},
    "debugger": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "refactorer": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "test-writer": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "e2e-test-writer": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "migrator": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "tech-writer": {"comment-discipline.md"},
    "product-manager": set(),  # exempt: non-code agent
}
NON_WRITERS = {"reviewer", "auditor"}


def _write_agent(
    root: Path, stem: str, blocks: set[str], tools: str = WRITER_TOOLS
) -> None:
    body = (
        "---\n"
        f"name: {stem}\n"
        f"tools: {tools}\n"
        "---\n"
        f"# {stem}\n"
    )
    for block in sorted(blocks):
        body += (
            f"<!-- BEGIN shared/agents/{block} -->\n"
            f"content of {block}\n"
            f"<!-- END shared/agents/{block} -->\n"
        )
    agent = root / "agents" / f"{stem}.md"
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text(body, encoding="utf-8")


def _write_all(root: Path, overrides: dict[str, set[str]] | None = None) -> None:
    for stem, blocks in {**WRITERS, **{s: set() for s in NON_WRITERS}}.items():
        tools = NON_WRITER_TOOLS if stem in NON_WRITERS else WRITER_TOOLS
        _write_agent(root, stem, (overrides or {}).get(stem, blocks), tools)


def test_full_coverage_passes(reset_validate):
    _write_all(reset_validate)
    validate.check_output_discipline_coverage()
    assert validate.FAILURES == []


def test_missing_comment_discipline_fails(reset_validate):
    overrides = {"migrator": WRITERS["migrator"] - {"comment-discipline.md"}}
    _write_all(reset_validate, overrides)
    validate.check_output_discipline_coverage()
    assert any(
        "migrator.md" in f and "comment-discipline" in f for f in validate.FAILURES
    )


def test_missing_docs_discipline_fails(reset_validate):
    overrides = {"test-writer": WRITERS["test-writer"] - {"docs-discipline.md"}}
    _write_all(reset_validate, overrides)
    validate.check_output_discipline_coverage()
    assert any(
        "test-writer.md" in f and "docs-discipline" in f for f in validate.FAILURES
    )


def test_missing_comment_scan_fails(reset_validate):
    overrides = {"e2e-test-writer": WRITERS["e2e-test-writer"] - {"comment-scan.md"}}
    _write_all(reset_validate, overrides)
    validate.check_output_discipline_coverage()
    assert any(
        "e2e-test-writer.md" in f and "comment-scan" in f for f in validate.FAILURES
    )


def test_new_writer_without_blocks_fails(reset_validate):
    """Derivation catch: an unknown agent with Edit tools needs the blocks."""
    _write_all(reset_validate)
    _write_agent(reset_validate, "fresh-writer", set())
    validate.check_output_discipline_coverage()
    assert any(
        "fresh-writer.md" in f and "comment-discipline" in f
        for f in validate.FAILURES
    )


def test_non_writer_without_blocks_passes(reset_validate):
    """Read-only agents are outside the matrix entirely."""
    _write_all(reset_validate)
    validate.check_output_discipline_coverage()
    assert not any("reviewer.md" in f for f in validate.FAILURES)


def test_code_impl_with_docs_discipline_fails(reset_validate):
    overrides = {"code-impl": WRITERS["code-impl"] | {"docs-discipline.md"}}
    _write_all(reset_validate, overrides)
    validate.check_output_discipline_coverage()
    assert any(
        "code-impl.md" in f and "docs-discipline" in f for f in validate.FAILURES
    )


def test_deleted_writer_is_out_of_scope(reset_validate):
    """Derivation means a deleted writer produces no coverage failure —
    agent existence itself is pinned by test_shared_relocation's inventory
    and the Pi contract golden inventory, not by this check."""
    _write_all(reset_validate)
    (reset_validate / "agents" / "migrator.md").unlink()
    validate.check_output_discipline_coverage()
    assert not any("migrator.md" in f for f in validate.FAILURES)


def test_unreadable_cached_agent_fails(reset_validate):
    _write_all(reset_validate)
    agent_md = reset_validate / "agents" / "debugger.md"
    validate.check_output_discipline_coverage(cache=({agent_md: None}, {}))
    assert any(
        "debugger.md" in f and "could not read" in f for f in validate.FAILURES
    )


def test_stale_exemption_fails(reset_validate):
    """An exemption naming a non-writer is stale config, not a free pass."""
    _write_all(reset_validate)
    validate._DOCS_DISCIPLINE_EXEMPT = frozenset({"ghost"})
    try:
        validate.check_output_discipline_coverage()
        assert any(
            "_DOCS_DISCIPLINE_EXEMPT" in f and "ghost" in f
            for f in validate.FAILURES
        )
    finally:
        validate._DOCS_DISCIPLINE_EXEMPT = frozenset({"tech-writer"})
