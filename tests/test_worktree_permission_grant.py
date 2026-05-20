"""Tests for hooks/worktree_permission_grant.sh.

Subprocess-driven so they exercise real shell logic.  Each test gets an
isolated temp git repo + linked worktree via the wt_env fixture.
"""

import json
import subprocess
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
HOOK_SH = ROOT / "hooks" / "worktree_permission_grant.sh"

_ALLOW_JSON = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "worktree allowlist grant (.claude/settings.local.json)",
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_CLEAN_ENV,
        check=check,
        capture_output=True,
        text=True,
    )


def _run(stdin_json: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK_SH)],
        input=json.dumps(stdin_json),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


def _cc_abs(path: Path) -> str:
    """Return the Claude Code //absolute-path marker form for a Path."""
    return f"//{str(path).lstrip('/')}"


def _settings(wt: Path, allow: list[str]) -> None:
    """Write .claude/settings.local.json into a worktree."""
    (wt / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"allow": allow}})
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wt_env(tmp_path: Path):
    """Create a main git repo + one linked worktree.

    Layout:
      tmp_path/main/         ← main git checkout
      tmp_path/wts/current/  ← linked worktree (CWD under test)
      tmp_path/wts/other/    ← sibling path referenced in allowlists
    """
    main = tmp_path / "main"
    main.mkdir()
    wts = tmp_path / "wts"
    wts.mkdir()

    _git("init", "-q", "-b", "main", cwd=main)
    _git("config", "user.email", "t@t.com", cwd=main)
    _git("config", "user.name", "T", cwd=main)
    (main / "README").write_text("init")
    _git("add", ".", cwd=main)
    _git(
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "user.email=t@t.com",
        "-c",
        "user.name=T",
        "commit",
        "-qm",
        "[chore] init",
        cwd=main,
    )

    current = wts / "current"
    _git("worktree", "add", "-b", "feature/current", str(current), cwd=main)
    (current / ".claude").mkdir()

    return {
        "main": main,
        "wt": current,
        "other": wts / "other",
        "wts": wts,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorktreePermissionGrant:
    def test_whole_tree_sibling_grant_allows(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Read({_cc_abs(other)}/**)"])
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "README")},
            }
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == _ALLOW_JSON

    def test_subdirectory_glob_matches(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Read({_cc_abs(other)}/skills/**)"])
        (wt / "skills" / "x").mkdir(parents=True)
        (wt / "skills" / "x" / "y.md").write_text("content")
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "skills" / "x" / "y.md")},
            }
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == _ALLOW_JSON

    def test_subdirectory_glob_no_match(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Read({_cc_abs(other)}/skills/**)"])
        (wt / "tests").mkdir()
        (wt / "tests" / "x.py").write_text("pass")
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "tests" / "x.py")},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_main_checkout_is_noop(self, wt_env):
        main = wt_env["main"]
        (main / ".claude").mkdir(exist_ok=True)
        (main / ".claude" / "settings.local.json").write_text(
            json.dumps({"permissions": {"allow": [f"Read({_cc_abs(main)}/**)"]}})
        )
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(main / "README")},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_missing_settings_is_noop(self, wt_env):
        wt = wt_env["wt"]
        # .claude/ exists but settings.local.json is absent
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "README")},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_edit_without_edit_entries_is_noop(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Read({_cc_abs(other)}/**)"])
        result = _run(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(wt / "README")},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_edit_grant_allows(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Edit({_cc_abs(other)}/**)"])
        result = _run(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(wt / "README")},
            }
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == _ALLOW_JSON

    def test_out_of_tree_path_is_denied(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Read({_cc_abs(other)}/**)"])
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/etc/passwd"},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_dotdot_traversal_is_denied(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Read({_cc_abs(other)}/**)"])
        traversal = str(wt) + "/subdir/../../etc/passwd"
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": traversal},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_relative_glob_matches(self, wt_env):
        wt = wt_env["wt"]
        _settings(wt, ["Read(skills/**)"])
        (wt / "skills").mkdir()
        (wt / "skills" / "foo.md").write_text("content")
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "skills" / "foo.md")},
            }
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == _ALLOW_JSON

    def test_unrelated_abs_grant_is_skipped(self, wt_env):
        wt = wt_env["wt"]
        _settings(wt, ["Read(//tmp/x/**)"])
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "README")},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_malformed_stdin_is_failopen(self):
        result = subprocess.run(
            ["bash", str(HOOK_SH)],
            input="not-valid-json{{{",
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_symlink_escape_denied(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        secret = wt_env["wts"].parent / "secret.txt"
        secret.write_text("secret")
        link = wt / "escape_link"
        link.symlink_to(secret)
        _settings(wt, [f"Read({_cc_abs(other)}/**)"])
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(link)},
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_write_grant_allows(self, wt_env):
        wt, other = wt_env["wt"], wt_env["other"]
        _settings(wt, [f"Write({_cc_abs(other)}/**)"])
        result = _run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(wt / "new_file.txt")},
            }
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == _ALLOW_JSON

    def test_single_slash_abs_glob_matches(self, wt_env):
        wt = wt_env["wt"]
        _settings(wt, [f"Read({str(wt)}/**)"])
        result = _run(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": str(wt / "README")},
            }
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == _ALLOW_JSON
