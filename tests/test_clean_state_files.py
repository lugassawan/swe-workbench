"""Tests for scripts/clean-state-files.sh — file-only state cleanup helper.

Mirrors tests/test_clean_ephemeral.py.  Each test invokes the script as a
subprocess.  Exit code 0 + file removed → allowed deletion.  Exit code 1 +
file untouched → rejected path.
"""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "scripts" / "clean-state-files.sh"
ROOT = Path(__file__).parent.parent
TMP = Path("/tmp")


def run_script(*paths: str, env=None):
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)] + list(paths),
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=merged_env,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _tmp_pr_review_dir() -> Path:
    d = TMP / "swe-workbench-pr-review"
    d.mkdir(exist_ok=True)
    return d


def _tmp_addr_feedback_dir() -> Path:
    d = TMP / "swe-workbench-address-feedback"
    d.mkdir(exist_ok=True)
    return d


# ── script existence ──────────────────────────────────────────────────────────

def test_script_exists_and_is_executable():
    """scripts/clean-state-files.sh must exist and be executable."""
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"


# ── happy path: pr-review state files ────────────────────────────────────────

def test_accepts_pr_review_json(tmp_path):
    """A file under /tmp/swe-workbench-pr-review/ is accepted and deleted (exit 0)."""
    d = _tmp_pr_review_dir()
    f = d / f"test-clean-state-{tmp_path.name}.json"
    f.write_text("{}")
    try:
        result = run_script(str(f))
        assert result.returncode == 0, (
            f"Expected exit 0 for valid state file {f}\n"
            f"stderr: {result.stderr!r}"
        )
        assert not f.exists(), "file must be removed after exit 0"
    finally:
        f.unlink(missing_ok=True)


def test_accepts_pr_review_threads_json(tmp_path):
    """A -threads.json file under /tmp/swe-workbench-pr-review/ is accepted."""
    d = _tmp_pr_review_dir()
    f = d / f"test-clean-state-{tmp_path.name}-threads.json"
    f.write_text("{}")
    try:
        result = run_script(str(f))
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert not f.exists()
    finally:
        f.unlink(missing_ok=True)


def test_accepts_two_pr_review_files(tmp_path):
    """Passing two files in the same sanctioned directory deletes both (exit 0)."""
    d = _tmp_pr_review_dir()
    f1 = d / f"test-multi-{tmp_path.name}.json"
    f2 = d / f"test-multi-{tmp_path.name}-threads.json"
    f1.write_text("{}")
    f2.write_text("{}")
    try:
        result = run_script(str(f1), str(f2))
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert not f1.exists() and not f2.exists()
    finally:
        f1.unlink(missing_ok=True)
        f2.unlink(missing_ok=True)


# ── happy path: single-file-writer patterns ───────────────────────────────────

@pytest.mark.parametrize("prefix,ext", [
    ("capture", "md"),
    ("capture", "cmd"),
    ("report-issue", "md"),
    ("report-issue", "cmd"),
    ("audit-emit", "md"),
    ("audit-emit", "cmd"),
    ("extend", "md"),
])
def test_accepts_single_file_writer_patterns(prefix, ext, tmp_path):
    """All four single-file-writer basename patterns under /tmp are accepted."""
    f = TMP / f"{prefix}-{tmp_path.name}.{ext}"
    f.write_text("test")
    try:
        result = run_script(str(f))
        assert result.returncode == 0, (
            f"Expected exit 0 for {prefix!r} pattern ({ext})\n"
            f"stderr: {result.stderr!r}"
        )
        assert not f.exists(), f"{f} must be removed"
    finally:
        f.unlink(missing_ok=True)


# ── happy path: idempotent on missing file ────────────────────────────────────

def test_idempotent_on_missing_pr_review_file():
    """A valid path that does not exist exits 0 (rm -f is idempotent)."""
    f = "/tmp/swe-workbench-pr-review/nonexistent-clean-state-test.json"
    result = run_script(f)
    assert result.returncode == 0, (
        f"Expected exit 0 for missing-but-valid path {f!r}\n"
        f"stderr: {result.stderr!r}"
    )


def test_idempotent_on_missing_capture_file():
    """A valid capture- path that does not exist exits 0."""
    f = "/tmp/capture-nonexistent-clean-state-test-99999.md"
    result = run_script(f)
    assert result.returncode == 0, (
        f"Expected exit 0 for missing-but-valid path {f!r}\n"
        f"stderr: {result.stderr!r}"
    )


# ── rejection: directory ──────────────────────────────────────────────────────

def test_rejects_directory(tmp_path):
    """A directory — even under a sanctioned location — is rejected (exit 1)."""
    d = _tmp_pr_review_dir()
    subdir = d / f"test-dir-{tmp_path.name}"
    subdir.mkdir(exist_ok=True)
    try:
        result = run_script(str(subdir))
        assert result.returncode != 0, (
            f"Expected non-zero for directory {subdir}\n"
            f"stderr: {result.stderr!r}"
        )
        assert subdir.exists(), "directory must NOT be deleted when rejected"
    finally:
        subdir.rmdir()


def test_rejects_capture_directory(tmp_path):
    """A directory with a capture- prefix directly in /tmp is rejected."""
    subdir = TMP / f"capture-test-dir-{tmp_path.name}"
    subdir.mkdir(exist_ok=True)
    try:
        result = run_script(str(subdir))
        assert result.returncode != 0, (
            f"Expected non-zero for directory {subdir}\n"
            f"stderr: {result.stderr!r}"
        )
        assert subdir.exists(), "directory must NOT be deleted when rejected"
    finally:
        subdir.rmdir()


# ── rejection: path traversal ────────────────────────────────────────────────

def test_rejects_dotdot_traversal():
    """Paths with .. segments are rejected."""
    result = run_script("/tmp/swe-workbench-pr-review/../../../etc/passwd")
    assert result.returncode != 0, (
        "Expected non-zero for path with .. traversal\n"
        f"stderr: {result.stderr!r}"
    )


def test_rejects_dotdot_in_capture_path():
    """.. in a capture- prefixed path is rejected."""
    result = run_script("/tmp/capture-repo-123/../../../etc/shadow")
    assert result.returncode != 0, (
        "Expected non-zero for path with .. traversal\n"
        f"stderr: {result.stderr!r}"
    )


# ── rejection: unsanctioned locations ────────────────────────────────────────

def test_rejects_relative_path():
    """Relative paths (not starting with /) are rejected."""
    result = run_script("capture-repo-123.md")
    assert result.returncode != 0, (
        "Expected non-zero for relative path\n"
        f"stderr: {result.stderr!r}"
    )


@pytest.mark.parametrize("bad_path", [
    "/",
    "",
    os.environ.get("HOME", "/Users/testuser") + "/secrets.json",
    "/usr/local/bin/env",
    "/tmp/evil.json",
])
def test_rejects_unsanctioned_paths(bad_path):
    """Root, empty, $HOME paths, and /tmp/<no-prefix> are rejected."""
    result = run_script(bad_path)
    assert result.returncode != 0, (
        f"Expected non-zero for unsanctioned path {bad_path!r}\n"
        f"stderr: {result.stderr!r}"
    )


def test_rejects_tmp_subdir_wrong_prefix(tmp_path):
    """A file in /tmp/ whose basename does not match any prefix pattern is rejected."""
    f = TMP / f"wrongprefix-{tmp_path.name}.json"
    f.write_text("{}")
    try:
        result = run_script(str(f))
        assert result.returncode != 0, (
            f"Expected non-zero for wrong-prefix {f}\n"
            f"stderr: {result.stderr!r}"
        )
        assert f.exists(), "file must NOT be deleted when rejected"
    finally:
        f.unlink(missing_ok=True)


def test_rejects_no_args():
    """Calling the script with no arguments exits 1."""
    result = run_script()
    assert result.returncode != 0, "Expected non-zero for zero arguments"


# ── rejection: one invalid arg prevents all deletions ────────────────────────

def test_one_bad_arg_prevents_all_deletions(tmp_path):
    """If one arg fails validation, no files are deleted."""
    d = _tmp_pr_review_dir()
    good = d / f"test-guard-{tmp_path.name}.json"
    good.write_text("{}")
    bad = "/tmp/evil.json"
    try:
        result = run_script(str(good), bad)
        assert result.returncode != 0, (
            f"Expected non-zero when one arg is invalid\n"
            f"stderr: {result.stderr!r}"
        )
        assert good.exists(), "valid file must NOT be deleted when another arg is invalid"
    finally:
        good.unlink(missing_ok=True)
