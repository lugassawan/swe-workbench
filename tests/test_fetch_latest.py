"""Tests for fetch-latest.sh — refreshes the remote-tracking ref for one
branch and reports whether it moved.

The script exists so branch-sync never compares against a locally-cached
remote ref: stdout is an eval-safe KEY=VALUE contract (DEFAULT_BRANCH,
FETCH_RESULT=updated|unchanged, OLD_REF, NEW_REF). Exit is 0 on a
successful fetch, non-zero on a fetch failure (git's stderr passes
through; no contract lines are emitted, so the caller has nothing
actionable to eval).
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
    / "fetch-latest.sh"
)

# gh is not authenticated/relevant to a throwaway local repo and no network
# should be reachable — restrict PATH so only git/bash resolve. File-path
# remotes keep every fetch offline.
_NO_GH_ENV = {**_CLEAN_ENV, "PATH": "/usr/bin:/bin"}


def _run(*args, cwd, env=None):
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=env or _CLEAN_ENV
    )


def _configure(repo: Path, base: Path) -> None:
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    _run("git", "config", "commit.gpgsign", "false", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)


def _build_repo_pair(base: Path, default_branch: str = "main") -> tuple[Path, Path]:
    """Create a bare origin plus a clone holding one pushed commit."""
    origin = base / "origin.git"
    _run("git", "init", "--bare", str(origin), cwd=base)
    repo = base / "repo"
    _run("git", "clone", str(origin), str(repo), cwd=base)
    _configure(repo, base)
    (repo / "README.md").write_text("one\n")
    _run("git", "add", "README.md", cwd=repo)
    _run("git", "commit", "-m", "one", cwd=repo)
    _run("git", "branch", "-M", default_branch, cwd=repo)
    _run("git", "push", "origin", default_branch, cwd=repo)
    return origin, repo


def _advance_origin(base: Path, origin: Path, default_branch: str) -> str:
    """Push a second commit to origin from a throwaway clone; return its sha."""
    other = base / "other"
    # --branch: the bare repo's HEAD may name an unborn or different branch —
    # checking out default_branch explicitly makes the new commit descend
    # from the current tip so the push fast-forwards.
    _run("git", "clone", "--branch", default_branch, str(origin), str(other), cwd=base)
    _configure(other, base)
    (other / "second.txt").write_text("two\n")
    _run("git", "add", "second.txt", cwd=other)
    _run("git", "commit", "-m", "two", cwd=other)
    # Push HEAD explicitly: the clone of a bare repo whose HEAD names a
    # different (or unborn) branch may not have default_branch checked out.
    _run("git", "push", "origin", f"HEAD:refs/heads/{default_branch}", cwd=other)
    return _run("git", "rev-parse", "HEAD", cwd=other).stdout.strip()


def _run_script(cwd: Path, *args: str):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_NO_GH_ENV,
    )


def _parse(stdout: str) -> dict:
    return dict(line.split("=", 1) for line in stdout.strip().splitlines())


def _tracking_ref(repo: Path, branch: str) -> str:
    return _run("git", "rev-parse", f"refs/remotes/origin/{branch}", cwd=repo).stdout.strip()


@pytest.fixture
def repo_pair(tmp_path: Path) -> tuple[Path, Path]:
    return _build_repo_pair(tmp_path)


@pytest.fixture
def repo_pair_trunk(tmp_path: Path) -> tuple[Path, Path]:
    return _build_repo_pair(tmp_path, default_branch="trunk")


class TestFetchUpdatesStaleRef:
    def test_fetch_updates_stale_ref_and_reports_updated(self, tmp_path, repo_pair):
        origin, repo = repo_pair
        stale = _tracking_ref(repo, "main")
        new = _advance_origin(tmp_path, origin, "main")

        result = _run_script(repo, "main")

        assert result.returncode == 0, result.stderr
        parsed = _parse(result.stdout)
        assert parsed["DEFAULT_BRANCH"] == "main"
        assert parsed["FETCH_RESULT"] == "updated"
        assert parsed["OLD_REF"] == stale
        assert parsed["NEW_REF"] == new
        # The tracking ref itself moved — later merge-base comparisons in
        # the skill read remote truth, not the cached sha.
        assert _tracking_ref(repo, "main") == new


class TestFetchNoChange:
    def test_fetch_with_no_new_commits_reports_unchanged(self, repo_pair):
        _, repo = repo_pair
        first = _run_script(repo, "main")
        assert first.returncode == 0, first.stderr

        second = _run_script(repo, "main")

        assert second.returncode == 0, second.stderr
        parsed = _parse(second.stdout)
        assert parsed["FETCH_RESULT"] == "unchanged"
        assert parsed["OLD_REF"] == parsed["NEW_REF"]


class TestNoPriorTrackingRef:
    def test_no_prior_tracking_ref_reports_updated_with_empty_old_ref(self, repo_pair):
        _, repo = repo_pair
        _run("git", "update-ref", "-d", "refs/remotes/origin/main", cwd=repo)

        result = _run_script(repo, "main")

        assert result.returncode == 0, result.stderr
        parsed = _parse(result.stdout)
        assert parsed["FETCH_RESULT"] == "updated"
        # %q of an empty value is '' — present as a key, eval-safe as empty.
        assert parsed["OLD_REF"] == "''"
        assert parsed["NEW_REF"]


class TestFetchFailure:
    def test_fetch_failure_exits_nonzero_with_no_contract_lines(self, tmp_path, repo_pair):
        _, repo = repo_pair
        _run("git", "remote", "set-url", "origin", str(tmp_path / "nonexistent.git"), cwd=repo)

        result = _run_script(repo, "main")

        assert result.returncode != 0
        assert "FETCH_RESULT" not in result.stdout
        # The script's own marker plus git's verbatim passthrough stderr — the skill
        # reports this verbatim and aborts.
        assert "fetch-latest:" in result.stderr
        assert "fatal:" in result.stderr
        assert result.stderr.strip()


class TestArgumentGuard:
    def test_missing_branch_arg_exits_nonzero_usage(self, repo_pair):
        _, repo = repo_pair

        result = _run_script(repo)

        assert result.returncode != 0
        assert "Usage: fetch-latest.sh" in result.stderr


class TestWorkTreeGuard:
    def test_not_inside_git_work_tree_exits_nonzero(self, tmp_path):
        result = _run_script(tmp_path, "main")

        assert result.returncode != 0
        assert "not inside a git work tree" in result.stderr


class TestNonMainDefaultBranch:
    def test_fetch_with_non_main_default_branch(self, tmp_path, repo_pair_trunk):
        origin, repo = repo_pair_trunk
        new = _advance_origin(tmp_path, origin, "trunk")

        result = _run_script(repo, "trunk")

        assert result.returncode == 0, result.stderr
        parsed = _parse(result.stdout)
        assert parsed["DEFAULT_BRANCH"] == "trunk"
        assert parsed["FETCH_RESULT"] == "updated"
        assert parsed["NEW_REF"] == new
        assert _tracking_ref(repo, "trunk") == new


class TestEvalSafety:
    def test_stdout_is_eval_safe(self, repo_pair):
        _, repo = repo_pair
        stdout = _run_script(repo, "main").stdout

        probe = subprocess.run(
            ["bash", "-c", 'eval "$1"; test -n "$NEW_REF" && test -n "$DEFAULT_BRANCH"',
             "fetch-latest-eval-probe", stdout],
            capture_output=True,
            text=True,
            env=_NO_GH_ENV,
        )
        assert probe.returncode == 0, probe.stderr

    def test_metachar_branch_name_round_trips_eval(self, repo_pair):
        """Branch names may legally contain shell metacharacters — the %q
        quoting of DEFAULT_BRANCH must keep the contract eval-safe for them
        (an unquoted emit would let the branch name execute as code)."""
        _, repo = repo_pair
        weird = "quo'te;br"
        _run("git", "branch", weird, cwd=repo)
        _run("git", "push", "origin", f"refs/heads/{weird}:refs/heads/{weird}", cwd=repo)

        result = _run_script(repo, weird)

        assert result.returncode == 0, result.stderr
        probe = subprocess.run(
            ["bash", "-c", 'eval "$1"; test "$DEFAULT_BRANCH" = "$2"',
             "fetch-latest-eval-probe", result.stdout, weird],
            capture_output=True,
            text=True,
            env=_NO_GH_ENV,
        )
        assert probe.returncode == 0, probe.stderr

    def test_empty_old_ref_is_eval_safe(self, repo_pair):
        _, repo = repo_pair
        _run("git", "update-ref", "-d", "refs/remotes/origin/main", cwd=repo)
        result = _run_script(repo, "main")
        assert result.returncode == 0, result.stderr

        probe = subprocess.run(
            ["bash", "-c", 'eval "$1"; test -z "$OLD_REF"', "fetch-latest-eval-probe", result.stdout],
            capture_output=True,
            text=True,
            env=_NO_GH_ENV,
        )
        assert probe.returncode == 0, probe.stderr
