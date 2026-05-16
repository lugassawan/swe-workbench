"""
Tests for scripts/setup.sh — subprocess-based so they exercise the real POSIX sh logic.
"""
import os
import subprocess
from pathlib import Path

SETUP_SH = Path(__file__).parent.parent / "scripts" / "setup.sh"

# Strip GIT_* vars so hook-context env doesn't leak into ephemeral test repos.
# When tests run inside a git pre-push hook, GIT_DIR points to the host repo —
# setup.sh's `git rev-parse` would then target the host instead of tmp_path.
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run_setup(tmp_path: Path) -> subprocess.CompletedProcess:
    """Run setup.sh inside a minimal git repo rooted at tmp_path."""
    init = subprocess.run(
        ["git", "init", str(tmp_path)], capture_output=True, text=True, env=_CLEAN_ENV
    )
    if init.returncode != 0:
        raise RuntimeError(f"git init failed: {init.stderr.strip()}")
    return subprocess.run(
        ["sh", str(SETUP_SH)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


class TestSetupShGlobGuard:
    def test_empty_githooks_creates_no_symlinks(self, tmp_path):
        """When .githooks/ exists but is empty, no symlinks are created."""
        (tmp_path / ".githooks").mkdir()
        result = _run_setup(tmp_path)
        assert result.returncode == 0, result.stderr
        hooks_dir = tmp_path / ".git" / "hooks"
        symlinks = [p for p in hooks_dir.iterdir() if p.is_symlink()] if hooks_dir.exists() else []
        assert symlinks == [], (
            f"Expected no symlinks in .git/hooks/ when .githooks/ is empty, "
            f"but found: {[p.name for p in symlinks]}"
        )

    def test_hook_file_creates_symlink(self, tmp_path):
        """When .githooks/ has a hook file, setup.sh creates a symlink for it."""
        githooks_dir = tmp_path / ".githooks"
        githooks_dir.mkdir()
        (githooks_dir / "commit-msg").write_text("#!/bin/sh\n")
        result = _run_setup(tmp_path)
        assert result.returncode == 0, result.stderr
        link = tmp_path / ".git" / "hooks" / "commit-msg"
        assert link.is_symlink(), "Expected a commit-msg symlink in .git/hooks/"
        assert link.resolve() == (githooks_dir / "commit-msg").resolve()

    def test_multiple_hooks_create_multiple_symlinks(self, tmp_path):
        """Multiple hook files each get their own symlink."""
        githooks_dir = tmp_path / ".githooks"
        githooks_dir.mkdir()
        for name in ("commit-msg", "pre-push", "pre-commit"):
            (githooks_dir / name).write_text("#!/bin/sh\n")
        result = _run_setup(tmp_path)
        assert result.returncode == 0, result.stderr
        hooks_dir = tmp_path / ".git" / "hooks"
        for name in ("commit-msg", "pre-push", "pre-commit"):
            link = hooks_dir / name
            assert link.is_symlink(), f"Expected symlink for {name}"

    def test_no_githooks_dir_exits_cleanly(self, tmp_path):
        """When .githooks/ does not exist at all, setup.sh exits 0 without errors."""
        result = _run_setup(tmp_path)
        assert result.returncode == 0, result.stderr
        hooks_dir = tmp_path / ".git" / "hooks"
        symlinks = [p for p in hooks_dir.iterdir() if p.is_symlink()] if hooks_dir.exists() else []
        assert symlinks == [], (
            f"Expected no symlinks when .githooks/ is absent, "
            f"but found: {[p.name for p in symlinks]}"
        )
