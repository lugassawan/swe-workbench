"""Tests for scripts/clean-ephemeral.sh — self-validating ephemeral worktree removal.

Each test invokes scripts/clean-ephemeral.sh directly as a subprocess, mirroring
the pattern used in test_hooks.py for bash_guard.sh.

Exit code 0  + path removed   → allowed removal (registered ephemeral worktree)
Exit code 1  + path untouched → rejected (not a sanctioned ephemeral path)
"""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "scripts" / "clean-ephemeral.sh"
REPO_ROOT = Path(__file__).parent.parent


def run_script(path: str, *, cwd=None, env=None):
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), path],
        capture_output=True, text=True,
        cwd=str(cwd or REPO_ROOT),
        env=merged_env,
    )


# ──────────────────────────────────────────────────────
# Fixture: real git repo with a linked ephemeral worktree
# ──────────────────────────────────────────────────────

@pytest.fixture()
def git_repo_with_worktree(tmp_path):
    """Create a bare-minimum git repo and add an ephemeral linked worktree."""
    repo = tmp_path / "main-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    wt_path = tmp_path / "pr-review-1282"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(wt_path), "HEAD"],
        check=True, capture_output=True,
    )
    return repo, wt_path


# ──────────────────────────────────────────────────────
# Happy path — registered ephemeral worktree is removed
# ──────────────────────────────────────────────────────

def test_removes_registered_worktree(git_repo_with_worktree):
    """A path registered as a git worktree with an ephemeral basename is removed (exit 0)."""
    repo, wt_path = git_repo_with_worktree
    assert wt_path.exists(), "worktree must exist before the script runs"
    result = run_script(str(wt_path), cwd=repo)
    assert result.returncode == 0, (
        f"Expected exit 0 for registered worktree {wt_path}\n"
        f"stderr: {result.stderr!r}\nstdout: {result.stdout!r}"
    )
    assert not wt_path.exists(), "worktree directory must be removed after exit 0"


@pytest.mark.parametrize("suffix", [
    "pr-review-1282",
    "pr-followup-999",       # workflow-pr-review-followup rimba task label
    "address-feedback-42",
    "pr-review-abc.def-1",
])
def test_removes_various_ephemeral_names(tmp_path, suffix):
    """All three ephemeral prefix patterns are accepted when the path is a registered worktree."""
    repo = tmp_path / "main-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    wt_path = tmp_path / suffix
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(wt_path), "HEAD"],
        check=True, capture_output=True,
    )
    result = run_script(str(wt_path), cwd=repo)
    assert result.returncode == 0, (
        f"Expected exit 0 for {suffix!r}\nstderr: {result.stderr!r}"
    )
    assert not wt_path.exists()


# ──────────────────────────────────────────────────────
# Rejection — non-ephemeral home path
# ──────────────────────────────────────────────────────

def test_refuses_non_ephemeral_home_path(tmp_path):
    """A path under $HOME that is NOT a registered git worktree and lacks an ephemeral basename is rejected."""
    fake_home_dir = tmp_path / "Documents"
    fake_home_dir.mkdir()
    result = run_script(str(fake_home_dir))
    assert result.returncode != 0, (
        f"Expected non-zero exit for non-ephemeral path {fake_home_dir}\n"
        f"stderr: {result.stderr!r}"
    )
    assert fake_home_dir.exists(), "directory must NOT be deleted when rejected"


def test_refuses_non_ephemeral_basename_even_if_worktree(git_repo_with_worktree, tmp_path):
    """A dir whose basename doesn't match ephemeral prefixes is rejected even if it is a registered worktree."""
    repo, _ = git_repo_with_worktree
    # Create a second worktree with a non-ephemeral name
    other_wt = tmp_path / "feature-my-branch"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(other_wt), "HEAD"],
        capture_output=True,  # may fail if HEAD is already checked out; that's fine
    )
    # Even if it didn't become a worktree, test the name-rejection path
    other_wt.mkdir(exist_ok=True)
    result = run_script(str(other_wt), cwd=repo)
    assert result.returncode != 0, (
        f"Expected non-zero for non-ephemeral basename 'feature-my-branch'\n"
        f"stderr: {result.stderr!r}"
    )


# ──────────────────────────────────────────────────────
# Rejection — root and bare home
# ──────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_path", [
    "/",
    "",
    os.environ.get("HOME", "/Users/testuser"),
])
def test_refuses_root_and_bare_home(bad_path):
    """Root, empty string, and bare $HOME are rejected (not deep enough / too dangerous)."""
    result = run_script(bad_path)
    assert result.returncode != 0, (
        f"Expected non-zero for dangerous path {bad_path!r}\n"
        f"stderr: {result.stderr!r}"
    )


def test_refuses_path_with_dotdot():
    """Paths containing .. segments are rejected (traversal prevention)."""
    result = run_script("/tmp/swe-workbench-pr-review/../../../etc")
    assert result.returncode != 0, (
        "Expected non-zero for path with .. traversal\n"
        f"stderr: {result.stderr!r}"
    )


def test_refuses_relative_path():
    """Relative paths (not starting with /) are rejected."""
    result = run_script("pr-review-1234")
    assert result.returncode != 0, (
        "Expected non-zero for relative path 'pr-review-1234'\n"
        f"stderr: {result.stderr!r}"
    )


# ──────────────────────────────────────────────────────
# Rejection — unregistered dir with wrong name
# ──────────────────────────────────────────────────────

def test_refuses_unregistered_dir_with_wrong_name(tmp_path):
    """A directory that exists but has a non-ephemeral basename (and is not a git worktree) is rejected."""
    bad_dir = tmp_path / "my-project"
    bad_dir.mkdir()
    result = run_script(str(bad_dir))
    assert result.returncode != 0, (
        f"Expected non-zero for {bad_dir}\nstderr: {result.stderr!r}"
    )
    assert bad_dir.exists(), "directory must NOT be deleted when rejected"


def test_refuses_unregistered_ephemeral_name(tmp_path):
    """An ephemeral-named dir that exists but is NOT a registered git worktree is also rejected."""
    # Correct basename but not registered in any git repo
    wt_dir = tmp_path / "pr-review-9999"
    wt_dir.mkdir()
    result = run_script(str(wt_dir))
    assert result.returncode != 0, (
        f"Expected non-zero for ephemeral-named-but-unregistered {wt_dir}\n"
        f"stderr: {result.stderr!r}"
    )
    assert wt_dir.exists(), "directory must NOT be deleted when rejected"


def test_refuses_submodule_style_git_file(tmp_path):
    """A .git file pointing to .git/modules/... (submodule style) must NOT be accepted as a worktree."""
    fake_wt = tmp_path / "pr-review-sub"
    fake_wt.mkdir()
    # Submodule .git file: gitdir points to <parent>/.git/modules/sub, NOT .git/worktrees/
    (fake_wt / ".git").write_text("gitdir: /some/repo/.git/modules/pr-review-sub\n")
    result = run_script(str(fake_wt))
    assert result.returncode != 0, (
        f"Expected rejection for submodule-style .git file\nstderr: {result.stderr!r}"
    )
    assert fake_wt.exists(), "directory must NOT be deleted when rejected"


# ──────────────────────────────────────────────────────
# Idempotency — already-removed path exits cleanly
# ──────────────────────────────────────────────────────

def test_script_exists_and_is_executable():
    """scripts/clean-ephemeral.sh must exist and be executable."""
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
