"""Structural tests for commands/sync.md (issue #485)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
COMMAND = ROOT / "commands" / "sync.md"


def _body():
    return COMMAND.read_text(encoding="utf-8")


def test_command_file_exists():
    assert COMMAND.is_file(), "commands/sync.md must exist"


def test_frontmatter_has_description_and_argument_hint():
    body = _body()
    assert body.startswith("---")
    frontmatter = body.split("---")[1]
    assert "description:" in frontmatter
    assert "argument-hint:" in frontmatter
    assert "--rebase" in frontmatter
    assert "--check-redundancy" in frontmatter


def test_delegates_to_workflow_branch_sync_skill():
    body = _body()
    assert "swe-workbench:workflow-branch-sync" in body


def test_parses_rebase_flag():
    body = _body()
    assert "--rebase" in body
    assert "strip" in body.lower()
    assert "merge" in body.lower() and "default" in body.lower()


def test_output_contract_present():
    body = _body()
    assert "## Output" in body
    output = body.split("## Output")[1]
    assert "push" in output.lower()
    assert "--force-with-lease" in output


def test_parses_check_redundancy_flag():
    body = _body()
    assert "--check-redundancy" in body
    assert "CHECK_REDUNDANCY" in body
    assert "on|off" in body or "on | off" in body


def test_check_redundancy_stripped_from_target_and_threaded_to_skill():
    body = _body()
    strategy = body.split("## Strategy resolution")[1]
    assert "strip" in strategy.lower()
    assert "CHECK_REDUNDANCY" in strategy

    assert "swe-workbench:workflow-branch-sync" in strategy
    assert "CHECK_REDUNDANCY" in strategy.split("swe-workbench:workflow-branch-sync")[0][-400:]


def test_check_redundancy_default_off():
    body = _body()
    strategy = body.split("## Strategy resolution")[1]
    assert "absent" in strategy.lower()
    assert "off" in strategy.lower()


def test_output_documents_opt_in_redundancy_assessment():
    body = _body()
    output = body.split("## Output")[1]
    assert "--check-redundancy" in output or "redundancy" in output.lower()
    assert "opt-in" in output.lower()
