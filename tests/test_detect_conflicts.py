"""Tests for detect-conflicts.sh — OPERATION detection + unmerged-path list.

Stdout contract: line 1 is `OPERATION=merge|rebase|none` (eval-safe);
remaining lines are raw unmerged file paths, one per line.
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
    / "detect-conflicts.sh"
)


def _run(*args, cwd):
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=_CLEAN_ENV
    )


def _build_diverged_repo(base: Path, files: dict) -> Path:
    """main + feature branch, each modifying the given files differently.

    files: {filename: (main_content, feature_content)}
    """
    repo = base / "repo"
    _run("git", "init", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    for name in files:
        (repo / name).write_text("base\n")
    _run("git", "add", *files.keys(), cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "branch", "-M", "main", cwd=repo)

    _run("git", "checkout", "-b", "feature", cwd=repo)
    for name, (_, feature_content) in files.items():
        (repo / name).write_text(feature_content)
    _run("git", "add", *files.keys(), cwd=repo)
    _run("git", "commit", "-m", "feature change", cwd=repo)

    _run("git", "checkout", "main", cwd=repo)
    for name, (main_content, _) in files.items():
        (repo / name).write_text(main_content)
    _run("git", "add", *files.keys(), cwd=repo)
    _run("git", "commit", "-m", "main change", cwd=repo)

    _run("git", "checkout", "feature", cwd=repo)
    return repo


def _run_script(repo: Path):
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
    )


class TestDetectConflictsNone:
    def test_reports_none_when_clean(self, tmp_path):
        repo = _build_diverged_repo(tmp_path, {"a.txt": ("m", "f")})

        result = _run_script(repo)

        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        assert lines == ["OPERATION=none"]


class TestDetectConflictsMerge:
    def test_reports_merge_and_unmerged_file(self, tmp_path):
        repo = _build_diverged_repo(tmp_path, {"a.txt": ("main-version\n", "feature-version\n")})
        subprocess.run(
            ["git", "merge", "main"], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
        )

        result = _run_script(repo)

        lines = result.stdout.strip().splitlines()
        assert lines[0] == "OPERATION=merge"
        assert lines[1:] == ["a.txt"]

    def test_reports_multiple_unmerged_files(self, tmp_path):
        repo = _build_diverged_repo(
            tmp_path,
            {
                "a.txt": ("main-a\n", "feature-a\n"),
                "b.txt": ("main-b\n", "feature-b\n"),
            },
        )
        subprocess.run(
            ["git", "merge", "main"], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
        )

        result = _run_script(repo)

        lines = result.stdout.strip().splitlines()
        assert lines[0] == "OPERATION=merge"
        assert sorted(lines[1:]) == ["a.txt", "b.txt"]


class TestDetectConflictsRebase:
    def test_reports_rebase_and_unmerged_file(self, tmp_path):
        repo = _build_diverged_repo(tmp_path, {"a.txt": ("main-version\n", "feature-version\n")})
        subprocess.run(
            ["git", "rebase", "main"], cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV
        )

        result = _run_script(repo)

        lines = result.stdout.strip().splitlines()
        assert lines[0] == "OPERATION=rebase"
        assert lines[1:] == ["a.txt"]


class TestDetectConflictsNotAGitRepo:
    def test_exits_nonzero_outside_git_repo(self, tmp_path):
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=str(not_a_repo), capture_output=True, text=True, env=_CLEAN_ENV
        )

        assert result.returncode != 0
        assert "git work tree" in result.stderr
