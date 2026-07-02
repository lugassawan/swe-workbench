"""Tests for apply-resolution.sh — the ours/theirs inversion mapping.

git inverts --ours/--theirs under rebase relative to merge:
  merge:  --ours = HEAD (your branch)         --theirs = incoming branch
  rebase: --ours = rebase target (default br)  --theirs = replayed commit (your branch)

apply-resolution.sh takes a user-intent side (mine/main) and an operation
(merge/rebase) and must translate to git's --ours/--theirs accordingly —
callers must never pass raw ours/theirs.
"""

import subprocess
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-branch-sync"
    / "scripts"
    / "apply-resolution.sh"
)

CONFLICT_FILE = "shared.txt"
MINE_CONTENT = "feature-version\n"
MAIN_CONTENT = "main-version\n"


def _run(*args, cwd):
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=_CLEAN_ENV
    )


def _build_repo(base: Path) -> Path:
    """main with one commit, feature branch diverging on the same file/line."""
    repo = base / "repo"
    _run("git", "init", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    (repo / CONFLICT_FILE).write_text("base\n")
    _run("git", "add", CONFLICT_FILE, cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "branch", "-M", "main", cwd=repo)

    _run("git", "checkout", "-b", "feature", cwd=repo)
    (repo / CONFLICT_FILE).write_text(MINE_CONTENT)
    _run("git", "add", CONFLICT_FILE, cwd=repo)
    _run("git", "commit", "-m", "feature change", cwd=repo)

    _run("git", "checkout", "main", cwd=repo)
    (repo / CONFLICT_FILE).write_text(MAIN_CONTENT)
    _run("git", "add", CONFLICT_FILE, cwd=repo)
    _run("git", "commit", "-m", "main change", cwd=repo)

    _run("git", "checkout", "feature", cwd=repo)
    return repo


def _induce_merge_conflict(repo: Path) -> None:
    subprocess.run(
        ["git", "merge", "main"], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
    )


def _induce_rebase_conflict(repo: Path) -> None:
    subprocess.run(
        ["git", "rebase", "main"], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
    )


def _run_script(repo: Path, file_: str, side: str, op: str):
    return subprocess.run(
        ["bash", str(SCRIPT), file_, side, op],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


def _is_staged(repo: Path, file_: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )
    return file_ not in result.stdout.splitlines()


class TestApplyResolutionMerge:
    """merge: mine -> --ours (HEAD/feature), main -> --theirs (incoming/main)."""

    def test_mine_under_merge_keeps_feature_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "GIT_SIDE=ours"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_main_under_merge_keeps_main_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "merge")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "GIT_SIDE=theirs"
        assert (repo / CONFLICT_FILE).read_text() == MAIN_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)


class TestApplyResolutionRebase:
    """rebase inverts: mine -> --theirs (replayed feature), main -> --ours (target)."""

    def test_mine_under_rebase_keeps_feature_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_rebase_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "rebase")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "GIT_SIDE=theirs"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_main_under_rebase_keeps_main_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_rebase_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "rebase")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "GIT_SIDE=ours"
        assert (repo / CONFLICT_FILE).read_text() == MAIN_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)


class TestApplyResolutionInvalidArgs:
    def test_rejects_unknown_side(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "theirs", "merge")

        assert result.returncode != 0
        assert "SIDE" in result.stderr

    def test_rejects_unknown_operation(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "cherry-pick")

        assert result.returncode != 0
        assert "OP" in result.stderr

    def test_missing_args_usage_error(self, tmp_path):
        repo = _build_repo(tmp_path)
        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
        )
        assert result.returncode != 0
        assert "Usage" in result.stderr
