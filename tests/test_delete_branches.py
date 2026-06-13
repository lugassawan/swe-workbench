"""Regression test for delete-branches.sh stdout contract (issue #449).

The script declares:
  Stdout contract: LOCAL_DELETED=0|1 then REMOTE_DELETED=0|1

It is invoked via ``eval "$(...)"`` so any byte on stdout that isn't those
exact assignments becomes a shell command in the caller's environment.

This test pins the contract: stdout must be exactly two lines.
"""

import re
import subprocess
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-cleanup-merged"
    / "scripts"
    / "delete-branches.sh"
)
BRANCH = "feature/449-fixture-branch"  # slash → quoting coverage
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
NOISE_STRINGS = [
    "To ",
    "- [deleted]",
    "Switched to branch",
    "Already on",
    "Already up to date",
    "Fast-forward",
    "Updating",
]


def _build_repo(base: Path, default_branch: str = "main") -> Path:
    """Create a minimal git environment: bare origin + working main_repo."""
    origin = base / "origin.git"
    repo = base / "main_repo"

    def run(*args, cwd=None):
        return subprocess.run(
            list(args),
            cwd=str(cwd or base),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )

    run("git", "init", "--bare", str(origin))
    run("git", "init", str(repo))
    run("git", "config", "user.email", "test@example.com", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    # Suppress host hooks inside fixture repos — we test delete-branches.sh, not
    # commit formatting.
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    (repo / "README.md").write_text("hello\n")
    run("git", "add", "README.md", cwd=repo)
    run("git", "commit", "-m", "init", cwd=repo)
    run("git", "branch", "-M", default_branch, cwd=repo)
    run("git", "remote", "add", "origin", str(origin), cwd=repo)
    run("git", "push", "-u", "origin", default_branch, cwd=repo)

    run("git", "checkout", "-b", BRANCH, cwd=repo)
    (repo / "feature.txt").write_text("feature\n")
    run("git", "add", "feature.txt", cwd=repo)
    run("git", "commit", "-m", "add feature", cwd=repo)
    run("git", "push", "-u", "origin", BRANCH, cwd=repo)
    run("git", "checkout", default_branch, cwd=repo)

    return repo


@pytest.fixture
def git_repo(tmp_path):
    return _build_repo(tmp_path, default_branch="main")


def _run_script(repo: Path, head_ref: str):
    return subprocess.run(
        ["bash", str(SCRIPT), head_ref],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


def _local_branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )
    return result.returncode == 0


def _remote_branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )
    return bool(result.stdout.strip())


def _assert_contract(result, local: str, remote: str) -> None:
    assert result.returncode == 0, (
        f"Script exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    lines = result.stdout.strip().splitlines()
    expected = [f"LOCAL_DELETED={local}", f"REMOTE_DELETED={remote}"]
    assert lines == expected, (
        f"Expected stdout={expected}, got {lines!r}\n"
        f"Full stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not SHA_PATTERN.search(result.stdout), (
        f"stdout must not contain a 40-hex SHA: {result.stdout!r}"
    )
    for noise in NOISE_STRINGS:
        assert noise not in result.stdout, (
            f"stdout must not contain {noise!r}: {result.stdout!r}"
        )


class TestDeleteBranchesBothPresent:
    """Happy path: local and remote branch both exist."""

    def test_local_present_remote_present(self, git_repo):
        result = _run_script(git_repo, BRANCH)
        _assert_contract(result, "1", "1")
        assert not _local_branch_exists(git_repo, BRANCH), (
            "Local branch must be deleted after script runs"
        )
        assert not _remote_branch_exists(git_repo, BRANCH), (
            "Remote branch must be deleted after script runs"
        )


class TestDeleteBranchesLocalAbsent:
    """WORKTREE_GONE=1 path: local branch already removed (e.g. rimba hook ran)."""

    def test_local_absent_remote_present(self, git_repo):
        # Pre-delete local branch to simulate WORKTREE_GONE=1 path
        subprocess.run(
            ["git", "branch", "-D", BRANCH],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        result = _run_script(git_repo, BRANCH)
        _assert_contract(result, "0", "1")
        assert not _remote_branch_exists(git_repo, BRANCH), (
            "Remote branch must still be deleted even when local was already gone"
        )


class TestDeleteBranchesRemoteAbsent:
    """Remote already deleted (GitHub auto-delete-head-branches)."""

    def test_remote_absent_is_success(self, git_repo):
        # Pre-delete remote branch
        subprocess.run(
            ["git", "push", "origin", "--delete", BRANCH],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        result = _run_script(git_repo, BRANCH)
        _assert_contract(result, "1", "0")
        assert result.returncode == 0, "exit 0 even when remote was already gone"


class TestDeleteBranchesIdempotent:
    """Both already deleted — idempotent, exit 0."""

    def test_both_absent_is_idempotent(self, git_repo):
        subprocess.run(
            ["git", "branch", "-D", BRANCH],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        subprocess.run(
            ["git", "push", "origin", "--delete", BRANCH],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        result = _run_script(git_repo, BRANCH)
        _assert_contract(result, "0", "0")


class TestDeleteBranchesStdoutContract:
    """Exact two-line stdout — no git noise, no SHAs."""

    def test_stdout_is_exact_contract_when_both_present(self, git_repo):
        result = _run_script(git_repo, BRANCH)
        assert result.returncode == 0
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 2, (
            f"Expected exactly 2 stdout lines, got {len(lines)}: {lines!r}"
        )
        assert lines[0] == "LOCAL_DELETED=1"
        assert lines[1] == "REMOTE_DELETED=1"


class TestDeleteBranchesEvalSafety:
    """Regression: eval "$(bash SCRIPT BRANCH 2>&1)" must not create stray files.

    Transport lines like "To <url>" or "- [deleted]" from git push output must not
    leak into the eval'd environment and cause redirect or command errors.
    """

    def test_eval_with_merged_stderr_does_not_create_stray_files(
        self, tmp_path, git_repo
    ):
        eval_cwd = tmp_path / "eval_cwd"
        eval_cwd.mkdir()
        # Glob target: ensure `*` expands to something in the eval'd shell
        (eval_cwd / "decoy").write_text("")

        # Guard: paths must not contain double-quotes (would break inline bash)
        assert (
            '"' not in str(eval_cwd)
            and '"' not in str(SCRIPT)
            and '"' not in BRANCH
        ), (
            f"Path or branch contains double-quote — inline bash string will break.\n"
            f"eval_cwd={eval_cwd}, SCRIPT={SCRIPT}, BRANCH={BRANCH}"
        )

        # Capture BEFORE cd-ing to eval_cwd: the script needs a valid git cwd
        # to resolve MAIN_REPO.  If we cd first, the script exits early.
        runner = (
            f'output="$(bash "{SCRIPT}" "{BRANCH}" 2>&1)"; '
            f'cd "{eval_cwd}"; '
            f'eval "$output" 2>/dev/null || true'
        )
        result = subprocess.run(
            ["bash", "-c", runner],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        assert result.returncode == 0, (
            f"bash runner failed (rc={result.returncode}):\n{result.stderr}"
        )

        # No stray files from redirect lines like "To <url>" parsed as `> <url>`
        stray = [f for f in eval_cwd.iterdir() if f.name != "decoy"]
        assert not stray, (
            f"Stray files created in {eval_cwd} — the script's combined "
            f"stdout+stderr contains output that eval parsed as shell commands: "
            f"{[f.name for f in stray]}"
        )
