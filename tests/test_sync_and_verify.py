"""Regression test for sync-and-verify.sh stdout contract (issue #197).

The script declares: Stdout contract: WORKTREE_GONE=0|1.
It is invoked via ``eval "$(...)"`` so any byte on stdout that isn't that
exact assignment becomes a shell command in the caller's environment.

Block B (git pull --ff-only) leaked "Already up to date." to stdout.
Block C (git rev-parse --verify) leaked the resolved SHA to stdout.
Both were eval'd by the caller, causing "command not found" errors.

This test pins the contract: stdout must be exactly one line.
"""

import os
import re
import shutil
import subprocess
import time
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


def _assert_contract(result, expected: str, hook_interrupted: str = "0") -> None:
    assert result.returncode == 0, (
        f"Script exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    lines = result.stdout.strip().splitlines()
    expected_lines = [
        f"WORKTREE_GONE={expected}",
        f"HOOK_INTERRUPTED={hook_interrupted}",
    ]
    assert lines == expected_lines, (
        f"Expected stdout={expected_lines!r}, got {lines!r}\n"
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


class TestSyncAndVerifyHookInterruptedDetection:
    """State-based detection (issue #496): a registered worktree whose directory
    is missing on disk is the canonical signal that the rimba post-merge hook
    (or a prior cleanup run) was interrupted mid-deletion — the worktree entry
    and branch ref survive in .git, but the directory is gone from disk."""

    def test_partial_deletion_detected(self, git_repo, tmp_path):
        stray_path = tmp_path / "wt-stray"
        subprocess.run(
            ["git", "worktree", "add", str(stray_path), "-b", "stray-branch"],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        shutil.rmtree(stray_path)

        result = _run_script(git_repo, BRANCH, default_branch="main")
        _assert_contract(result, "0", hook_interrupted="1")


class TestSyncAndVerifyWatchdog:
    """The internal SYNC_TIMEOUT guard (issue #496) must reap a hung `git pull`
    within the configured window — headless (no tty, no job control) — without
    polluting stdout and without leaking the killed subprocess."""

    def test_watchdog_kills_hung_pull_and_stays_clean(self, git_repo, tmp_path):
        real_git = shutil.which("git")
        assert real_git, "git must be resolvable on PATH for this test"

        stub_dir = tmp_path / "stub_bin"
        stub_dir.mkdir()
        stub_git = stub_dir / "git"
        marker = tmp_path / "pull_started"
        stub_git.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "pull" ]; then\n'
            f'  touch "{marker}"\n'
            "  sleep 30\n"
            "fi\n"
            f'exec "{real_git}" "$@"\n'
        )
        stub_git.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": f"{stub_dir}{os.pathsep}{_CLEAN_ENV['PATH']}",
            "SYNC_TIMEOUT": "1",
        }

        start = time.monotonic()
        result = subprocess.run(
            ["bash", str(SCRIPT), BRANCH, "main"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        elapsed = time.monotonic() - start

        assert marker.exists(), "stub git pull was never invoked — test is vacuous"
        assert result.returncode == 0, (
            f"Script exited {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert elapsed < 10, (
            f"watchdog (SYNC_TIMEOUT=1) should reap the hung pull well under "
            f"10s, took {elapsed:.1f}s"
        )

        lines = result.stdout.strip().splitlines()
        assert lines == ["WORKTREE_GONE=0", "HOOK_INTERRUPTED=0"], (
            f"Expected clean two-line contract, got {lines!r}\n"
            f"Full stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

        # TIMED_OUT=1 with HOOK_INTERRUPTED=0 (this case: no worktree was mid-
        # deletion) must still surface a diagnostic — a killed checkout/pull is
        # not silently indistinguishable from a fully successful sync.
        assert "internal timeout" in result.stderr, (
            f"A watchdog timeout with no hook interruption must still warn on "
            f"stderr, got: {result.stderr!r}"
        )

        # Confirm the stubbed sleep was actually reaped, not merely orphaned
        # after the parent exited (process-group kill, not just job kill).
        time.sleep(0.5)
        ps = subprocess.run(
            ["pgrep", "-f", "sleep 30"], capture_output=True, text=True, env=_CLEAN_ENV
        )
        assert ps.returncode != 0, f"orphaned stub sleep process still running: {ps.stdout}"

    def test_watchdog_timeout_concurrent_with_hook_interruption(self, git_repo, tmp_path):
        """The exact scenario issue #496 was filed for: SYNC_TIMEOUT fires while a
        registered worktree is simultaneously missing its directory on disk. Must
        emit the timeout-specific stderr message (corroborated wording), not the
        generic partial-deletion one — this exercises the `TIMED_OUT=1` branch of
        Block D's message selection, which the non-combined tests above never hit
        (one triggers only TIMED_OUT, the other only HOOK_INTERRUPTED)."""
        real_git = shutil.which("git")
        assert real_git, "git must be resolvable on PATH for this test"

        stray_path = tmp_path / "wt-stray-timeout"
        subprocess.run(
            ["git", "worktree", "add", str(stray_path), "-b", "stray-timeout-branch"],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )
        shutil.rmtree(stray_path)

        stub_dir = tmp_path / "stub_bin_combined"
        stub_dir.mkdir()
        stub_git = stub_dir / "git"
        marker = tmp_path / "pull_started_combined"
        stub_git.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "pull" ]; then\n'
            f'  touch "{marker}"\n'
            "  sleep 30\n"
            "fi\n"
            f'exec "{real_git}" "$@"\n'
        )
        stub_git.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": f"{stub_dir}{os.pathsep}{_CLEAN_ENV['PATH']}",
            "SYNC_TIMEOUT": "1",
        }

        result = subprocess.run(
            ["bash", str(SCRIPT), BRANCH, "main"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )

        assert marker.exists(), "stub git pull was never invoked — test is vacuous"
        _assert_contract(result, "0", hook_interrupted="1")
        assert "internal timeout" in result.stderr, (
            f"Expected the TIMED_OUT-corroborated message, got: {result.stderr!r}"
        )
        assert "a prior cleanup was likely interrupted" not in result.stderr, (
            "Got the generic (non-timeout) partial-deletion message instead of "
            f"the timeout-specific one: {result.stderr!r}"
        )


class TestSyncAndVerifySyncTimeoutValidation:
    """A malformed SYNC_TIMEOUT must not silently disable the watchdog.

    `[ "$elapsed" -ge "$SYNC_TIMEOUT" ]` errors on non-numeric input, which
    evaluates as false under set -e inside an if condition — the loop would
    never time out, reproducing the exact bug #496 exists to fix. The script
    must fall back to the 90s default and warn on stderr instead.
    """

    def test_non_numeric_sync_timeout_falls_back_to_default(self, git_repo):
        env = {**_CLEAN_ENV, "SYNC_TIMEOUT": "90s"}
        result = subprocess.run(
            ["bash", str(SCRIPT), BRANCH, "main"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
            env=env,
        )
        _assert_contract(result, "0")
        assert "invalid SYNC_TIMEOUT" in result.stderr, (
            f"Expected a fallback warning on stderr, got: {result.stderr!r}"
        )


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
            # --branch main: force HEAD checkout regardless of bare repo's default branch
            # (CI runners may have a bare repo whose HEAD defaults to 'master').
            ["git", "clone", "--branch", "main", str(tmp_path / "origin.git"), str(clone)],
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
        assert (
            '"' not in str(eval_cwd) and '"' not in str(SCRIPT) and '"' not in BRANCH
        ), (
            f"Path or branch contains double-quote — inline bash string will break.\n"
            f"eval_cwd={eval_cwd}, SCRIPT={SCRIPT}, BRANCH={BRANCH}"
        )

        # Capture BEFORE cd-ing to eval_cwd: the script needs a valid git cwd
        # to resolve MAIN_REPO. If we cd first, the script exits early.
        runner = (
            f'output="$(bash "{SCRIPT}" "{BRANCH}" main 2>&1)"; '
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

        assert not (eval_cwd / "FETCH_HEAD").exists(), (
            f"Stray FETCH_HEAD created in {eval_cwd} — the script's "
            f"combined stdout+stderr still contains a git tracking line that "
            f"eval parsed as a `> FETCH_HEAD` redirect."
        )
