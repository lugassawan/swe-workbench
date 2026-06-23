"""Behavioral tests for scripts/check-lockfile-additions.sh.

Each case builds a hermetic temp git repo (git init + initial commit of the
base lock), overwrites the working-tree lock to simulate a post-regen state,
then runs the script via subprocess and asserts the exit code and output.

The script reads HEAD:<lock> as the pre-regen baseline and compares top-level
sets (packages whose # via block references -r *.txt).
"""

import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
GUARD_SCRIPT = ROOT / "scripts" / "check-lockfile-additions.sh"

# Minimal pip-compile lock with one top-level package.
_BASE_LOCK = (
    "pytest==9.0.3\n"
    "    # via -r tests/requirements.txt\n"
)


def _make_git_repo(tmp_path: Path, lock_content: str) -> Path:
    """Scaffold a temp git repo with the given lock content committed to HEAD."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    lock_file = tests_dir / "requirements.lock"
    lock_file.write_text(lock_content)

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True, env=_CLEAN_ENV)
    subprocess.run(["git", "add", "tests/requirements.lock"], cwd=tmp_path,
                   check=True, capture_output=True, env=_CLEAN_ENV)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True,
                   capture_output=True, env=_CLEAN_ENV)
    return lock_file


class TestLockfileAdditionsGuard:
    def test_no_args_exits_one(self, tmp_path):
        """No lockfile args → usage error → exit 1."""
        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 1
        assert "Usage" in result.stderr

    def test_version_bump_exits_zero(self, tmp_path):
        """Bumping a top-level package version is not an addition → exit 0."""
        lock_file = _make_git_repo(tmp_path, _BASE_LOCK)
        lock_file.write_text("pytest==9.1.0\n    # via -r tests/requirements.txt\n")

        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT), "tests/requirements.lock"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0, result.stderr

    def test_new_top_level_package_exits_one(self, tmp_path):
        """Adding a new # via -r package is a new top-level dep → exit 1 naming it."""
        lock_file = _make_git_repo(tmp_path, _BASE_LOCK)
        lock_file.write_text(
            _BASE_LOCK
            + "requests==2.31.0\n"
            + "    # via -r tests/requirements.txt\n"
        )

        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT), "tests/requirements.lock"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 1
        assert "requests" in result.stderr

    def test_identical_lock_exits_zero(self, tmp_path):
        """Unchanged working-tree lock → exit 0."""
        lock_file = _make_git_repo(tmp_path, _BASE_LOCK)
        lock_file.write_text(_BASE_LOCK)

        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT), "tests/requirements.lock"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0, result.stderr

    def test_new_lockfile_absent_from_head_exits_one(self, tmp_path):
        """Lockfile absent from HEAD (first introduction) → all packages are additions → exit 1."""
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                       capture_output=True, env=_CLEAN_ENV)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path,
                       check=True, capture_output=True, env=_CLEAN_ENV)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        lock_file = tests_dir / "requirements.lock"
        lock_file.write_text(_BASE_LOCK)

        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT), "tests/requirements.lock"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 1
        assert "pytest" in result.stderr

    def test_missing_lockfile_exits_one(self, tmp_path):
        """Path given but file absent from working tree → exit 1 with error message."""
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True,
                       capture_output=True, env=_CLEAN_ENV)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=tmp_path, check=True, capture_output=True, env=_CLEAN_ENV)

        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT), "tests/requirements.lock"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 1
        assert "file not found" in result.stderr

    def test_transitive_only_addition_exits_zero(self, tmp_path):
        """A new package with # via <dep> (no -r) is transitive-only → exit 0."""
        lock_file = _make_git_repo(tmp_path, _BASE_LOCK)
        lock_file.write_text(
            _BASE_LOCK
            + "attrs==23.1.0\n"
            + "    # via pytest\n"
        )

        result = subprocess.run(
            ["bash", str(GUARD_SCRIPT), "tests/requirements.lock"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0, result.stderr
