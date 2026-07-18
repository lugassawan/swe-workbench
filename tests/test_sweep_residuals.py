"""Tests for skills/workflow-cleanup-merged/scripts/sweep-residuals.sh.

PR-scoped backstop invoked by workflow-cleanup-merged's Residual Sweep step, after
cleanup-merged has already independently verified via `gh pr view` that the PR is
MERGED. Force-removes rimba worktrees (pr-review-<N>, pr-followup-<N>,
address-feedback-<N>) and their /tmp/swe-workbench-* state-file JSON, all scoped to
one specific PR number.

Mirrors tests/test_delete_branches.py's harness conventions: real git repos built
with subprocess.run(..., env=_CLEAN_ENV), no mocking of git itself. State-file tests
use real /tmp/swe-workbench-* paths (like tests/test_clean_state_files.py) with a
unique high PR number per test to avoid cross-test / cross-run collisions.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-cleanup-merged"
    / "scripts"
    / "sweep-residuals.sh"
)

TMP = Path("/tmp")
PR_REVIEW_DIR = TMP / "swe-workbench-pr-review"
ADDR_FEEDBACK_DIR = TMP / "swe-workbench-address-feedback"


def _unique_n() -> str:
    """A large, effectively-unique PR number so /tmp fixtures never collide."""
    return str(10_000_000 + int.from_bytes(os.urandom(3), "big"))


def _run(*args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=_CLEAN_ENV,
    )


def _build_repo(base: Path) -> Path:
    """A minimal git repo (no remote needed — sweep-residuals.sh never pushes/fetches)."""
    repo = base / "main_repo"
    _run("git", "init", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _run("git", "add", "README.md", cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "branch", "-M", "main", cwd=repo)
    return repo


def _rimba_absent_env(fake_home: Path) -> dict:
    """Environment in which resolve-rimba.sh resolves to nothing.

    Strips PATH down to the directories that actually hold `git` (and basic
    system utilities), and points $HOME at an empty fixture dir so the
    `$HOME/.local/bin/rimba` / `$HOME/go/bin/rimba` fallback checks also miss —
    without this, a real rimba install on the dev machine would make the
    "rimba absent" scenario silently untestable.
    """
    git_path = shutil.which("git")
    assert git_path, "git must be resolvable to build/run test fixtures"
    git_dir = os.path.dirname(git_path)
    env = dict(_CLEAN_ENV)
    env["PATH"] = ":".join([git_dir, "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    env["HOME"] = str(fake_home)
    return env


def _run_script(repo: Path, n: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), n],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_contract(result: subprocess.CompletedProcess, swept_wt: str, swept_sf: str, residual_none: str) -> None:
    assert result.returncode == 0, (
        f"Script must always exit 0 (rc={result.returncode})\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    lines = result.stdout.strip().splitlines()
    expected = [
        f"SWEPT_WORKTREES={swept_wt}",
        f"SWEPT_STATE_FILES={swept_sf}",
        f"RESIDUAL_NONE={residual_none}",
    ]
    assert lines == expected, (
        f"Expected stdout={expected}, got {lines!r}\n"
        f"Full stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV,
    )
    return result.returncode == 0


def _cleanup_worktree(repo: Path, wt_path: Path, branch: str | None) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)],
                    cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV)
    if branch:
        subprocess.run(["git", "branch", "-D", branch],
                        cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV)
    shutil.rmtree(wt_path, ignore_errors=True)


# ── existence / syntax ───────────────────────────────────────────────────────


def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable (chmod +x)"


def test_bash_syntax_check():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, env=_CLEAN_ENV,
    )
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"


# ── reviewer worktree (pr-review-<N>): worktree + branch both reaped ────────


class TestReviewerWorktreeReaped:
    """rimba absent → fallback convention: --detach worktree at the bare-N /tmp
    path, tracking branch pr-review-<N>. Both the worktree and the branch must
    be reaped, since reviewer-flow branches are throwaway detached copies."""

    def test_pr_review_worktree_and_branch_reaped(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        branch = f"pr-review-{n}"
        wt_path = PR_REVIEW_DIR / n

        _run("git", "branch", branch, cwd=repo)
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _run("git", "worktree", "add", "--detach", str(wt_path), branch, cwd=repo)

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "1", "0", "0")
            assert not wt_path.exists(), "worktree directory must be removed"
            assert not _branch_exists(repo, branch), (
                "pr-review-<N> branch must be force-deleted (throwaway detached copy)"
            )
        finally:
            _cleanup_worktree(repo, wt_path, branch)

    def test_pr_followup_worktree_and_branch_reaped(self, tmp_path):
        """Same contract for the followup flow's bare-N `<N>-followup` fallback path."""
        repo = _build_repo(tmp_path)
        n = _unique_n()
        branch = f"pr-followup-{n}"
        wt_path = PR_REVIEW_DIR / f"{n}-followup"

        _run("git", "branch", branch, cwd=repo)
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _run("git", "worktree", "add", "--detach", str(wt_path), branch, cwd=repo)

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "1", "0", "0")
            assert not wt_path.exists()
            assert not _branch_exists(repo, branch)
        finally:
            _cleanup_worktree(repo, wt_path, branch)


# ── address-feedback worktree: worktree removed, branch preserved ───────────


class TestAddressFeedbackWorktreePreservesBranch:
    """address-feedback-<N> worktrees check out the PR's real head branch directly
    (not a synthetic label) — that branch must survive, only the worktree goes."""

    def test_address_feedback_worktree_removed_branch_kept(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        pr_head_branch = f"feature/real-pr-head-{n}"
        wt_dir = tmp_path / "wt_parent"
        wt_dir.mkdir()
        wt_path = wt_dir / f"address-feedback-{n}"

        _run("git", "branch", pr_head_branch, cwd=repo)
        _run("git", "worktree", "add", str(wt_path), pr_head_branch, cwd=repo)

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "1", "0", "0")
            assert not wt_path.exists(), "address-feedback worktree must be removed"
            assert _branch_exists(repo, pr_head_branch), (
                "address-feedback's branch is the PR's real head branch — "
                "sweep-residuals.sh must NEVER `git branch -D` it"
            )
        finally:
            _cleanup_worktree(repo, wt_path, None)
            _run("git", "branch", "-D", pr_head_branch, cwd=repo)


# ── no residual found ─────────────────────────────────────────────────────


def test_no_residual_reports_clean(tmp_path):
    repo = _build_repo(tmp_path)
    n = _unique_n()  # nothing on disk is keyed to this N
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)

    result = _run_script(repo, n, env)
    _assert_contract(result, "0", "0", "1")


# ── bad argument → clean contract, exit 0 ────────────────────────────────


@pytest.mark.parametrize("bad_arg", ["", "abc", "-5", "12.3", "12abc", "1 2", " 12"])
def test_non_integer_arg_emits_clean_contract(tmp_path, bad_arg):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)

    result = _run_script(repo, bad_arg, env)
    _assert_contract(result, "0", "0", "1")


def test_missing_arg_emits_clean_contract(tmp_path):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)

    result = subprocess.run(["bash", str(SCRIPT)], cwd=str(repo), capture_output=True, text=True, env=env)
    _assert_contract(result, "0", "0", "1")


# ── state-file reap ──────────────────────────────────────────────────────


class TestStateFileReap:
    """A unique high N so these never collide with a concurrent real invocation
    or another test run's leftovers under the shared /tmp/swe-workbench-* dirs."""

    def test_all_known_state_files_reaped(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        ADDR_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

        candidates = [
            PR_REVIEW_DIR / f"{n}.json",
            PR_REVIEW_DIR / f"{n}-followup.json",
            PR_REVIEW_DIR / f"{n}-post-threads-general.json",  # nullglob-scoped pattern
            PR_REVIEW_DIR / f"{n}-post-threads-followup.json",  # a second CALLER_TAG
            ADDR_FEEDBACK_DIR / f"{n}.json",
            ADDR_FEEDBACK_DIR / f"{n}-threads.json",
            ADDR_FEEDBACK_DIR / f"{n}-pr-comments.json",
            ADDR_FEEDBACK_DIR / f"{n}-triage.json",
        ]
        for f in candidates:
            f.write_text("{}")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", str(len(candidates)), "0")
            for f in candidates:
                assert not f.exists(), f"{f} must be reaped"
        finally:
            for f in candidates:
                f.unlink(missing_ok=True)

    def test_unrelated_n_state_files_untouched(self, tmp_path):
        """Sweeping PR N must not touch another PR's state files."""
        repo = _build_repo(tmp_path)
        n = _unique_n()
        other_n = _unique_n()
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        other_file = PR_REVIEW_DIR / f"{other_n}.json"
        other_file.write_text("{}")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "1")
            assert other_file.exists(), "an unrelated PR's state file must survive"
        finally:
            other_file.unlink(missing_ok=True)


# ── eval safety (script feeds `eval "$(...)"` per the SKILL.md wiring) ──────


def test_eval_stdout_only_does_not_create_stray_files(tmp_path):
    """Production pattern: eval "$(sweep-residuals.sh <N>)" — stdout only.

    Capture BEFORE cd-ing to a different directory (the eval/cwd trap): the
    script needs a valid git cwd to resolve MAIN_REPO, or it would exit early
    via the "could not resolve MAIN_REPO" path and under-report.
    """
    repo = _build_repo(tmp_path)
    n = _unique_n()
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)

    eval_cwd = tmp_path / "eval_cwd"
    eval_cwd.mkdir()
    (eval_cwd / "decoy").write_text("")

    assert '"' not in str(eval_cwd) and '"' not in str(SCRIPT) and '"' not in n

    runner = (
        f'output="$(bash "{SCRIPT}" "{n}")"; '
        f'cd "{eval_cwd}"; '
        f'eval "$output" 2>/dev/null || true; '
        f'echo "RESIDUAL_NONE_SEEN=$RESIDUAL_NONE"'
    )
    result = subprocess.run(
        ["bash", "-c", runner], cwd=str(repo), capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"bash runner failed:\n{result.stderr}"
    assert "RESIDUAL_NONE_SEEN=1" in result.stdout, (
        f"eval'd contract did not set RESIDUAL_NONE in the caller's shell: {result.stdout!r}"
    )

    stray = [f for f in eval_cwd.iterdir() if f.name != "decoy"]
    assert not stray, (
        f"Stray files created in {eval_cwd} via eval of the script's stdout: "
        f"{[f.name for f in stray]}"
    )
