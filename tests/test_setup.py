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


class TestSetupShPreservation:
    def _run_setup(self, repo, *args):
        return subprocess.run(
            ["sh", "scripts/setup.sh", *args],
            cwd=repo, check=False, capture_output=True, text=True, env=_CLEAN_ENV,
        )

    def test_idempotent_rerun(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        r1 = self._run_setup(repo)
        assert r1.returncode == 0
        r2 = self._run_setup(repo)
        assert r2.returncode == 0
        assert r2.stderr == ""

    def test_idempotent_with_whitelisted_hookspath(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        _git("config", "--local", "core.hooksPath", ".githooks", cwd=repo)
        result = self._run_setup(repo)
        assert result.returncode == 0
        assert result.stderr == ""
        val = subprocess.check_output(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=repo, text=True, env=_CLEAN_ENV,
        ).strip()
        assert val == ".githooks", "whitelisted core.hooksPath must not be silently cleared"

    def test_refuses_to_clobber_existing_regular_file_hook(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "pre-push"
        hook.write_text("#!/bin/sh\nexit 0\n")
        result = self._run_setup(repo)
        assert result.returncode != 0
        assert not hook.is_symlink(), "hook must not have been replaced"
        assert str(hook) in result.stderr
        assert not (hooks_dir / "commit-msg").exists(), "Apply section must not run if preflight found conflicts"

    def test_refuses_to_clobber_foreign_symlink(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        link = hooks_dir / "pre-push"
        link.symlink_to("/tmp/foo")
        result = self._run_setup(repo)
        assert result.returncode != 0
        assert os.readlink(link) == "/tmp/foo", "symlink target must be unchanged"
        assert str(link) in result.stderr

    def test_refuses_to_unset_user_core_hookspath(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        _git("config", "--local", "core.hooksPath", "/tmp/elsewhere", cwd=repo)
        result = self._run_setup(repo)
        assert result.returncode != 0
        val = subprocess.check_output(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=repo, text=True, env=_CLEAN_ENV,
        ).strip()
        assert val == "/tmp/elsewhere", "core.hooksPath must remain unchanged"

    def test_force_overrides_all_conflicts(self, repo_with_worktree):
        repo, _ = repo_with_worktree
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        _git("config", "--local", "core.hooksPath", "/tmp/elsewhere", cwd=repo)
        (hooks_dir / "pre-push").write_text("#!/bin/sh\nexit 0\n")
        (hooks_dir / "commit-msg").symlink_to("/tmp/foreign")

        result = self._run_setup(repo, "--force")
        assert result.returncode == 0

        for name in ("pre-push", "commit-msg"):
            link = hooks_dir / name
            assert link.is_symlink(), f"{link} must be a symlink"
            assert os.readlink(link) == str(repo / ".githooks" / name)

        hp = subprocess.run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=repo, capture_output=True, text=True, env=_CLEAN_ENV,
        )
        assert hp.returncode != 0, "core.hooksPath must be unset after --force"

        assert "warning:" in result.stderr


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
