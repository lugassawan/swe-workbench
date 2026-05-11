"""Regression test for issue #165 — setup.sh must install symlinks that
resolve from inside a git worktree, not just from the main repo's hooks dir.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SETUP_SH = REPO_ROOT / "scripts" / "setup.sh"

# Strip GIT_* vars so hook-context env doesn't leak into ephemeral test repos.
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
        env=_CLEAN_ENV,
    )


@pytest.fixture
def repo_with_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)

    (repo / "scripts").mkdir()
    shutil.copy(SETUP_SH, repo / "scripts" / "setup.sh")
    (repo / "scripts" / "setup.sh").chmod(0o755)
    (repo / ".githooks").mkdir()
    for name in ("pre-push", "commit-msg"):
        h = repo / ".githooks" / name
        h.write_text("#!/bin/sh\nexit 0\n")
        h.chmod(0o755)

    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)

    worktree = tmp_path / "wt"
    _git("worktree", "add", "-q", str(worktree), "-b", "feature/x", cwd=repo)
    return repo, worktree


class TestSetupShInWorktree:
    def test_symlinks_resolve_from_worktree(self, repo_with_worktree):
        repo, worktree = repo_with_worktree
        subprocess.run(["sh", "scripts/setup.sh"], cwd=worktree, check=True, env=_CLEAN_ENV)

        git_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"], cwd=worktree, text=True, env=_CLEAN_ENV
        ).strip()
        git_dir_path = Path(git_dir) if os.path.isabs(git_dir) else worktree / git_dir

        for src in (repo / ".githooks").iterdir():
            link = git_dir_path / "hooks" / src.name
            assert link.is_symlink(), f"{link} is not a symlink"
            target = link.resolve(strict=True)

    def test_symlinks_resolve_from_main_repo(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        subprocess.run(["sh", "scripts/setup.sh"], cwd=repo, check=True, env=_CLEAN_ENV)
        for src in (repo / ".githooks").iterdir():
            link = repo / ".git" / "hooks" / src.name
            assert link.is_symlink()
            assert link.resolve(strict=False).exists()
