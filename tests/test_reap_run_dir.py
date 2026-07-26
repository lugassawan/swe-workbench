"""Tests for runtime/reap-run-dir.sh — run-scoped scratch directory removal.

Mirrors tests/test_clean_ephemeral.py and tests/test_clean_state_files.py.
Each test invokes the script as a subprocess.

Exit code 0 + dir removed (or already absent) -> allowed removal.
Exit code 1 + dir untouched                   -> rejected path.
"""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "runtime" / "reap-run-dir.sh"
REPO_ROOT = Path(__file__).parent.parent

RUN_ROOT = Path("/tmp/swe-workbench-run")


def run_script(path: str, *, env=None):
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), path],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
        env=merged_env,
    )


def make_run_dir(name: str) -> Path:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    d = RUN_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ──────────────────────────────────────────────────────
# Script existence
# ──────────────────────────────────────────────────────

def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"


# ──────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────

def test_removes_well_formed_run_dir():
    """A well-formed run dir one level under the root is removed (exit 0)."""
    d = make_run_dir("pr-review-42-a1b2c3")
    result = run_script(str(d))
    assert result.returncode == 0, (
        f"Expected exit 0 for well-formed run dir {d}\n"
        f"stderr: {result.stderr!r}\nstdout: {result.stdout!r}"
    )
    assert not d.exists(), "run dir must be removed after exit 0"


@pytest.mark.parametrize("name", [
    "pr-review-42-a1b2c3",
    "pr-followup-999-zZ9kL0",
    "address-feedback-7-abcdef",
    "review-security-15-a1b2c3",
    "extend-3-a1b2c3",
    "capture-1-a1b2c3",
    "audit-emit-1-a1b2c3",
    "hotfix-100-a1b2c3",
])
def test_accepts_all_name_shapes(name):
    """All eight allowlisted flow prefixes are accepted."""
    d = make_run_dir(name)
    result = run_script(str(d))
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert not d.exists()


def test_absent_path_is_idempotent():
    """A well-formed but non-existent run dir path exits 0 (nothing to do)."""
    target = RUN_ROOT / "pr-review-999999-nonexi"
    assert not target.exists()
    result = run_script(str(target))
    assert result.returncode == 0, f"stderr: {result.stderr!r}"


# ──────────────────────────────────────────────────────
# Rejection — structural checks
# ──────────────────────────────────────────────────────

def test_refuses_root_itself():
    """The run-dir root itself must never be removable."""
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    result = run_script(str(RUN_ROOT))
    assert result.returncode != 0, f"stderr: {result.stderr!r}"
    assert RUN_ROOT.exists(), "root must NOT be removed"


def test_refuses_two_levels_deep():
    """A path two levels below the root is rejected (depth must be exactly one)."""
    d = make_run_dir("pr-review-42-a1b2c3")
    nested = d / "inner"
    nested.mkdir()
    try:
        result = run_script(str(nested))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert nested.exists(), "nested dir must NOT be removed when rejected"
    finally:
        nested.rmdir()
        d.rmdir()


def test_refuses_dotdot_traversal():
    result = run_script("/tmp/swe-workbench-run/../../../etc")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_refuses_relative_path():
    result = run_script("pr-review-42-a1b2c3")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_refuses_empty_path():
    result = run_script("")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_refuses_symlink():
    """A symlink at the exact run-dir location is rejected, not followed."""
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    real_target = Path("/tmp") / "reap-run-dir-symlink-target"
    real_target.mkdir(exist_ok=True)
    link = RUN_ROOT / "pr-review-42-a1b2c3"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(real_target)
    try:
        result = run_script(str(link))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert link.is_symlink(), "symlink must NOT be removed when rejected"
        assert real_target.exists(), "symlink target must NOT be removed"
    finally:
        link.unlink(missing_ok=True)
        real_target.rmdir()


def test_refuses_bad_name_shape():
    """A basename that does not match any allowlisted prefix/shape is rejected."""
    d = make_run_dir("not-a-known-prefix-42-a1b2c3")
    try:
        result = run_script(str(d))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert d.exists(), "dir must NOT be removed when rejected"
    finally:
        d.rmdir()


def test_refuses_name_missing_hash_suffix():
    """A name lacking the trailing 6-char mktemp suffix is rejected."""
    d = make_run_dir("pr-review-42")
    try:
        result = run_script(str(d))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert d.exists()
    finally:
        d.rmdir()


def test_refuses_dir_containing_git():
    """A run-dir-shaped directory containing a .git entry is refused — keeps
    scratch and worktree domains disjoint by construction."""
    d = make_run_dir("pr-review-42-a1b2c3")
    (d / ".git").mkdir()
    try:
        result = run_script(str(d))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert d.exists(), "dir must NOT be removed when rejected"
    finally:
        (d / ".git").rmdir()
        d.rmdir()


def test_refuses_non_directory():
    """A regular file at a well-formed run-dir path is rejected (not a directory)."""
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    f = RUN_ROOT / "pr-review-42-a1b2c3"
    f.write_text("not a directory")
    try:
        result = run_script(str(f))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert f.exists()
    finally:
        f.unlink()


# ──────────────────────────────────────────────────────
# Ownership — skip when not meaningfully testable
# ──────────────────────────────────────────────────────

def test_refuses_dir_owned_by_another_uid():
    """A dir owned by a different UID must be refused. Only runnable as root
    (need CAP_CHOWN to fabricate another owner), so skip otherwise with a marker."""
    if os.geteuid() != 0:
        pytest.skip("requires root to chown a directory to another UID")
    d = make_run_dir("pr-review-42-a1b2c3")
    try:
        os.chown(d, 1, 1)  # arbitrary non-current UID
        result = run_script(str(d))
        assert result.returncode != 0, f"stderr: {result.stderr!r}"
        assert d.exists()
    finally:
        os.chown(d, os.getuid(), os.getgid())
        d.rmdir()


# ──────────────────────────────────────────────────────
# Concurrency — two run dirs for the same PR are independent
# ──────────────────────────────────────────────────────

def test_reaping_one_run_dir_leaves_sibling_intact():
    """Two distinct mktemp-suffixed run dirs for the same PR number must not
    cross-reap — reaping is an exact-path delete, never a pattern match."""
    d1 = make_run_dir("pr-review-42-a1b2c3")
    d2 = make_run_dir("pr-review-42-d4e5f6")
    try:
        result = run_script(str(d1))
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert not d1.exists()
        assert d2.exists(), "sibling run dir for the same PR must survive"
    finally:
        d1.rmdir() if d1.exists() else None
        d2.rmdir() if d2.exists() else None
