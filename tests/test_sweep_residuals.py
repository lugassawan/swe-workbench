"""Tests for bin/swe-workbench-sweep-residuals.

PR-scoped backstop invoked by workflow-cleanup-merged's Residual Sweep step, after
cleanup-merged has already independently verified via `gh pr view` that the PR is
MERGED. Force-removes rimba worktrees (pr-review-<N>, pr-followup-<N>,
address-feedback-<N>, review-<mode>-<N> per postable specialist mode) and their
/tmp/swe-workbench-* state-file JSON, all scoped to one specific PR number.

Mirrors tests/test_delete_branches.py's harness conventions: real git repos built
with subprocess.run(..., env=_CLEAN_ENV), no mocking of git itself. State-file tests
use real /tmp/swe-workbench-* paths (like tests/test_clean_state_files.py) with a
unique high PR number per test to avoid cross-test / cross-run collisions.

The `KEY=VALUE` stdout contract was later replaced with the standard JSON envelope
(schema `swb.sweep-residuals/1`, see shared/docs/runtime-result-contract.md) —
`retained_worktrees`/`failed_removals` are now `[{path, reason}]` arrays rather than
bare counts. `_assert_contract`'s `retained_wt`/`failed` parameters still take an
expected *count* (checked against array length) so nearly every existing call site
is unchanged; a handful of dedicated tests assert the actual path/reason content.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-sweep-residuals"
REVIEW_MD = Path(__file__).parent.parent / "commands" / "review.md"

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
    """A minimal git repo (no remote needed — swe-workbench-sweep-residuals never pushes/fetches)."""
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


def _assert_contract(
    result: subprocess.CompletedProcess,
    swept_wt: str,
    swept_sf: str,
    residual_none: str,
    swept_rd: str = "0",
    swept_ssf: str = "0",
    retained_wt: str = "0",
    failed: str = "0",
) -> None:
    """`retained_wt`/`failed` are expected *counts* — checked against the length of
    the `data.retained_worktrees`/`data.failed_removals` arrays, not their content."""
    assert result.returncode == 0, (
        f"Script must always exit 0 (rc={result.returncode})\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "swb.sweep-residuals/1"
    assert payload["warnings"] == []
    expected_status = "partial" if (int(retained_wt) > 0 or int(failed) > 0) else "ok"
    assert payload["status"] == expected_status, (
        f"expected status={expected_status!r}, got {payload['status']!r}\nFull payload: {payload!r}"
    )
    data = payload["data"]
    actual = {
        "swept_worktrees": data["swept_worktrees"],
        "swept_state_files": data["swept_state_files"],
        "swept_run_dirs": data["swept_run_dirs"],
        "swept_session_files": data["swept_session_files"],
        "retained_worktrees": len(data["retained_worktrees"]),
        "failed_removals": len(data["failed_removals"]),
        "residual_none": data["residual_none"],
    }
    expected = {
        "swept_worktrees": int(swept_wt),
        "swept_state_files": int(swept_sf),
        "swept_run_dirs": int(swept_rd),
        "swept_session_files": int(swept_ssf),
        "retained_worktrees": int(retained_wt),
        "failed_removals": int(failed),
        "residual_none": bool(int(residual_none)),
    }
    assert actual == expected, (
        f"Expected data={expected}, got {actual!r}\n"
        f"Full payload: {payload!r}\nstderr: {result.stderr!r}"
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
                "swe-workbench-sweep-residuals must NEVER `git branch -D` it"
            )
        finally:
            _cleanup_worktree(repo, wt_path, None)
            _run("git", "branch", "-D", pr_head_branch, cwd=repo)


# ── dirty worktree: skipped, never force-removed ─────────────────────────


class TestDirtyWorktreeSkipped:
    """A worktree with uncommitted changes must be skipped, not force-removed.

    Interrupted flows are exactly when uncommitted, local-only work is most
    likely to exist (e.g. a killed session mid-edit, before its own commit
    step) — silently discarding it would be an unrecoverable data-loss bug.
    """

    def test_dirty_pr_review_worktree_skipped_not_removed(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        branch = f"pr-review-{n}"
        wt_path = PR_REVIEW_DIR / n

        _run("git", "branch", branch, cwd=repo)
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _run("git", "worktree", "add", "--detach", str(wt_path), branch, cwd=repo)
        (wt_path / "uncommitted.txt").write_text("local-only work\n")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            # This is the ticket's headline bug: a dirty worktree that is
            # correctly skipped (not force-removed) must still be counted —
            # RESIDUAL_NONE must NOT be 1 just because nothing was swept.
            _assert_contract(result, "0", "0", "0", retained_wt="1")
            assert wt_path.exists(), "dirty worktree must NOT be force-removed"
            assert (wt_path / "uncommitted.txt").exists(), (
                "uncommitted file must survive — this is the data-loss guard"
            )
            assert _branch_exists(repo, branch), (
                "branch must survive when its worktree is skipped as dirty"
            )
            assert "uncommitted" in result.stderr.lower() or "dirty" in result.stderr.lower(), (
                f"a dirty-skip warning must be printed to stderr, got: {result.stderr!r}"
            )
            # The actual capability gain of the envelope migration: retained_worktrees
            # carries which path and why, not just a bare count.
            retained = json.loads(result.stdout)["data"]["retained_worktrees"]
            assert retained == [{"path": str(wt_path), "reason": "1 uncommitted change(s)"}], retained
        finally:
            _cleanup_worktree(repo, wt_path, branch)


# ── FAILED_REMOVALS: a genuinely-attempted-but-failed removal is counted ────


class TestFailedRemovalCounted:
    """FAILED_REMOVALS must go nonzero when a removal is actually attempted and
    actually fails — every other test in this file only proves the counter
    stays 0 in the happy path. Denying write permission on the worktree
    directory itself makes both `git worktree remove --force` and the
    swe-workbench-clean-ephemeral fallback unable to unlink its contents
    (POSIX: removing an entry needs write+execute on its *containing*
    directory), so the directory survives both attempts — this is portable
    across Linux and macOS (no OS-specific immutable-flag mechanism needed).
    """

    def test_worktree_removal_failure_is_counted(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("permission-denial is not enforceable when running as root")

        repo = _build_repo(tmp_path)
        n = _unique_n()
        branch = f"pr-review-{n}"
        wt_path = PR_REVIEW_DIR / n

        _run("git", "branch", branch, cwd=repo)
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _run("git", "worktree", "add", "--detach", str(wt_path), branch, cwd=repo)
        os.chmod(wt_path, 0o555)

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "0", failed="1")
            assert wt_path.exists(), (
                "removal must have genuinely failed — the worktree directory "
                "must still be present on disk"
            )
            failed_removals = json.loads(result.stdout)["data"]["failed_removals"]
            assert failed_removals == [{"path": str(wt_path), "reason": "worktree removal failed"}], failed_removals
        finally:
            os.chmod(wt_path, 0o755)
            _cleanup_worktree(repo, wt_path, branch)


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


# ── Block C: run-dir orphans ─────────────────────────────────────────────


RUN_ROOT = TMP / "swe-workbench-run"


class TestRunDirOrphanReap:
    """<N>-keyed by the run-dir naming convention itself — same safety argument
    as Blocks A/B: Step 2 already proved #N is MERGED before this script runs."""

    def test_orphaned_run_dir_reaped(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        run_dir = RUN_ROOT / f"pr-review-{n}-a1b2c3"
        run_dir.mkdir()
        (run_dir / "leftover.json").write_text("{}")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "0", swept_rd="1")
            assert not run_dir.exists(), "orphaned run dir must be reaped"
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_multiple_run_dirs_for_same_pr_all_reaped(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        d1 = RUN_ROOT / f"pr-review-{n}-a1b2c3"
        d2 = RUN_ROOT / f"review-security-{n}-d4e5f6"
        d1.mkdir()
        d2.mkdir()

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "0", swept_rd="2")
            assert not d1.exists()
            assert not d2.exists()
        finally:
            shutil.rmtree(d1, ignore_errors=True)
            shutil.rmtree(d2, ignore_errors=True)

    def test_unrelated_n_run_dir_untouched(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        other_n = _unique_n()
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        other_dir = RUN_ROOT / f"pr-review-{other_n}-d4e5f6"
        other_dir.mkdir()

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "1")
            assert other_dir.exists(), "an unrelated PR's run dir must survive"
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)


# ── Block D: session scratchpad (NOT <N>-keyed — that is the point, AC4) ────


UID_ROOT = TMP / f"claude-{os.getuid()}"
FAKE_SS_PROJECT = "pytest-sweep-residuals-scratch-fixture"
FAKE_SS_SESSION_ID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"


class TestSessionScratchpadReap:
    def test_session_scratchpad_contents_reaped_directory_preserved(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        scratch = UID_ROOT / FAKE_SS_PROJECT / FAKE_SS_SESSION_ID / "scratchpad"
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "existing_commit.diff").write_text("x")
        (scratch / "pr_body.md").write_text("x")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            env["CLAUDE_CODE_SESSION_ID"] = FAKE_SS_SESSION_ID
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "0", swept_ssf="2")
            assert scratch.exists(), "the scratchpad directory itself must survive"
            assert list(scratch.iterdir()) == []
        finally:
            shutil.rmtree(UID_ROOT / FAKE_SS_PROJECT, ignore_errors=True)

    def test_no_session_id_env_is_noop(self, tmp_path):
        """CLAUDE_CODE_SESSION_ID is stripped from _CLEAN_ENV — this is the default
        environment every other test in this file already runs under."""
        repo = _build_repo(tmp_path)
        n = _unique_n()
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)

        result = _run_script(repo, n, env)
        _assert_contract(result, "0", "0", "1")


# ── specialist-review artifact coverage (PR-mode /swe-workbench:review) ─────
#
# commands/review.md's postable specialist modes each create their own
# mode-scoped preflight state file, rimba worktree label, and direct-Git
# fallback worktree — none of which the pre-fix script's allowlists knew
# about (only the Block C run-dir class was transitively covered, because its
# glob happens to also match review-<mode>-<N>-??????).

SPECIALIST_MODES = ["security", "accessibility", "dependency", "performance", "tests", "ux"]


class TestSpecialistStateFileReap:
    @pytest.mark.parametrize("mode", SPECIALIST_MODES)
    def test_specialist_state_file_reaped(self, tmp_path, mode):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        state_file = PR_REVIEW_DIR / f"{n}-review-{mode}.json"
        state_file.write_text("{}")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "1", "0")
            assert not state_file.exists(), f"{state_file} must be reaped"
        finally:
            state_file.unlink(missing_ok=True)


class TestSpecialistWorktreeReapedViaPorcelain:
    """The rimba-label path (basename == 'review-<mode>-<N>') is discoverable
    by the porcelain scan directly — no fallback-path lookup needed."""

    @pytest.mark.parametrize("mode", SPECIALIST_MODES)
    def test_specialist_worktree_and_branch_reaped(self, tmp_path, mode):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        branch = f"review-{mode}-{n}"
        wt_dir = tmp_path / "specialist_wt_parent"
        wt_dir.mkdir(exist_ok=True)
        wt_path = wt_dir / branch

        _run("git", "worktree", "add", "-b", branch, str(wt_path), cwd=repo)

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "1", "0", "0")
            assert not wt_path.exists(), "specialist worktree must be removed"
            assert not _branch_exists(repo, branch), (
                "specialist review branches are throwaway copies — must be force-deleted"
            )
        finally:
            _cleanup_worktree(repo, wt_path, branch)


class TestSpecialistDirectGitFallbackWorktreeReaped:
    """rimba-absent fallback convention (commands/review.md Step 2): the worktree
    is checked out --detach at /tmp/swe-workbench-pr-review/<mode>-<N> — its
    basename does not match the review-<mode>-<N> label, so only the fallback
    literal-path check (not the porcelain scan) can find it."""

    @pytest.mark.parametrize("mode", SPECIALIST_MODES)
    def test_specialist_fallback_worktree_and_branch_reaped(self, tmp_path, mode):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        branch = f"review-{mode}-{n}"
        wt_path = PR_REVIEW_DIR / f"{mode}-{n}"

        _run("git", "branch", branch, cwd=repo)
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _run("git", "worktree", "add", "--detach", str(wt_path), branch, cwd=repo)

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "1", "0", "0")
            assert not wt_path.exists(), "specialist fallback worktree must be removed"
            assert not _branch_exists(repo, branch)
        finally:
            _cleanup_worktree(repo, wt_path, branch)


class TestSpecialistDirtyWorktreeRetained:
    def test_dirty_specialist_worktree_retained_and_counted(self, tmp_path):
        repo = _build_repo(tmp_path)
        n = _unique_n()
        mode = "security"
        branch = f"review-{mode}-{n}"
        wt_path = PR_REVIEW_DIR / f"{mode}-{n}"

        _run("git", "branch", branch, cwd=repo)
        PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _run("git", "worktree", "add", "--detach", str(wt_path), branch, cwd=repo)
        (wt_path / "uncommitted.txt").write_text("local-only work\n")

        try:
            env = _rimba_absent_env(tmp_path / "fake_home")
            (tmp_path / "fake_home").mkdir(exist_ok=True)
            result = _run_script(repo, n, env)

            _assert_contract(result, "0", "0", "0", retained_wt="1")
            assert wt_path.exists(), "dirty specialist worktree must NOT be force-removed"
            assert _branch_exists(repo, branch)
        finally:
            _cleanup_worktree(repo, wt_path, branch)


def test_unrelated_pr_specialist_artifacts_untouched(tmp_path):
    """Sweeping PR N must not touch another PR's specialist-mode artifacts."""
    repo = _build_repo(tmp_path)
    n = _unique_n()
    other_n = _unique_n()
    mode = "ux"
    PR_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    other_state_file = PR_REVIEW_DIR / f"{other_n}-review-{mode}.json"
    other_state_file.write_text("{}")

    other_branch = f"review-{mode}-{other_n}"
    other_wt_path = PR_REVIEW_DIR / f"{mode}-{other_n}"
    _run("git", "branch", other_branch, cwd=repo)
    _run("git", "worktree", "add", "--detach", str(other_wt_path), other_branch, cwd=repo)

    try:
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        result = _run_script(repo, n, env)

        _assert_contract(result, "0", "0", "1")
        assert other_state_file.exists(), "an unrelated PR's specialist state file must survive"
        assert other_wt_path.exists(), "an unrelated PR's specialist worktree must survive"
        assert _branch_exists(repo, other_branch)
    finally:
        other_state_file.unlink(missing_ok=True)
        _cleanup_worktree(repo, other_wt_path, other_branch)


def test_specialist_modes_match_review_md_postable_list():
    """Drift guard: the script's SPECIALIST_MODES must match commands/review.md's
    postable-mode list. Adding a 7th postable mode there without updating the
    script must fail here rather than silently re-opening the coverage gap this
    ticket closed.
    """
    script_text = SCRIPT.read_text()
    match = re.search(r"SPECIALIST_MODES=\(([^)]*)\)", script_text)
    assert match, "bin/swe-workbench-sweep-residuals must declare SPECIALIST_MODES=(...)"
    script_modes = match.group(1).split()

    review_text = REVIEW_MD.read_text()
    postable_match = re.search(r"postable specialist value \(([^)]*)\)", review_text)
    assert postable_match, (
        "commands/review.md must name the postable specialist value list in parentheses"
    )
    review_modes = [m.strip() for m in postable_match.group(1).split(",")]

    assert script_modes == review_modes, (
        f"SPECIALIST_MODES={script_modes} in bin/swe-workbench-sweep-residuals must match "
        f"commands/review.md's postable specialist list {review_modes}"
    )


# ── envelope round-trip (replaces the old eval-safety test class; production pattern
#    is now RESULT=$(sweep-residuals <N> | result-check swb.sweep-residuals/1) || exit 1) ──


def test_envelope_round_trips_through_result_check(tmp_path):
    """stdout must be a bare JSON envelope — no `eval`-able KEY=VALUE lines, and it
    must validate cleanly against the checker's registered schema."""
    repo = _build_repo(tmp_path)
    n = _unique_n()
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)

    result = _run_script(repo, n, env)
    assert result.returncode == 0, result.stderr

    checker = ROOT / "bin" / "swe-workbench-result-check"
    checked = subprocess.run(
        [sys.executable, str(checker), "swb.sweep-residuals/1"],
        input=result.stdout, capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == json.loads(result.stdout)


def test_stdout_contains_no_eval_able_key_value_lines(tmp_path):
    """Regression lock for the migration itself — a stray `KEY=VALUE` line surviving
    in stdout would silently re-open the eval-injection hazard this ticket closes."""
    repo = _build_repo(tmp_path)
    n = _unique_n()
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)

    result = _run_script(repo, n, env)
    assert result.returncode == 0, result.stderr
    assert not re.search(r"^[A-Z_]+=", result.stdout, re.MULTILINE), (
        f"stdout must be a bare JSON envelope, no shell KEY=VALUE lines: {result.stdout!r}"
    )
