"""Light contract tests for scripts/rtk-worktree-matrix.sh.

The script itself drives headless `claude -p` sessions and is a manual regression check
(not run in CI); these tests only pin its CLI surface and that it fails fast, before
creating any scratch state, when a prerequisite is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "rtk-worktree-matrix.sh"
BASH = shutil.which("bash") or "/bin/bash"


def _run(args, env, timeout=30):
    return subprocess.run(
        [BASH, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=timeout
    )


def _env_with_tools(tmp_path: Path, tools) -> dict:
    tool_bin = tmp_path / "tool-bin"
    tool_bin.mkdir()
    for name in tools:
        real = shutil.which(name)
        assert real, f"{name} must exist on the test host"
        (tool_bin / name).symlink_to(real)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    return {**dict(_CLEAN_ENV), "PATH": str(tool_bin), "TMPDIR": str(scratch), "HOME": str(tmp_path)}


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK), "scripts/rtk-worktree-matrix.sh must be executable"


def test_help_documents_cleanup_contract(tmp_path):
    env = _env_with_tools(tmp_path, ["awk", "dirname"])
    result = _run(["--help"], env)
    assert result.returncode == 0, result.stderr
    assert "--keep" in result.stdout
    assert "Cleanup" in result.stdout


def test_unknown_argument_is_rejected_before_any_state(tmp_path):
    env = _env_with_tools(tmp_path, ["dirname"])
    result = _run(["--bogus"], env)
    assert result.returncode == 64
    assert list((tmp_path / "tmp").iterdir()) == []


_STUB_CLAUDE = """\
#!/bin/bash
# Registers a project dir keyed by the cwd, the way a real `claude -p` run does, plus the
# twin a `.claude/worktrees/probe` EnterWorktree session would register.
slug=$(pwd -P | tr -c 'A-Za-z0-9' '-')
mkdir -p "$HOME/.claude/projects/$slug" "$HOME/.claude/projects/${slug}--claude-worktrees-probe"
exit 0
"""


def _stubbed_env(tmp_path: Path) -> dict:
    env = _env_with_tools(
        tmp_path, ["dirname", "git", "python3", "mktemp", "cat", "rm", "sed", "grep", "tr", "mkdir"]
    )
    stub = tmp_path / "tool-bin" / "claude"
    stub.write_text(_STUB_CLAUDE)
    stub.chmod(0o755)
    home = tmp_path / "home"
    (home / ".claude" / "projects" / "-unrelated-project").mkdir(parents=True)
    return {**env, "HOME": str(home)}


def test_cleanup_removes_scratch_root_and_claude_project_dirs_it_caused(tmp_path):
    """The cleanup contract covers state a run leaves in the user's Claude config dir,
    not just the scratch root; unrelated project dirs must be left alone."""
    env = _stubbed_env(tmp_path)
    result = _run(["--configs", "c1"], env, timeout=60)
    assert result.returncode == 0, result.stderr
    assert list((tmp_path / "tmp").iterdir()) == [], "scratch root survived cleanup"
    projects = sorted(p.name for p in (tmp_path / "home" / ".claude" / "projects").iterdir())
    assert projects == ["-unrelated-project"], projects


def test_keep_preserves_root_and_prints_its_path(tmp_path):
    env = _stubbed_env(tmp_path)
    result = _run(["--configs", "c1", "--keep"], env, timeout=60)
    assert result.returncode == 0, result.stderr
    kept = [p for p in (tmp_path / "tmp").iterdir() if p.name.startswith("rtk-wt-matrix.")]
    assert len(kept) == 1
    assert str(kept[0]) in result.stdout
    projects = [p.name for p in (tmp_path / "home" / ".claude" / "projects").iterdir()]
    assert any("rtk-wt-matrix" in name for name in projects), "--keep must not touch project dirs"


def test_missing_claude_fails_fast_without_creating_scratch(tmp_path):
    env = _env_with_tools(tmp_path, ["dirname", "git", "python3"])
    result = _run([], env)
    assert result.returncode == 2
    assert "claude" in result.stderr
    assert list((tmp_path / "tmp").iterdir()) == [], "scratch root created before prerequisite check"
