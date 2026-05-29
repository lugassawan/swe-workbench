"""Tests for the GIT_DIR leak guard and sentinel injection in conftest.py."""

import os
import subprocess

import pytest

from conftest import _CLEAN_ENV, _GIT_DIR_GUARD_SENTINEL


class TestGitDirLeakGuard:
    def test_guard_blocks_git_dir_in_explicit_env(self):
        """subprocess.run with GIT_DIR in an explicit env= raises AssertionError."""
        with pytest.raises(AssertionError, match="GIT_DIR"):
            subprocess.run(["true"], env={"GIT_DIR": "/x"})

    def test_guard_blocks_git_dir_inherited(self):
        """subprocess.run with no env= inherits process env; sentinel makes guard fire."""
        with pytest.raises(AssertionError, match="GIT_DIR"):
            subprocess.run(["true"])

    def test_guard_allows_clean_env(self):
        """subprocess.run with env=dict(_CLEAN_ENV) succeeds (no GIT_DIR in _CLEAN_ENV)."""
        result = subprocess.run(["true"], env=dict(_CLEAN_ENV), capture_output=True)
        assert result.returncode == 0

    def test_sentinel_present(self):
        """The GIT_DIR sentinel is injected into os.environ during the test session."""
        assert os.environ.get("GIT_DIR") == _GIT_DIR_GUARD_SENTINEL
