"""Tests for scripts/clean-ephemeral.sh — self-validating ephemeral worktree removal.

Each test invokes scripts/clean-ephemeral.sh directly as a subprocess, mirroring
the pattern used in test_hooks.py for bash_guard.sh.

Exit code 0  + path removed   → allowed removal (registered ephemeral worktree)
Exit code 1  + path untouched → rejected (not a sanctioned ephemeral path)

Design note: tests that verify the happy path (registered git worktree) create the
exact file structure that git uses for linked worktrees — a .git FILE containing
'gitdir: .../.git/worktrees/<name>' — without running `git commit`. This avoids
GIT_DIR / GIT_WORK_TREE pollution from the hook environment that would otherwise
redirect temp-repo commits into the main swe-workbench branch.
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


def make_linked_worktree(base: Path, name: str) -> Path:
    """Create a minimal linked-worktree directory structure without running git.

    A real git linked worktree has:
      <wt>/.git  — a FILE containing: gitdir: <main>/.git/worktrees/<wt-name>

    We replicate that structure in pure Python so no git subprocess is needed
    and no commits are created in any repo (avoiding hook-environment pollution).
    """
    wt = base / name
    wt.mkdir(parents=True, exist_ok=True)
    # The worktrees metadata directory inside the (fake) main repo's .git.
    worktrees_meta = base / "fake-main-repo" / ".git" / "worktrees" / name
    worktrees_meta.mkdir(parents=True, exist_ok=True)
    (wt / ".git").write_text(f"gitdir: {worktrees_meta}\n")
    return wt


# ──────────────────────────────────────────────────────
# Happy path — registered ephemeral worktree is removed
# ──────────────────────────────────────────────────────

def test_removes_registered_worktree(tmp_path):
    """A path with a proper linked-worktree .git file and ephemeral basename is removed (exit 0)."""
    wt = make_linked_worktree(tmp_path, "pr-review-1282")
    assert wt.exists(), "worktree must exist before the script runs"
    result = run_script(str(wt))
    assert result.returncode == 0, (
        f"Expected exit 0 for registered worktree {wt}\n"
        f"stderr: {result.stderr!r}\nstdout: {result.stdout!r}"
    )
    assert not wt.exists(), "worktree directory must be removed after exit 0"


@pytest.mark.parametrize("name", [
    "pr-review-1282",
    "pr-followup-999",       # workflow-pr-review-followup rimba task label
    "address-feedback-42",
    "pr-review-abc.def-1",
])
def test_removes_various_ephemeral_names(tmp_path, name):
    """All three ephemeral prefix patterns are accepted when the .git file is present."""
    wt = make_linked_worktree(tmp_path, name)
    result = run_script(str(wt))
    assert result.returncode == 0, (
        f"Expected exit 0 for {name!r}\nstderr: {result.stderr!r}"
    )
    assert not wt.exists()


# ──────────────────────────────────────────────────────
# Rejection — non-ephemeral home path
# ──────────────────────────────────────────────────────

def test_refuses_non_ephemeral_home_path(tmp_path):
    """A plain directory without a .git file and non-ephemeral basename is rejected."""
    fake_home_dir = tmp_path / "Documents"
    fake_home_dir.mkdir()
    result = run_script(str(fake_home_dir))
    assert result.returncode != 0, (
        f"Expected non-zero exit for non-ephemeral path {fake_home_dir}\n"
        f"stderr: {result.stderr!r}"
    )
    assert fake_home_dir.exists(), "directory must NOT be deleted when rejected"


def test_refuses_non_ephemeral_basename_even_if_worktree(tmp_path):
    """A dir with a valid .git file but non-ephemeral basename is rejected."""
    wt = make_linked_worktree(tmp_path, "feature-my-branch")
    result = run_script(str(wt))
    assert result.returncode != 0, (
        f"Expected non-zero for non-ephemeral basename 'feature-my-branch'\n"
        f"stderr: {result.stderr!r}"
    )
    assert wt.exists(), "directory must NOT be deleted when rejected"


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
    """A plain directory with a non-ephemeral basename (no .git file) is rejected."""
    bad_dir = tmp_path / "my-project"
    bad_dir.mkdir()
    result = run_script(str(bad_dir))
    assert result.returncode != 0, (
        f"Expected non-zero for {bad_dir}\nstderr: {result.stderr!r}"
    )
    assert bad_dir.exists(), "directory must NOT be deleted when rejected"


def test_refuses_unregistered_ephemeral_name(tmp_path):
    """An ephemeral-named dir without a .git file is rejected (not a registered worktree)."""
    wt_dir = tmp_path / "pr-review-9999"
    wt_dir.mkdir()
    result = run_script(str(wt_dir))
    assert result.returncode != 0, (
        f"Expected non-zero for ephemeral-named-but-unregistered {wt_dir}\n"
        f"stderr: {result.stderr!r}"
    )
    assert wt_dir.exists(), "directory must NOT be deleted when rejected"


def test_refuses_submodule_style_git_file(tmp_path):
    """A .git file pointing to .git/modules/... (submodule style) must NOT be accepted."""
    fake_wt = tmp_path / "pr-review-sub"
    fake_wt.mkdir()
    (fake_wt / ".git").write_text("gitdir: /some/repo/.git/modules/pr-review-sub\n")
    result = run_script(str(fake_wt))
    assert result.returncode != 0, (
        f"Expected rejection for submodule-style .git file\nstderr: {result.stderr!r}"
    )
    assert fake_wt.exists(), "directory must NOT be deleted when rejected"


# ──────────────────────────────────────────────────────
# Script existence check
# ──────────────────────────────────────────────────────

def test_script_exists_and_is_executable():
    """scripts/clean-ephemeral.sh must exist and be executable."""
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
