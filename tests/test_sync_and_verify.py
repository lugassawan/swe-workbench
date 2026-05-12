"""Regression test for sync-and-verify.sh stdout contract (issue #197).

The script declares: Stdout contract: WORKTREE_GONE=0|1.
It is invoked via ``eval "$(...)"`` so any byte on stdout that isn't that
exact assignment becomes a shell command in the caller's environment.

Block B (git pull --ff-only) leaked "Already up to date." to stdout.
Block C (git rev-parse --verify) leaked the resolved SHA to stdout.
Both were eval'd by the caller, causing "command not found" errors.

This test pins the contract: stdout must be exactly one line.
"""

import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-cleanup-merged"
    / "scripts"
    / "sync-and-verify.sh"
)
BRANCH = "feature/197-fixture-branch"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
NOISE_STRINGS = [
    "Switched to branch",
    "Already on",
    "Already up to date",
    "Fast-forward",
    "Updating",
]


def _build_repo(base: Path, default_branch: str = "main") -> Path:
    """Create a minimal git environment: bare origin + working main_repo.

    default_branch controls the name of the default branch so tests can verify
    Treatment D works on repos whose default branch is not 'main'.
    """
    origin = base / "origin.git"
    repo = base / "main_repo"

    # Strip inherited GIT_* env vars so fixture git operations use the tmp repo,
    # not a parent worktree whose GIT_DIR may be set by a calling git hook.
    import os as _os
    _clean_env = {k: v for k, v in _os.environ.items() if not k.startswith("GIT_")}
    _clean_env["GIT_CONFIG_NOSYSTEM"] = "1"

    def run(*args, cwd=None):
        return subprocess.run(
            list(args),
            cwd=str(cwd or base),
            check=True,
            capture_output=True,
            text=True,
            env=_clean_env,
        )

    run("git", "init", "--bare", str(origin))
    run("git", "init", str(repo))
    run("git", "config", "user.email", "test@example.com", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    # Prevent the global core.hooksPath (set to swe-workbench hooks) from
    # running the commit-msg hook inside test fixture repos.  The fixture
    # tests sync-and-verify.sh, not commit formatting.
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    (repo / "README.md").write_text("hello\n")
    run("git", "add", "README.md", cwd=repo)
    run("git", "commit", "-m", "init", cwd=repo)
    run("git", "branch", "-M", default_branch, cwd=repo)
    run("git", "remote", "add", "origin", str(origin), cwd=repo)
    run("git", "push", "-u", "origin", default_branch, cwd=repo)

    run("git", "checkout", "-b", BRANCH, cwd=repo)
    (repo / "feature.txt").write_text("feature\n")
    run("git", "add", "feature.txt", cwd=repo)
    run("git", "commit", "-m", "add feature", cwd=repo)
    run("git", "push", "-u", "origin", BRANCH, cwd=repo)
    run("git", "checkout", default_branch, cwd=repo)

    return repo


@pytest.fixture
def git_repo(tmp_path):
    return _build_repo(tmp_path, default_branch="main")


@pytest.fixture
def git_repo_trunk(tmp_path):
    """Repo whose default branch is 'trunk', not 'main' (Treatment D coverage)."""
    return _build_repo(tmp_path, default_branch="trunk")


def _run_script(repo: Path, head_ref: str, default_branch: str = "main"):
    # Clear git environment variables so the script operates on the fixture
    # repo, not on a parent worktree whose GIT_DIR may be inherited when tests
    # run inside a git hook (e.g. pre-push).  Without this, sync-and-verify.sh
    # would derive MAIN_REPO from the parent worktree and git checkout would
    # switch the parent worktree's branch as a side-effect.
    env = {k: v for k, v in __import__("os").environ.items()
           if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return subprocess.run(
        ["bash", str(SCRIPT), head_ref, default_branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_contract(result, expected: str) -> None:
    assert result.returncode == 0, (
        f"Script exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    lines = result.stdout.strip().splitlines()
    assert lines == [f"WORKTREE_GONE={expected}"], (
        f"Expected stdout=['WORKTREE_GONE={expected}'], got {lines!r}\n"
        f"Full stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not SHA_PATTERN.search(result.stdout), (
        f"stdout must not contain a 40-hex SHA: {result.stdout!r}"
    )
    for noise in NOISE_STRINGS:
        assert noise not in result.stdout, (
            f"stdout must not contain {noise!r}: {result.stdout!r}"
        )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("branch_present", "0"),
        ("branch_absent", "1"),
    ],
)
class TestSyncAndVerifyStdoutContract:
    """Pin the stdout contract: exactly one line, WORKTREE_GONE=0|1, no git noise."""

    def test_stdout_is_exact_contract(self, git_repo, case, expected):
        if case == "branch_absent":
            subprocess.run(
                ["git", "branch", "-D", BRANCH],
                cwd=str(git_repo),
                check=True,
                capture_output=True,
                text=True,
            )

        result = _run_script(git_repo, BRANCH, default_branch="main")
        _assert_contract(result, expected)


class TestSyncAndVerifyNonMainDefaultBranch:
    """Treatment D: script must work when the default branch is not 'main'."""

    def test_branch_present_trunk_default(self, git_repo_trunk):
        result = _run_script(git_repo_trunk, BRANCH, default_branch="trunk")
        _assert_contract(result, "0")

    def test_branch_absent_trunk_default(self, git_repo_trunk):
        subprocess.run(
            ["git", "branch", "-D", BRANCH],
            cwd=str(git_repo_trunk),
            check=True,
            capture_output=True,
            text=True,
        )
        result = _run_script(git_repo_trunk, BRANCH, default_branch="trunk")
        _assert_contract(result, "1")
