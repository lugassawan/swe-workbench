"""Guard tests for issue #603: shared/ relocated out of agents/ and commands/.

Prevents regression back to `agents/shared/*.md` or `commands/shared/*.md` —
both directories must remain outside the two discovery roots.
"""

import re

from validate import ROOT

EXPECTED_SHARED_AGENT_STEMS = {
    "comment-scan",
    "external-repo-reading",
    "language-skill-required",
    "languages",
    "lsp",
    "preload-canary-citation",
    "principles",
    "severity-output-contract",
    "skill-catalog-pointer",
    "workflows",
}

EXPECTED_SHARED_COMMAND_STEMS = {
    "interrogation-prelude",
    "ticket-context-prelude",
}

_OLD_INCLUDE_RE = re.compile(r"@\./shared/")
_SENTINEL_BEGIN_RE = re.compile(r"<!-- BEGIN shared/agents/([\w-]+\.md) -->")


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


def test_every_sentinel_block_source_resolves_on_disk():
    """Every sentinel BEGIN marker in agents/*.md must name a shared/agents/*.md
    file that actually exists (#619 — the dead '@../shared/agents/*.md' include
    this test used to require at least one of has been fully replaced by the
    sentinel-delimited block mechanism; zero old-style includes should remain)."""
    shared_agents_dir = ROOT / "shared" / "agents"
    found_any = False
    for agent_file in (ROOT / "agents").glob("*.md"):
        text = agent_file.read_text(encoding="utf-8")
        for match in _SENTINEL_BEGIN_RE.finditer(text):
            found_any = True
            target = shared_agents_dir / match.group(1)
            assert target.is_file(), (
                f"{agent_file.name} has a sentinel block for {match.group(0)} "
                f"but {target} does not exist"
            )
    assert found_any, (
        "expected at least one '<!-- BEGIN shared/agents/*.md -->' sentinel block "
        "in agents/*.md (e.g. the skill-catalog-pointer block, which every agent carries)"
    )


def test_no_old_style_shared_include_survives_in_agents():
    for agent_file in (ROOT / "agents").glob("*.md"):
        text = agent_file.read_text(encoding="utf-8")
        assert not _OLD_INCLUDE_RE.search(text), (
            f"{agent_file.name} still references the old @./shared/ include form"
        )
