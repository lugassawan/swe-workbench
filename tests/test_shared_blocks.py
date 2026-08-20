"""Tests for the sentinel-delimited shared-block inlining mechanism (issue #619):
scripts/sync-shared-blocks.py and the validate.py checks that guard it.

Most fixtures below are isolated temp trees built from scratch (Task 1's original
tests, written before agents/ was migrated). TestLiveTreeIntegration at the bottom
is the exception: it runs against the real, now-migrated agents/ and shared/agents/
directories (Task 2 replaced every dead '@../shared/agents/*.md' include with a
sentinel block) — this is the direct, load-bearing regression guard for #619 itself.
"""

import importlib.util
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import validate
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent


def _load_sync_module():
    path = ROOT / "scripts" / "sync-shared-blocks.py"
    loader = SourceFileLoader("sync_shared_blocks", str(path))
    spec = importlib.util.spec_from_file_location("sync_shared_blocks", path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync_shared_blocks"] = module
    spec.loader.exec_module(module)
    return module


sb = _load_sync_module()


# ──────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────

def _block(name, content):
    """Build a sentinel block for *name* wrapping *content* (which must end in '\\n')."""
    return f"<!-- BEGIN {name} -->\n{content}<!-- END {name} -->\n"


def _write_fragment(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_agent(root, stem, body):
    agents_dir = root / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {stem}\ndescription: d\ntools: Read\n---\n\n"
    path = agents_dir / f"{stem}.md"
    path.write_text(fm + body, encoding="utf-8")
    return path


def _setup_minimal_catalog(root):
    """Empty skills/ + empty (but present) slice files, so check_catalog_completeness's
    unchanged slice-parity audit (lines 937-968) passes trivially and doesn't pollute
    FAILURES for tests targeting the reworked per-agent sentinel-marker logic."""
    (root / "skills").mkdir(parents=True, exist_ok=True)
    shared_agents = root / "shared" / "agents"
    shared_agents.mkdir(parents=True, exist_ok=True)
    for slice_file in ("principles.md", "languages.md", "workflows.md"):
        (shared_agents / slice_file).write_text("\n", encoding="utf-8")


POINTER_NAME = "shared/agents/skill-catalog-pointer.md"
LANGUAGE_NAME = "shared/agents/language-skill-required.md"
POINTER_CONTENT = "Skill catalog pointer.\n"
LANGUAGE_CONTENT = "Language skill requirement.\n"


# ──────────────────────────────────────────────
# scripts/sync-shared-blocks.py — --check
# ──────────────────────────────────────────────

class TestSyncScriptCheck:
    def test_passes_when_in_sync(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_fragment(tmp_path, "shared/agents/lsp.md", "LSP content.\n")
        _write_agent(tmp_path, "my-agent", _block("shared/agents/lsp.md", "LSP content.\n"))
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._check(agent_files) == 0
        out = capsys.readouterr()
        assert "no drift" in out.out.lower()

    def test_fails_when_drifted(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_fragment(tmp_path, "shared/agents/lsp.md", "Updated content.\n")
        _write_agent(tmp_path, "my-agent", _block("shared/agents/lsp.md", "Stale content.\n"))
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._check(agent_files) == 1
        err = capsys.readouterr().err
        assert "drifted" in err

    def test_fails_when_source_missing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_agent(tmp_path, "my-agent", _block("shared/agents/ghost.md", "Ghost content.\n"))
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._check(agent_files) == 1
        err = capsys.readouterr().err
        assert "does not exist" in err

    def test_fails_on_begin_without_matching_end(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_fragment(tmp_path, "shared/agents/lsp.md", "LSP content.\n")
        _write_agent(tmp_path, "my-agent", "<!-- BEGIN shared/agents/lsp.md -->\nLSP content.\n")
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._check(agent_files) == 1
        err = capsys.readouterr().err
        assert "no matching END" in err

    def test_file_with_no_sentinel_pairs_not_flagged(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_agent(tmp_path, "my-agent", "Nothing to see here.\n")
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._check(agent_files) == 0
        out = capsys.readouterr()
        assert "no drift" in out.out.lower()


# ──────────────────────────────────────────────
# scripts/sync-shared-blocks.py — --write
# ──────────────────────────────────────────────

class TestSyncScriptWrite:
    def test_repairs_drift_and_leaves_rest_untouched(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_fragment(tmp_path, "shared/agents/lsp.md", "Updated content.\n")
        agent_path = _write_agent(
            tmp_path,
            "my-agent",
            "Before text.\n\n" + _block("shared/agents/lsp.md", "Stale content.\n") + "\nAfter text.\n",
        )
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._write(agent_files) == 0
        new_text = agent_path.read_text(encoding="utf-8")
        assert "Updated content.\n" in new_text
        assert "Stale content." not in new_text
        assert "Before text.\n" in new_text
        assert "After text.\n" in new_text
        # Re-checking must now report clean.
        assert sb._check(agent_files) == 0

    def test_source_missing_stays_an_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_agent(tmp_path, "my-agent", _block("shared/agents/ghost.md", "Ghost content.\n"))
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._write(agent_files) == 1

    def test_never_creates_new_sentinel_pair(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_fragment(tmp_path, "shared/agents/lsp.md", "LSP content.\n")
        agent_path = _write_agent(tmp_path, "my-agent", "No sentinel block in this agent at all.\n")
        before = agent_path.read_text(encoding="utf-8")
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._write(agent_files) == 0
        assert agent_path.read_text(encoding="utf-8") == before

    def test_already_in_sync_reports_nothing_changed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sb, "ROOT", tmp_path)
        _write_fragment(tmp_path, "shared/agents/lsp.md", "LSP content.\n")
        _write_agent(tmp_path, "my-agent", _block("shared/agents/lsp.md", "LSP content.\n"))
        agent_files = sorted((tmp_path / "agents").glob("*.md"))
        assert sb._write(agent_files) == 0
        out = capsys.readouterr().out
        assert "nothing needed changing" in out.lower()


# ──────────────────────────────────────────────
# validate.check_shared_blocks_in_sync
# ──────────────────────────────────────────────

class TestCheckSharedBlocksInSync:
    def test_in_sync_passes(self, reset_validate):
        root = reset_validate
        _write_fragment(root, "shared/agents/lsp.md", "LSP content.\n")
        _write_agent(root, "my-agent", _block("shared/agents/lsp.md", "LSP content.\n"))
        validate.check_shared_blocks_in_sync()
        assert validate.FAILURES == []

    def test_drifted_fails(self, reset_validate):
        root = reset_validate
        _write_fragment(root, "shared/agents/lsp.md", "Updated content.\n")
        _write_agent(root, "my-agent", _block("shared/agents/lsp.md", "Stale content.\n"))
        validate.check_shared_blocks_in_sync()
        assert any("drifted" in f for f in validate.FAILURES)

    def test_missing_source_fails(self, reset_validate):
        root = reset_validate
        _write_agent(root, "my-agent", _block("shared/agents/ghost.md", "Ghost content.\n"))
        validate.check_shared_blocks_in_sync()
        assert any("does not exist" in f for f in validate.FAILURES)

    def test_begin_without_end_fails(self, reset_validate):
        root = reset_validate
        _write_fragment(root, "shared/agents/lsp.md", "LSP content.\n")
        _write_agent(root, "my-agent", "<!-- BEGIN shared/agents/lsp.md -->\nLSP content.\n")
        validate.check_shared_blocks_in_sync()
        assert any("no matching END" in f for f in validate.FAILURES)

    def test_no_sentinel_pairs_passes(self, reset_validate):
        root = reset_validate
        _write_agent(root, "my-agent", "Nothing to see here.\n")
        validate.check_shared_blocks_in_sync()
        assert validate.FAILURES == []


# ──────────────────────────────────────────────
# validate.check_no_inert_at_includes
# ──────────────────────────────────────────────

class TestCheckNoInertAtIncludes:
    def test_agent_with_parent_relative_include_fails(self, reset_validate):
        root = reset_validate
        _write_agent(root, "my-agent", "See @../shared/agents/lsp.md for details.\n")
        validate.check_no_inert_at_includes()
        assert any("619" in f for f in validate.FAILURES)

    def test_agent_with_same_dir_include_fails(self, reset_validate):
        root = reset_validate
        _write_agent(root, "my-agent", "See @./shared/x.md for details.\n")
        validate.check_no_inert_at_includes()
        assert len(validate.FAILURES) == 1

    def test_command_with_inert_include_fails(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nSee @../shared/agents/lsp.md.\n", encoding="utf-8",
        )
        validate.check_no_inert_at_includes()
        assert len(validate.FAILURES) == 1

    def test_skill_md_with_inert_include_fails(self, reset_validate):
        root = reset_validate
        skill_dir = root / "skills" / "my-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: d\n---\n\nSee @../shared/agents/lsp.md.\n",
            encoding="utf-8",
        )
        validate.check_no_inert_at_includes()
        assert len(validate.FAILURES) == 1

    def test_nested_skill_file_with_inert_include_fails(self, reset_validate):
        root = reset_validate
        nested = root / "skills" / "my-skill" / "examples"
        nested.mkdir(parents=True, exist_ok=True)
        (root / "skills" / "my-skill").mkdir(parents=True, exist_ok=True)
        (root / "skills" / "my-skill" / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: d\n---\nBody.\n", encoding="utf-8",
        )
        (nested / "example.md").write_text("See @./shared/x.md.\n", encoding="utf-8")
        validate.check_no_inert_at_includes()
        assert any("example.md" in f for f in validate.FAILURES)

    def test_clean_files_pass(self, reset_validate):
        root = reset_validate
        _write_agent(root, "my-agent", _block("shared/agents/lsp.md", "LSP content.\n"))
        validate.check_no_inert_at_includes()
        assert validate.FAILURES == []

    def test_two_occurrences_on_one_line_yield_two_failures(self, reset_validate):
        root = reset_validate
        _write_agent(
            root, "my-agent",
            "See @../shared/agents/principles.md and @../shared/agents/languages.md.\n",
        )
        validate.check_no_inert_at_includes()
        assert len(validate.FAILURES) == 2


# ──────────────────────────────────────────────
# validate.check_language_pointer_matches_disk
# ──────────────────────────────────────────────

class TestCheckLanguagePointerMatchesDisk:
    def _write_language_skills(self, root, ids):
        skills_dir = root / "skills"
        for sid in ids:
            sd = skills_dir / sid
            sd.mkdir(parents=True, exist_ok=True)
            (sd / "SKILL.md").write_text(f"---\nname: {sid}\ndescription: d\n---\n", encoding="utf-8")

    def test_matching_set_passes(self, reset_validate):
        root = reset_validate
        self._write_language_skills(root, ["language-python", "language-go"])
        _write_fragment(
            root, LANGUAGE_NAME,
            "- `swe-workbench:language-python`\n- `swe-workbench:language-go`\n",
        )
        validate.check_language_pointer_matches_disk()
        assert validate.FAILURES == []

    def test_missing_from_pointer_fails(self, reset_validate):
        root = reset_validate
        self._write_language_skills(root, ["language-python", "language-go"])
        _write_fragment(root, LANGUAGE_NAME, "- `swe-workbench:language-python`\n")
        validate.check_language_pointer_matches_disk()
        assert any("language-go" in f and "missing" in f for f in validate.FAILURES)

    def test_stale_in_pointer_fails(self, reset_validate):
        root = reset_validate
        self._write_language_skills(root, ["language-python"])
        _write_fragment(
            root, LANGUAGE_NAME,
            "- `swe-workbench:language-python`\n- `swe-workbench:language-rust`\n",
        )
        validate.check_language_pointer_matches_disk()
        assert any("language-rust" in f and "stale" in f for f in validate.FAILURES)

    def test_missing_pointer_file_fails(self, reset_validate):
        root = reset_validate
        self._write_language_skills(root, ["language-python"])
        validate.check_language_pointer_matches_disk()
        assert any("missing" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# validate.check_catalog_completeness — reworked per-agent sentinel logic
# ──────────────────────────────────────────────

class TestCheckCatalogCompletenessSentinelMarkers:
    def test_agent_with_both_markers_passes(self, reset_validate):
        root = reset_validate
        _setup_minimal_catalog(root)
        body = _block(POINTER_NAME, POINTER_CONTENT) + "\n" + _block(LANGUAGE_NAME, LANGUAGE_CONTENT)
        _write_agent(root, "my-agent", body)
        validate.check_catalog_completeness()
        assert validate.FAILURES == []

    def test_non_code_agent_needs_pointer_only(self, reset_validate):
        root = reset_validate
        _setup_minimal_catalog(root)
        body = _block(POINTER_NAME, POINTER_CONTENT)
        _write_agent(root, "product-manager", body)
        validate.check_catalog_completeness()
        assert validate.FAILURES == []

    def test_missing_pointer_marker_fails(self, reset_validate):
        root = reset_validate
        _setup_minimal_catalog(root)
        body = _block(LANGUAGE_NAME, LANGUAGE_CONTENT)
        _write_agent(root, "my-agent", body)
        validate.check_catalog_completeness()
        assert any("skill-catalog-pointer" in f for f in validate.FAILURES)

    def test_missing_language_marker_for_code_agent_fails(self, reset_validate):
        root = reset_validate
        _setup_minimal_catalog(root)
        body = _block(POINTER_NAME, POINTER_CONTENT)
        _write_agent(root, "my-agent", body)
        validate.check_catalog_completeness()
        assert any("language-skill-required" in f for f in validate.FAILURES)

    def test_non_code_agent_missing_language_marker_still_passes(self, reset_validate):
        root = reset_validate
        _setup_minimal_catalog(root)
        body = _block(POINTER_NAME, POINTER_CONTENT)
        _write_agent(root, "product-manager", body)
        validate.check_catalog_completeness()
        assert not any("language-skill-required" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# Live-tree integration (#619) — the assertion that would have caught it
# ──────────────────────────────────────────────
#
# Unlike every class above, these run against the real agents/ and
# shared/agents/ directories rather than an isolated tmp_path fixture. The
# original #619 regression was that a test asserted an include *string* was
# present in an agent body, never that it resolved to real content — that
# gap only shows up against the live tree, where the migration (Task 2)
# either did or didn't actually happen.

_POINTER_MARKER = "<!-- BEGIN shared/agents/skill-catalog-pointer.md -->"
_LANGUAGE_MARKER = "<!-- BEGIN shared/agents/language-skill-required.md -->"
_AGENTS_DIR = ROOT / "agents"
_SHARED_AGENTS_DIR = ROOT / "shared" / "agents"
_SYNC_SCRIPT = ROOT / "scripts" / "sync-shared-blocks.py"


class TestLiveTreeIntegration:
    def test_every_agent_carries_pointer_block(self):
        agent_files = sorted(_AGENTS_DIR.glob("*.md"))
        assert agent_files, "expected at least one agents/*.md file"
        for agent_path in agent_files:
            text = agent_path.read_text(encoding="utf-8")
            assert _POINTER_MARKER in text, (
                f"agents/{agent_path.name} is missing the skill-catalog-pointer sentinel block"
            )

    def test_every_code_touching_agent_carries_language_block(self):
        agent_files = sorted(_AGENTS_DIR.glob("*.md"))
        code_touching = [p for p in agent_files if p.stem not in validate._NON_CODE_AGENTS]
        assert code_touching, "expected at least one code-touching agent"
        for agent_path in code_touching:
            text = agent_path.read_text(encoding="utf-8")
            assert _LANGUAGE_MARKER in text, (
                f"agents/{agent_path.name} is missing the language-skill-required sentinel block"
            )

    def test_every_sentinel_block_is_byte_identical_to_its_source(self):
        """The direct, load-bearing assertion for #619's regression class: a future
        edit to a shared fragment without re-running sync-shared-blocks.py must fail
        here, not silently ship stale content to every agent that inlined it."""
        agent_files = sorted(_AGENTS_DIR.glob("*.md"))
        checked_any = False
        for agent_path in agent_files:
            text = agent_path.read_text(encoding="utf-8")
            for name, inner, _, _ in sb._iter_sentinel_pairs(text):
                checked_any = True
                assert inner is not None, (
                    f"agents/{agent_path.name}: BEGIN {name} has no matching END marker"
                )
                source_path = ROOT / name
                assert source_path.is_file(), (
                    f"agents/{agent_path.name}: block for {name} but that source file does not exist"
                )
                source_text = source_path.read_text(encoding="utf-8")
                assert inner == source_text, (
                    f"agents/{agent_path.name}'s {name} block has drifted from source — "
                    "run python3 scripts/sync-shared-blocks.py --write"
                )
        assert checked_any, "expected at least one sentinel block across agents/*.md"

    def test_no_inert_at_includes_survive_repo_wide(self, monkeypatch):
        """No '@../shared/' or '@./shared/' include may remain anywhere under
        agents/, commands/, or skills/ — Claude Code never expands them (#619)."""
        monkeypatch.setattr(validate, "ROOT", ROOT)
        validate.FAILURES.clear()
        validate.check_no_inert_at_includes()
        assert validate.FAILURES == [], f"validate.py failures: {validate.FAILURES}"

    def test_sync_script_check_passes_against_real_tree(self):
        result = subprocess.run(
            [sys.executable, str(_SYNC_SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0, (
            f"scripts/sync-shared-blocks.py --check failed against the real tree:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "no drift" in result.stdout.lower()

    def test_sync_script_write_is_idempotent_against_real_tree(self, tmp_path):
        """--write must report 'Nothing needed changing' against a copy of the real
        tree, since Task 2's inlined copies are already byte-exact — proving that,
        never mutates the live working tree; runs against a throwaway tmp copy."""
        tmp_root = tmp_path / "repo_copy"
        shutil.copytree(_AGENTS_DIR, tmp_root / "agents")
        shutil.copytree(_SHARED_AGENTS_DIR, tmp_root / "shared" / "agents")
        scripts_dir = tmp_root / "scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copy2(_SYNC_SCRIPT, scripts_dir / "sync-shared-blocks.py")

        result = subprocess.run(
            [sys.executable, str(scripts_dir / "sync-shared-blocks.py"), "--write"],
            cwd=tmp_root,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0, (
            f"scripts/sync-shared-blocks.py --write failed against the tmp copy:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "nothing needed changing" in result.stdout.lower(), (
            f"expected --write to be a no-op against an already-synced copy, got:\n{result.stdout}"
        )
        # Confirm the copy itself was left byte-identical to the real tree (no
        # accidental mutation, i.e. genuine idempotency, not a false-positive no-op).
        for agent_path in sorted((tmp_root / "agents").glob("*.md")):
            original = (_AGENTS_DIR / agent_path.name).read_text(encoding="utf-8")
            assert agent_path.read_text(encoding="utf-8") == original
