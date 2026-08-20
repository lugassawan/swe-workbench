"""Guard tests for issue #603: shared/ relocated out of agents/ and commands/.

Prevents regression back to `agents/shared/*.md` or `commands/shared/*.md` —
both directories must remain outside the two discovery roots.
"""

import re

from validate import ROOT

EXPECTED_SHARED_AGENT_STEMS = {
    "comment-scan",
    "external-repo-reading",
    "languages",
    "lsp",
    "principles",
    "severity-output-contract",
    "workflows",
}

EXPECTED_SHARED_COMMAND_STEMS = {
    "interrogation-prelude",
    "ticket-context-prelude",
}

_INCLUDE_RE = re.compile(r"@\.\./shared/agents/([\w-]+\.md)")
_OLD_INCLUDE_RE = re.compile(r"@\./shared/")


def test_no_shared_subdir_under_agents_or_commands():
    assert not (ROOT / "agents" / "shared").exists()
    assert not (ROOT / "commands" / "shared").exists()
    assert not list((ROOT / "agents").rglob("shared/*.md"))
    assert not list((ROOT / "commands").rglob("shared/*.md"))


def test_shared_agents_dir_has_exactly_expected_stems():
    shared_agents_dir = ROOT / "shared" / "agents"
    stems = {p.stem for p in shared_agents_dir.glob("*.md")}
    assert stems == EXPECTED_SHARED_AGENT_STEMS


def test_shared_commands_dir_has_exactly_expected_stems():
    shared_commands_dir = ROOT / "shared" / "commands"
    stems = {p.stem for p in shared_commands_dir.glob("*.md")}
    assert stems == EXPECTED_SHARED_COMMAND_STEMS


def test_agents_dir_walk_finds_only_top_level_agent_files():
    all_md = list((ROOT / "agents").rglob("*.md"))
    top_level_md = list((ROOT / "agents").glob("*.md"))
    assert all_md == top_level_md
    assert len(top_level_md) == 22


def test_commands_dir_walk_finds_only_top_level_command_files():
    all_md = list((ROOT / "commands").rglob("*.md"))
    top_level_md = list((ROOT / "commands").glob("*.md"))
    assert all_md == top_level_md
    assert len(top_level_md) == 21


def test_every_shared_agent_include_resolves_on_disk():
    shared_agents_dir = ROOT / "shared" / "agents"
    found_any = False
    for agent_file in (ROOT / "agents").glob("*.md"):
        text = agent_file.read_text(encoding="utf-8")
        for match in _INCLUDE_RE.finditer(text):
            found_any = True
            target = shared_agents_dir / match.group(1)
            assert target.is_file(), (
                f"{agent_file.name} references {match.group(0)} "
                f"but {target} does not exist"
            )
    assert found_any, "expected at least one @../shared/agents/*.md include in agents/*.md"


def test_no_old_style_shared_include_survives_in_agents():
    for agent_file in (ROOT / "agents").glob("*.md"):
        text = agent_file.read_text(encoding="utf-8")
        assert not _OLD_INCLUDE_RE.search(text), (
            f"{agent_file.name} still references the old @./shared/ include form"
        )
