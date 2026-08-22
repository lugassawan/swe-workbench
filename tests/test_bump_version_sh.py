"""Behavioural tests for scripts/bump-version.sh — the .version-bump.json-driven version-sync
tool scripts/release.sh delegates to instead of an inline two-file jq bump.

Each test copies the real script into an isolated tmp_path fixture tree (not the live repo) so
the declared-files list, current version, and audit-exclude entries are fully controlled per
test. The script resolves its own root from its own path (`dirname "${BASH_SOURCE[0]}"/..`), not
from cwd, so no explicit `cwd=` is needed on subprocess.run.
"""

import json
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
BUMP_VERSION_SH = ROOT / "scripts" / "bump-version.sh"


def _make_fixture_tree(root: Path, *, exclude=None) -> None:
    (root / ".claude-plugin").mkdir(parents=True)
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    script_copy = scripts_dir / "bump-version.sh"
    script_copy.write_text(BUMP_VERSION_SH.read_text(encoding="utf-8"), encoding="utf-8")
    script_copy.chmod(0o755)

    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "test-plugin", "version": "1.0.0"}), encoding="utf-8"
    )
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "test-plugin", "version": "1.0.0"}]}), encoding="utf-8"
    )
    (root / "package.json").write_text(
        json.dumps({"name": "test-plugin", "version": "1.0.0"}), encoding="utf-8"
    )
    (root / ".version-bump.json").write_text(
        json.dumps(
            {
                "files": [
                    {"path": ".claude-plugin/plugin.json", "field": ".version"},
                    {"path": ".claude-plugin/marketplace.json", "field": ".plugins[0].version"},
                    {"path": "package.json", "field": ".version"},
                ],
                "audit": {"exclude": exclude or []},
            }
        ),
        encoding="utf-8",
    )


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(root / "scripts" / "bump-version.sh"), *args],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
    )


class TestBumpMode:
    def test_writes_new_version_to_every_declared_file(self, tmp_path):
        _make_fixture_tree(tmp_path)
        result = _run(tmp_path, "9.9.9")
        assert result.returncode == 0, result.stderr
        assert json.loads((tmp_path / ".claude-plugin" / "plugin.json").read_text())["version"] == "9.9.9"
        mkt = json.loads((tmp_path / ".claude-plugin" / "marketplace.json").read_text())
        assert mkt["plugins"][0]["version"] == "9.9.9"
        assert json.loads((tmp_path / "package.json").read_text())["version"] == "9.9.9"

    def test_rejects_malformed_version(self, tmp_path):
        _make_fixture_tree(tmp_path)
        result = _run(tmp_path, "not-a-version")
        assert result.returncode != 0
        assert "must be X.Y.Z" in result.stderr

    def test_no_args_prints_usage_and_fails(self, tmp_path):
        _make_fixture_tree(tmp_path)
        result = _run(tmp_path)
        assert result.returncode != 0
        assert "Usage:" in result.stderr


class TestCheckMode:
    def test_passes_when_all_declared_files_agree(self, tmp_path):
        _make_fixture_tree(tmp_path)
        result = _run(tmp_path, "--check")
        assert result.returncode == 0, result.stderr
        assert "All declared files agree on version 1.0.0." in result.stdout

    def test_fails_on_drift(self, tmp_path):
        _make_fixture_tree(tmp_path)
        pkg = tmp_path / "package.json"
        data = json.loads(pkg.read_text())
        data["version"] = "2.0.0"
        pkg.write_text(json.dumps(data), encoding="utf-8")
        result = _run(tmp_path, "--check")
        assert result.returncode != 0
        assert "expected 1.0.0" in result.stderr


class TestAuditMode:
    def test_passes_when_no_undeclared_occurrences(self, tmp_path):
        _make_fixture_tree(tmp_path)
        result = _run(tmp_path, "--audit")
        assert result.returncode == 0, result.stderr
        assert "No undeclared occurrences of 1.0.0 found." in result.stdout

    def test_fails_on_undeclared_occurrence(self, tmp_path):
        _make_fixture_tree(tmp_path)
        (tmp_path / "stray-doc.md").write_text("version 1.0.0 hardcoded here\n", encoding="utf-8")
        result = _run(tmp_path, "--audit")
        assert result.returncode != 0
        assert "stray-doc.md" in result.stderr

    def test_excludes_declared_audit_exclude_directory(self, tmp_path):
        _make_fixture_tree(tmp_path, exclude=["node_modules"])
        nm = tmp_path / "node_modules" / "@types" / "node"
        nm.mkdir(parents=True)
        (nm / "fs.d.ts").write_text("since v1.0.0\n", encoding="utf-8")
        result = _run(tmp_path, "--audit")
        assert result.returncode == 0, result.stderr

    def test_trailing_slash_exclude_entry_still_excludes_nested_files(self, tmp_path):
        """Regression test for a real bug caught in review: _under_prefix()'s naive
        "$1" == "$2"/* pattern breaks when $2 (the declared/excluded path) itself already
        ends in "/" — the idiomatic .gitignore-style form — producing a double-slash glob
        that never matches a real single-slash path. Without stripping the trailing slash,
        this test reproduces the bug: every file under node_modules/ would wrongly surface
        as an undeclared occurrence."""
        _make_fixture_tree(tmp_path, exclude=["node_modules/"])
        nm = tmp_path / "node_modules" / "@types" / "node"
        nm.mkdir(parents=True)
        (nm / "fs.d.ts").write_text("since v1.0.0\n", encoding="utf-8")
        result = _run(tmp_path, "--audit")
        assert result.returncode == 0, result.stderr

    def test_declared_files_are_not_flagged_as_undeclared(self, tmp_path):
        _make_fixture_tree(tmp_path)
        result = _run(tmp_path, "--audit")
        assert result.returncode == 0, result.stderr
        assert "plugin.json" not in result.stdout
