"""Tests for hooks/bash_guard.sh — end-to-end guard invocation (issue #233).

Each test class invokes hooks/bash_guard.sh directly with a JSON payload on
stdin, mirroring exactly how Claude Code calls the PreToolUse:Bash hook.
Exit code 2 + "BLOCKED" in stderr → command was blocked.
Exit code 0, empty stderr              → command was allowed.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).parent.parent / "hooks" / "bash_guard.sh"

# When tests run inside a git pre-push hook, GIT_DIR points to the hook's repo.
# Strip GIT_* so subprocess git calls use normal cwd-based repo detection.
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture(scope="module")
def guard_script():
    assert GUARD.exists(), f"missing {GUARD}"
    assert os.access(GUARD, os.X_OK), f"{GUARD} must be executable"
    return GUARD


def run_guard(script, cmd, *, cwd=None, env=None):
    payload = json.dumps({"tool_input": {"command": cmd}})
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        [str(script)],
        input=payload, text=True, capture_output=True,
        cwd=cwd, env=merged_env,
    )


# ──────────────────────────────────────────────
# rm -rf against root or home
# ──────────────────────────────────────────────

class TestRmRfBlocker:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        'rm -rf "$HOME"',
        "sudo rm -rf /",
        "rm -rf /Users/foo",
        "rm -rf /Users/foo/Documents",
        "rm -rf /Users/foo/a/b/c",
        "rm -rf /home/foo",
        "rm -rf /home/foo/.config",
        "rm -rf $HOME/Documents",
        "rm -rf ~/.config",
        "rm -rf /Users",
        "rm -rf /home",
        'rm -rf "/Users/foo"',
        "rm -rf '/home/foo'",
        "rm -Rf /Users/foo",
        "rm -RF /Users/foo",
    ])
    def test_blocked(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2, (
            f"Expected exit 2 (BLOCKED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr, (
            f"Expected 'BLOCKED' in stderr for {cmd!r}\nstderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("cmd", [
        "rm -rf ./build",
        "rm -rf node_modules",
        "rm -rf /tmp/foo",
        "rm -rf /var/log",
        "rm -f somefile",
        "rm -r ./dist",
        "rm -rf /UsersHome",
        "rm -rf /homestead",
    ])
    def test_allowed(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 0, (
            f"Expected exit 0 (ALLOWED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"Expected empty stderr for {cmd!r}\nstderr: {result.stderr!r}"
        )


# ──────────────────────────────────────────────
# force-push to main/master
# ──────────────────────────────────────────────

class TestForcePushBlocker:
    @pytest.mark.parametrize("cmd", [
        "git push --force origin main",
        "git push -f origin master",
        "git push --force origin main:main",
        "git push --force origin master:master",
        "git push --force origin HEAD:main",
        "git push --force origin feature:main",
        "git push --force origin HEAD:master",
        "git push origin main --force",
    ])
    def test_blocked(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2, (
            f"Expected exit 2 (BLOCKED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push origin main",
        "git push --force origin feature/x",
        "git push --force origin mainline",
        "git push --force origin my-master",
        "git push --force-with-lease origin main",
        "git push --force-with-lease origin master",
        "git push --force-if-includes origin main",
        "git push --force-with-lease=origin/main origin main",
    ])
    def test_allowed(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 0, (
            f"Expected exit 0 (ALLOWED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )


# ──────────────────────────────────────────────
# hard reset — branch-aware (requires temp git repo)
# ──────────────────────────────────────────────

@pytest.fixture
def repo_on(tmp_path):
    """Factory for temp git repos on a given branch."""
    def _make(branch: str) -> Path:
        # Use a named subdirectory so stale .git dirs from previous pytest
        # sessions never cause re-init or branch contamination.
        repo_dir = tmp_path / "repo"
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.mkdir()
        subprocess.run(["git", "init", "-q", "-b", branch], cwd=repo_dir,
                       env=_CLEAN_ENV, check=True)
        (repo_dir / "README").write_text("init")
        subprocess.run(["git", "add", "."], cwd=repo_dir, env=_CLEAN_ENV, check=True)
        # Disable hooks so the host repo's commit-msg hook (which enforces
        # [type] format) does not reject the plain "init" fixture message.
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null",
             "-c", "user.email=t@t.com", "-c", "user.name=T",
             "commit", "-qm", "init"],
            cwd=repo_dir, env=_CLEAN_ENV, check=True,
        )
        return repo_dir
    return _make


class TestHardResetBlocker:
    @pytest.mark.parametrize("branch", ["main", "master", "release/2025-01"])
    def test_blocked_on_protected_branch(self, guard_script, repo_on, branch):
        repo = repo_on(branch)
        result = run_guard(guard_script, "git reset --hard HEAD~1", cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED on branch {branch!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_allowed_on_feature_branch(self, guard_script, repo_on):
        repo = repo_on("feature/x")
        result = run_guard(guard_script, "git reset --hard HEAD~1", cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED on feature/x, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

    def test_soft_reset_always_allowed(self, guard_script, repo_on):
        repo = repo_on("main")
        result = run_guard(guard_script, "git reset --soft HEAD~1", cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED for --soft on main, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )


# ──────────────────────────────────────────────
# short-circuit: non-rm/non-git commands skip grep
# ──────────────────────────────────────────────

class TestShortCircuit:
    def _run_with_shims(self, script, cmd, tmp_path):
        trace = tmp_path / "trace"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        real_jq = shutil.which("jq")
        real_grep = shutil.which("grep")
        for tool, real in [("jq", real_jq), ("grep", real_grep)]:
            shim = bin_dir / tool
            shim.write_text(
                f'#!/bin/sh\necho "{tool}" >> "{trace}"\nexec "{real}" "$@"\n'
            )
            shim.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        run_guard(script, cmd, env=env)
        return trace.read_text() if trace.exists() else ""

    @pytest.mark.parametrize("cmd", ["ls .", "cat foo.txt", "echo hello", "make build"])
    def test_no_grep_for_safe_commands(self, guard_script, cmd, tmp_path):
        trace = self._run_with_shims(guard_script, cmd, tmp_path)
        assert "jq" in trace, f"Expected jq to run for {cmd!r}"
        assert "grep" not in trace, f"Expected grep to be skipped for {cmd!r}"

    @pytest.mark.parametrize("cmd", ["rm -rf /tmp/foo", "git status"])
    def test_grep_runs_for_rm_and_git(self, guard_script, cmd, tmp_path):
        trace = self._run_with_shims(guard_script, cmd, tmp_path)
        assert "jq" in trace, f"Expected jq to run for {cmd!r}"
        assert "grep" in trace, f"Expected grep to run for {cmd!r}"


# ──────────────────────────────────────────────
# pre-push hook — unchanged
# ──────────────────────────────────────────────

class TestPrePushHook:
    """Verify .githooks/pre-push contains the expected invocations."""

    PRE_PUSH = Path(__file__).parent.parent / ".githooks" / "pre-push"

    def test_pre_push_runs_validate(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "validate.sh" in content, "pre-push hook must invoke validate.sh"

    def test_pre_push_runs_pytest(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "pytest" in content and "tests/" in content, (
            "pre-push hook must invoke pytest against the tests/ directory"
        )
