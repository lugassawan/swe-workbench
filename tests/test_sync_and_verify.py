"""Regression test for sync-and-verify.sh stdout contract (issue #197).

The script declares: Stdout contract: WORKTREE_GONE=0|1.
It is invoked via ``eval "$(...)"`` so any byte on stdout that isn't that
exact assignment becomes a shell command in the caller's environment.

Block B (git pull --ff-only) leaked "Already up to date." to stdout.
Block C (git rev-parse --verify) leaked the resolved SHA to stdout.
Both were eval'd by the caller, causing "command not found" errors.

This test pins the contract: stdout must be exactly one line.
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
    / "sync-and-verify.sh"
)
BRANCH = "feature/197-fixture-branch"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
NOISE_STRINGS = [
    "Switched to branch",
    "Already on",
    "Already up to date",
    "Fast-forward",
    "Updating",
]


def _build_repo(base: Path, default_branch: str = "main") -> Path:
    """Create a minimal git environment: bare origin + working main_repo.

    default_branch controls the name of the default branch so tests can verify
    Treatment D works on repos whose default branch is not 'main'.
    """
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
    # Prevent the global core.hooksPath (set to swe-workbench hooks) from
    # running the commit-msg hook inside test fixture repos.  The fixture
    # tests sync-and-verify.sh, not commit formatting.
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


@pytest.fixture
def git_repo_trunk(tmp_path):
    """Repo whose default branch is 'trunk', not 'main' (Treatment D coverage)."""
    return _build_repo(tmp_path, default_branch="trunk")


def _run_script(repo: Path, head_ref: str, default_branch: str = "main"):
    return subprocess.run(
        ["bash", str(SCRIPT), head_ref, default_branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


def _assert_contract(result, expected: str) -> None:
    assert result.returncode == 0, (
        f"Script exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    lines = result.stdout.strip().splitlines()
    assert lines == [f"WORKTREE_GONE={expected}"], (
        f"Expected stdout=['WORKTREE_GONE={expected}'], got {lines!r}\n"
        f"Full stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not SHA_PATTERN.search(result.stdout), (
        f"stdout must not contain a 40-hex SHA: {result.stdout!r}"
    )
    for noise in NOISE_STRINGS:
        assert noise not in result.stdout, (
            f"stdout must not contain {noise!r}: {result.stdout!r}"
        )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("branch_present", "0"),
        ("branch_absent", "1"),
    ],
)
class TestSyncAndVerifyStdoutContract:
    """Pin the stdout contract: exactly one line, WORKTREE_GONE=0|1, no git noise."""

    def test_stdout_is_exact_contract(self, git_repo, case, expected):
        if case == "branch_absent":
            subprocess.run(
                ["git", "branch", "-D", BRANCH],
                cwd=str(git_repo),
                check=True,
                capture_output=True,
                text=True,
                env=_CLEAN_ENV,
            )

        result = _run_script(git_repo, BRANCH, default_branch="main")
        _assert_contract(result, expected)


class TestSyncAndVerifyNonMainDefaultBranch:
    """Treatment D: script must work when the default branch is not 'main'."""

    def test_branch_present_trunk_default(self, git_repo_trunk):
        result = _run_script(git_repo_trunk, BRANCH, default_branch="trunk")
        _assert_contract(result, "0")

    def test_branch_absent_trunk_default(self, git_repo_trunk):
        subprocess.run(
            ["git", "branch", "-D", BRANCH],
            cwd=str(git_repo_trunk),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        result = _run_script(git_repo_trunk, BRANCH, default_branch="trunk")
        _assert_contract(result, "1")


class TestSyncAndVerifyEvalSafety:
    """Regression: caller adding `2>&1` to $(...) must not let git output
    poison eval. Specifically, git's '* branch main -> FETCH_HEAD' tracking
    line must not parse as a `> FETCH_HEAD` redirect inside eval."""

    def test_eval_with_merged_stderr_does_not_create_stray_files(
        self, tmp_path, git_repo
    ):
        # Push a new commit to origin so the next `git pull --ff-only origin main`
        # actually transfers refs and prints the `From ... -> FETCH_HEAD` line.
        clone = tmp_path / "second_clone"
        no_hooks = tmp_path / ".nohooks"
        no_hooks.mkdir(exist_ok=True)  # don't rely on git_repo fixture side-effect

        subprocess.run(
            ["git", "clone", str(tmp_path / "origin.git"), str(clone)],
            check=True,
            capture_output=True,
            env=_CLEAN_ENV,
        )
        subprocess.run(
            ["git", "config", "user.email", "ci@example.com"],
            cwd=str(clone),
            check=True,
            env=_CLEAN_ENV,
        )
        subprocess.run(
            ["git", "config", "user.name", "CI"],
            cwd=str(clone),
            check=True,
            env=_CLEAN_ENV,
        )
        subprocess.run(
            ["git", "config", "core.hooksPath", str(no_hooks)],
            cwd=str(clone),
            check=True,
            env=_CLEAN_ENV,
        )
        (clone / "new.txt").write_text("new\n")
        subprocess.run(
            ["git", "add", "new.txt"], cwd=str(clone), check=True, env=_CLEAN_ENV
        )
        subprocess.run(
            ["git", "commit", "-m", "trigger fetch output"],
            cwd=str(clone),
            check=True,
            capture_output=True,
            env=_CLEAN_ENV,
        )
        subprocess.run(
            # HEAD:main — robust to CI runners where the bare repo's HEAD
            # defaults to `master`, leaving the clone without a local `main`
            # branch; this pushes whatever is checked out to origin/main.
            ["git", "push", "origin", "HEAD:main"],
            cwd=str(clone),
            check=True,
            capture_output=True,
            env=_CLEAN_ENV,
        )

        # Reproduce the caller-side bug: eval "$(... 2>&1)".
        # Run inside a clean tempdir so any stray redirect lands somewhere
        # observable (and out of the test runner's cwd).
        eval_cwd = tmp_path / "eval_cwd"
        eval_cwd.mkdir()
        # Glob target: ensure `*` expands to something so the eval'd `*` token
        # behaves the same way as in the bug repro (where cwd contained files).
        (eval_cwd / "decoy").write_text("")

        # Pre-condition: origin must be ahead of local so git pull actually
        # fetches new refs. The `* branch main -> FETCH_HEAD` tracking line
        # only appears when git pull fetches something new. If origin and local
        # are already in sync, the test would be vacuous.
        # Note: we use ls-remote (not rev-list HEAD..origin/main) because we
        # haven't fetched yet — origin/main tracking ref is stale locally.
        ls_remote_out = subprocess.run(
            ["git", "ls-remote", "origin", "refs/heads/main"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        ).stdout.split()
        assert ls_remote_out, (
            "ls-remote returned no output for refs/heads/main — "
            "origin has no main branch; fixture setup failed."
        )
        origin_sha = ls_remote_out[0]
        local_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        ).stdout.strip()
        assert origin_sha != local_sha, (
            f"Pre-condition: origin/main ({origin_sha}) must be ahead of "
            f"local HEAD ({local_sha}). git pull won't fetch — the "
            f"'-> FETCH_HEAD' tracking line won't appear and the test is vacuous."
        )

        # Guard: eval_cwd and SCRIPT paths must not contain double-quotes,
        # which would break the inline bash string we build below.
        assert '"' not in str(eval_cwd) and '"' not in str(SCRIPT), (
            f"Path contains double-quote — inline bash string will break.\n"
            f"eval_cwd={eval_cwd}, SCRIPT={SCRIPT}"
        )

        # Capture BEFORE cd-ing to eval_cwd: the script needs a valid git cwd
        # to resolve MAIN_REPO. If we cd first, the script exits early.
        runner = (
            f'output="$(bash "{SCRIPT}" "{BRANCH}" main 2>&1)"; '
            f'cd "{eval_cwd}"; '
            f'eval "$output" 2>/dev/null || true'
        )
        subprocess.run(
            ["bash", "-c", runner],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )

        assert not (eval_cwd / "FETCH_HEAD").exists(), (
            f"Stray FETCH_HEAD created in {eval_cwd} — the script's "
            f"combined stdout+stderr still contains a git tracking line that "
            f"eval parsed as a `> FETCH_HEAD` redirect."
        )
