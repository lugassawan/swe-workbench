"""Tests for preflight-guard.sh — branch-sync preflight state detection.

The script only reports state (CURRENT_BRANCH, DEFAULT_BRANCH, IS_DEFAULT,
DETACHED, DIRTY); refusal on default branch / detached HEAD is the calling
skill's responsibility. DEFAULT_BRANCH must never be hardcoded to "main".
"""

import subprocess
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-branch-sync"
    / "scripts"
    / "preflight-guard.sh"
)

# gh is not authenticated/relevant to a throwaway local repo — force the
# symbolic-ref/echo-main fallback path deterministically and avoid any
# network dependency in the test.
_NO_GH_ENV = {**_CLEAN_ENV, "PATH": "/usr/bin:/bin"}


def _run(*args, cwd, env=None):
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=env or _CLEAN_ENV
    )


def _build_repo(base: Path, default_branch: str = "main") -> Path:
    repo = base / "repo"
    _run("git", "init", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    (repo / "README.md").write_text("hello\n")
    _run("git", "add", "README.md", cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "branch", "-M", default_branch, cwd=repo)
    return repo


def _run_script(repo: Path):
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=str(repo), capture_output=True, text=True, env=_NO_GH_ENV
    )


def _parse(stdout: str) -> dict:
    return dict(line.split("=", 1) for line in stdout.strip().splitlines())


class TestPreflightGuardCleanFeatureBranch:
    def test_reports_current_and_default_branch(self, tmp_path):
        repo = _build_repo(tmp_path)
        _run("git", "checkout", "-b", "feature/x", cwd=repo)

        result = _run_script(repo)

        assert result.returncode == 0, result.stderr
        fields = _parse(result.stdout)
        assert fields["CURRENT_BRANCH"] == "feature/x"
        assert fields["DEFAULT_BRANCH"] == "main"
        assert fields["IS_DEFAULT"] == "0"
        assert fields["DETACHED"] == "0"
        assert fields["DIRTY"] == "0"


class TestPreflightGuardDefaultBranch:
    def test_flags_is_default_when_on_default_branch(self, tmp_path):
        repo = _build_repo(tmp_path)

        result = _run_script(repo)

        fields = _parse(result.stdout)
        assert fields["CURRENT_BRANCH"] == "main"
        assert fields["IS_DEFAULT"] == "1"


class TestPreflightGuardDetachedHead:
    def test_flags_detached_head(self, tmp_path):
        repo = _build_repo(tmp_path)
        sha = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        _run("git", "checkout", sha, cwd=repo)

        result = _run_script(repo)

        fields = _parse(result.stdout)
        assert fields["DETACHED"] == "1"
        assert fields["IS_DEFAULT"] == "0"


class TestPreflightGuardDirty:
    def test_reports_dirty_count(self, tmp_path):
        repo = _build_repo(tmp_path)
        _run("git", "checkout", "-b", "feature/x", cwd=repo)
        (repo / "a.txt").write_text("new\n")
        (repo / "b.txt").write_text("new\n")

        result = _run_script(repo)

        fields = _parse(result.stdout)
        assert fields["DIRTY"] == "2"


class TestPreflightGuardDefaultBranchNotHardcoded:
    """DEFAULT_BRANCH must resolve from origin/HEAD, not a literal 'main'."""

    def test_resolves_non_main_default_branch_from_origin_head(self, tmp_path):
        origin = tmp_path / "origin.git"
        _run("git", "init", "--bare", str(origin), cwd=tmp_path)

        repo = _build_repo(tmp_path, default_branch="trunk")
        _run("git", "remote", "add", "origin", str(origin), cwd=repo)
        _run("git", "push", "-u", "origin", "trunk", cwd=repo)
        _run("git", "remote", "set-head", "origin", "trunk", cwd=repo)
        _run("git", "checkout", "-b", "feature/x", cwd=repo)

        result = _run_script(repo)

        fields = _parse(result.stdout)
        assert fields["DEFAULT_BRANCH"] == "trunk"
        assert fields["IS_DEFAULT"] == "0"


class TestPreflightGuardNotAGitRepo:
    def test_exits_nonzero_outside_git_repo(self, tmp_path):
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=str(not_a_repo), capture_output=True, text=True, env=_NO_GH_ENV
        )

        assert result.returncode != 0
        assert "git work tree" in result.stderr
