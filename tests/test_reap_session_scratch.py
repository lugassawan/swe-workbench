"""Tests for bin/swe-workbench-reap-session-scratch — session scratchpad content removal.

Mirrors tests/test_reap_run_dir.py, with one structural difference: this script takes no
path argument. It derives its own target from $CLAUDE_CODE_SESSION_ID and a filesystem glob,
and any guard failure is a silent no-op (stderr note, always exit 0) rather than exit 1 —
a version-fragile harness path layout should degrade to "did nothing", never abort the
caller's cleanup flow. Every test therefore asserts exit 0 and inspects SWEPT_SESSION_FILES
on stdout plus filesystem side effects, never a non-zero exit code.

Tests operate against the real /tmp/claude-<uid>/ tree (mirrors test_reap_run_dir.py's use of
the real /tmp/swe-workbench-run/), scoped under a dedicated fake project slug and a session id
that can never collide with a live session, and always pass CLAUDE_CODE_SESSION_ID explicitly
so a test never touches this actual session's real scratchpad.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "bin" / "swe-workbench-reap-session-scratch"
REPO_ROOT = Path(__file__).parent.parent

UID_ROOT = Path(f"/tmp/claude-{os.getuid()}")
FAKE_PROJECT = "pytest-reap-session-scratch-fixture"
FAKE_SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def run_script(*, env_overrides=None):
    merged_env = dict(_CLEAN_ENV)
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:
                merged_env.pop(k, None)
            else:
                merged_env[k] = v
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
        env=merged_env,
    )


def swept_count(stdout: str) -> int:
    for line in stdout.splitlines():
        if line.startswith("SWEPT_SESSION_FILES="):
            return int(line.split("=", 1)[1])
    raise AssertionError(f"SWEPT_SESSION_FILES not found in stdout: {stdout!r}")


def make_scratchpad(session_id: str = FAKE_SESSION_ID, project: str = FAKE_PROJECT) -> Path:
    d = UID_ROOT / project / session_id / "scratchpad"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(autouse=True)
def _clean_fake_session_tree():
    # Per project_auto_reap_552_pr573's lesson: an idempotent-on-absent test must rm -rf its
    # own target first rather than inherit ambient state left by an earlier test's mkdir.
    shutil.rmtree(UID_ROOT / FAKE_PROJECT, ignore_errors=True)
    yield
    shutil.rmtree(UID_ROOT / FAKE_PROJECT, ignore_errors=True)


# ──────────────────────────────────────────────────────
# Script existence
# ──────────────────────────────────────────────────────

def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"


# ──────────────────────────────────────────────────────
# Resolution guards
# ──────────────────────────────────────────────────────

def test_missing_session_id_env_is_noop():
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": None})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 0


@pytest.mark.parametrize("bad_id", [
    "",
    "not-a-uuid",
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-extra",
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee",  # 35 chars, one short
    "gggggggg-bbbb-cccc-dddd-eeeeeeeeeeee",  # non-hex char
    "aaaaaaaa bbbb cccc dddd eeeeeeeeeeee",  # spaces instead of hyphens
])
def test_malformed_session_id_is_noop(bad_id):
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": bad_id})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 0


def test_zero_glob_hits_is_noop():
    """A well-formed session id with no matching scratchpad on disk is a no-op."""
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 0


def test_only_literal_scratchpad_dirname_matches():
    """A differently-named directory at the session-id level is never picked up."""
    d = UID_ROOT / FAKE_PROJECT / FAKE_SESSION_ID / "not-scratchpad"
    d.mkdir(parents=True)
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 0
    assert d.exists(), "unrelated directory must be untouched"


def test_multiple_glob_hits_is_noop():
    """Two projects both matching the same session id: ambiguous, so no-op — both untouched."""
    d1 = make_scratchpad(project=f"{FAKE_PROJECT}-a")
    d2 = make_scratchpad(project=f"{FAKE_PROJECT}-b")
    (d1 / "leftover.diff").write_text("x")
    (d2 / "leftover.diff").write_text("x")
    try:
        result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert swept_count(result.stdout) == 0
        assert (d1 / "leftover.diff").exists()
        assert (d2 / "leftover.diff").exists()
    finally:
        shutil.rmtree(UID_ROOT / f"{FAKE_PROJECT}-a", ignore_errors=True)
        shutil.rmtree(UID_ROOT / f"{FAKE_PROJECT}-b", ignore_errors=True)


# ──────────────────────────────────────────────────────
# Rejection — structural checks
# ──────────────────────────────────────────────────────

def test_refuses_symlinked_scratchpad():
    """A symlink at the exact scratchpad location is rejected, not followed."""
    session_dir = UID_ROOT / FAKE_PROJECT / FAKE_SESSION_ID
    session_dir.mkdir(parents=True)
    real_target = Path("/tmp") / "reap-session-scratch-symlink-target"
    real_target.mkdir(exist_ok=True)
    link = session_dir / "scratchpad"
    link.symlink_to(real_target)
    try:
        result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert swept_count(result.stdout) == 0
        assert link.is_symlink(), "symlink must NOT be removed when rejected"
        assert real_target.exists(), "symlink target must NOT be touched"
    finally:
        real_target.rmdir()


def test_refuses_scratchpad_escaping_via_symlinked_session_dir():
    """The session-id directory itself resolving (via symlink) outside of
    /tmp/claude-<uid>/ must be rejected — this is the 'grandparent's parent
    must be the uid root' guard, exercised via a path-escape attempt."""
    evil_root = Path("/tmp") / "reap-session-scratch-evil-root"
    evil_scratchpad = evil_root / "scratchpad"
    evil_scratchpad.mkdir(parents=True, exist_ok=True)
    (evil_scratchpad / "should-not-be-touched.txt").write_text("x")

    project_dir = UID_ROOT / FAKE_PROJECT
    project_dir.mkdir(parents=True, exist_ok=True)
    session_link = project_dir / FAKE_SESSION_ID
    session_link.symlink_to(evil_root)
    try:
        result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert swept_count(result.stdout) == 0
        assert (evil_scratchpad / "should-not-be-touched.txt").exists(), (
            "escaped target must NOT be touched"
        )
    finally:
        shutil.rmtree(evil_root, ignore_errors=True)


def test_refuses_scratchpad_escaping_via_symlinked_project_slug():
    """The project-slug directory (one level above the session-id dir) resolving
    via symlink outside /tmp/claude-<uid>/ must also be rejected — the guard must
    catch an escape at ANY path segment, not just the session-id level."""
    evil_root = Path("/tmp") / "reap-session-scratch-evil-root-slug"
    evil_scratchpad = evil_root / FAKE_SESSION_ID / "scratchpad"
    evil_scratchpad.mkdir(parents=True, exist_ok=True)
    (evil_scratchpad / "should-not-be-touched.txt").write_text("x")

    project_link = UID_ROOT / FAKE_PROJECT
    UID_ROOT.mkdir(parents=True, exist_ok=True)
    project_link.symlink_to(evil_root)
    try:
        result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert swept_count(result.stdout) == 0
        assert (evil_scratchpad / "should-not-be-touched.txt").exists(), (
            "escaped target must NOT be touched"
        )
    finally:
        project_link.unlink()
        shutil.rmtree(evil_root, ignore_errors=True)


def test_hidden_files_are_swept_as_top_level_entries():
    """dotglob is enabled for the sweep loop — a hidden file must be counted and
    removed alongside regular files, not silently left behind."""
    d = make_scratchpad()
    (d / "a.txt").write_text("x")
    (d / ".env").write_text("SECRET=x")
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 2, "hidden file must be counted alongside 'a.txt'"
    assert list(d.iterdir()) == [], "hidden file must actually be removed, not left behind"


def test_refuses_dir_containing_git():
    """A scratchpad directory containing a .git entry is refused — keeps scratch
    and worktree domains disjoint by construction."""
    d = make_scratchpad()
    (d / "leftover.diff").write_text("x")
    (d / ".git").mkdir()
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 0
    assert (d / "leftover.diff").exists(), "contents must NOT be removed when rejected"


def test_refuses_non_directory_target():
    """A regular file at the exact scratchpad path is rejected (not a directory)."""
    session_dir = UID_ROOT / FAKE_PROJECT / FAKE_SESSION_ID
    session_dir.mkdir(parents=True)
    f = session_dir / "scratchpad"
    f.write_text("not a directory")
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 0
    assert f.exists()


def test_refuses_dir_owned_by_another_uid():
    """A scratchpad owned by a different UID must be refused. Only runnable as root
    (need CAP_CHOWN to fabricate another owner), so skip otherwise with a marker."""
    if os.geteuid() != 0:
        pytest.skip("requires root to chown a directory to another UID")
    d = make_scratchpad()
    (d / "leftover.diff").write_text("x")
    try:
        os.chown(d, 1, 1)  # arbitrary non-current UID
        result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert swept_count(result.stdout) == 0
    finally:
        os.chown(d, os.getuid(), os.getgid())


# ──────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────

def test_happy_path_clears_contents_but_preserves_directory():
    d = make_scratchpad()
    (d / "existing_commit.diff").write_text("x")
    (d / "pr_body.md").write_text("x")
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 2
    assert d.exists(), "the scratchpad directory itself must survive"
    assert list(d.iterdir()) == [], "all contents must be removed"


def test_top_level_entry_count_not_recursive():
    """SWEPT_SESSION_FILES counts top-level entries, not files inside subdirectories."""
    d = make_scratchpad()
    (d / "a.txt").write_text("x")
    sub = d / "subdir"
    sub.mkdir()
    for i in range(5):
        (sub / f"nested-{i}.txt").write_text("x")
    result = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert swept_count(result.stdout) == 2, "must count 'a.txt' + 'subdir' as 2, not 6"
    assert list(d.iterdir()) == []


def test_idempotent_rerun_reports_zero():
    d = make_scratchpad()
    (d / "leftover.diff").write_text("x")
    first = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert first.returncode == 0
    assert swept_count(first.stdout) == 1

    second = run_script(env_overrides={"CLAUDE_CODE_SESSION_ID": FAKE_SESSION_ID})
    assert second.returncode == 0, f"stderr: {second.stderr!r}"
    assert swept_count(second.stdout) == 0
    assert d.exists(), "directory must still exist after a clean re-run"
