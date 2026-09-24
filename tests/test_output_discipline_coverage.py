"""Structural tests: output-discipline block coverage per writer agent.

Acceptance criteria: every code-writing agent carries the comment-discipline
and comment-scan shared blocks; every writer except code-impl (whose
`file_set` containment is strictly stronger) also carries docs-discipline;
and code-impl must NOT carry docs-discipline, guarding against reflexive
blanket embeds.
"""

from pathlib import Path

import validate

WRITERS = {
    "code-impl": {"comment-discipline.md", "comment-scan.md"},
    "debugger": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "refactorer": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "test-writer": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "e2e-test-writer": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
    "migrator": {"comment-discipline.md", "comment-scan.md", "docs-discipline.md"},
}


def _write_agent(root: Path, stem: str, blocks: set[str]) -> None:
    body = f"# {stem}\n"
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
    for stem, blocks in WRITERS.items():
        _write_agent(root, stem, (overrides or {}).get(stem, blocks))


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


def test_code_impl_with_docs_discipline_fails(reset_validate):
    overrides = {"code-impl": WRITERS["code-impl"] | {"docs-discipline.md"}}
    _write_all(reset_validate, overrides)
    validate.check_output_discipline_coverage()
    assert any(
        "code-impl.md" in f and "docs-discipline" in f for f in validate.FAILURES
    )


def test_missing_agent_file_fails(reset_validate):
    _write_all(reset_validate)
    (reset_validate / "agents" / "migrator.md").unlink()
    validate.check_output_discipline_coverage()
    assert any("migrator.md" in f for f in validate.FAILURES)
