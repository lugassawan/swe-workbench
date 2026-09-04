"""Tests for bin/swe-workbench-address-feedback-worktree.

Extracts workflow-address-feedback's Phase 2 worktree acquire/reconcile/release
lifecycle out of SKILL.md prose into a directly-testable bash runtime command.

Mirrors tests/test_sweep_residuals.py's harness conventions: real git repos built
with subprocess.run(..., env=_CLEAN_ENV), no mocking of git itself. `_rimba_absent_env`
strips PATH/HOME so the shared resolve-rimba.sh helper resolves to nothing, letting
the git-fallback paths be tested deterministically regardless of whether the dev
machine has rimba installed.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-address-feedback-worktree"
STATE_DIR = Path("/tmp/swe-workbench-address-feedback")


def _unique_n() -> str:
    return str(10_000_000 + int.from_bytes(os.urandom(3), "big"))


def _run(*args, cwd, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True,
        env=dict(_CLEAN_ENV) if env is None else env,
    )


def _rimba_absent_env(fake_home: Path) -> dict:
    """Environment in which resolve-rimba.sh resolves to nothing — see
    test_sweep_residuals.py's identical helper for the full rationale."""
    git_path = shutil.which("git")
    assert git_path, "git must be resolvable to build/run test fixtures"
    git_dir = os.path.dirname(git_path)
    jq_path = shutil.which("jq")
    assert jq_path, "jq must be resolvable to run the script under test"
    jq_dir = os.path.dirname(jq_path)
    env = dict(_CLEAN_ENV)
    env["PATH"] = ":".join(dict.fromkeys([git_dir, jq_dir, "/usr/bin", "/bin", "/usr/sbin", "/sbin"]))
    env["HOME"] = str(fake_home)
    fake_home.mkdir(parents=True, exist_ok=True)
    return env


def _build_remote_and_clone(base: Path, pr_branch: str) -> tuple[Path, Path]:
    """A bare 'origin' remote plus a clone (the acquire caller's cwd) with
    `pr_branch` pushed to origin but NOT checked out locally in the clone."""
    remote = base / "origin.git"
    # -b main (not just the later `branch -M main` on the seed repo) — the bare
    # repo's own HEAD symref is set once at `init --bare` time and never moves when
    # something is later pushed to a *different*-named branch. Without an explicit
    # -b here, a CI runner with no ~/.gitconfig init.defaultBranch (unlike a dev
    # machine that commonly has one) leaves HEAD pointing at refs/heads/master —
    # a ref that's never created — and `git clone` then fails to check out
    # anything ("remote HEAD refers to nonexistent ref"), leaving `clone` on an
    # unborn branch with no local `main` at all, only `origin/main`.
    _run("git", "init", "--bare", "-b", "main", str(remote), cwd=base)

    seed = base / "seed"
    _run("git", "init", "-b", "main", str(seed), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=seed)
    _run("git", "config", "user.name", "Test", cwd=seed)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=seed)
    (seed / "README.md").write_text("hello\n")
    _run("git", "add", "README.md", cwd=seed)
    _run("git", "commit", "-m", "init", cwd=seed)
    _run("git", "branch", "-M", "main", cwd=seed)
    _run("git", "remote", "add", "origin", str(remote), cwd=seed)
    _run("git", "push", "origin", "main", cwd=seed)

    _run("git", "checkout", "-b", pr_branch, cwd=seed)
    (seed / "feature.txt").write_text("feature work\n")
    _run("git", "add", "feature.txt", cwd=seed)
    _run("git", "commit", "-m", "feature commit", cwd=seed)
    _run("git", "push", "origin", pr_branch, cwd=seed)
    _run("git", "checkout", "main", cwd=seed)
    _run("git", "branch", "-D", pr_branch, cwd=seed)

    clone = base / "clone"
    _run("git", "clone", str(remote), str(clone), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=clone)
    _run("git", "config", "user.name", "Test", cwd=clone)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=clone)
    return remote, clone


def _run_acquire(cwd: Path, pr: str, branch: str, env: dict, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), "acquire", "--pr", pr, "--branch", branch, *(extra_args or [])],
        cwd=str(cwd), capture_output=True, text=True, env=env,
    )


def _run_release(cwd: Path, pr: str, path: str, branch: str, created: str, env: dict, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), "release", "--pr", pr, "--path", path, "--branch", branch, "--created", created, *(extra_args or [])],
        cwd=str(cwd), capture_output=True, text=True, env=env,
    )


def _cleanup_state_files(pr: str, slug: str = "") -> None:
    stem = f"{slug}-{pr}" if slug else pr
    for name in (f"{pr}-worktree.json", f"{stem}-worktree.json"):
        (STATE_DIR / name).unlink(missing_ok=True)


def _cleanup_worktree(repo: Path, wt_path, branch: str | None) -> None:
    if wt_path is not None:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)],
                        cwd=str(repo), capture_output=True, text=True, env=dict(_CLEAN_ENV))
        shutil.rmtree(wt_path, ignore_errors=True)
    if branch:
        subprocess.run(["git", "branch", "-D", branch],
                        cwd=str(repo), capture_output=True, text=True, env=dict(_CLEAN_ENV))


def _branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo), capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    return result.returncode == 0


# ── existence / syntax ───────────────────────────────────────────────────────


def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable (chmod +x)"


def test_bash_syntax_check():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"


# ── CLI validation ───────────────────────────────────────────────────────────


def test_no_args_exits_nonzero_with_usage():
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0
    assert "Usage" in result.stderr


def test_unknown_subcommand_exits_nonzero():
    result = subprocess.run([str(SCRIPT), "bogus"], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0


def test_acquire_missing_pr_exits_nonzero():
    result = subprocess.run([str(SCRIPT), "acquire", "--branch", "x"], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0


def test_acquire_missing_branch_exits_nonzero():
    result = subprocess.run([str(SCRIPT), "acquire", "--pr", "1"], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0


def test_acquire_non_integer_pr_exits_nonzero():
    result = subprocess.run(
        [str(SCRIPT), "acquire", "--pr", "abc", "--branch", "x"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0


def test_release_missing_created_flag_exits_nonzero():
    """--created is required; a missing flag must never silently default (fail-dangerous)."""
    result = subprocess.run(
        [str(SCRIPT), "release", "--pr", "1", "--path", "/tmp/x", "--branch", "b"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0


def test_release_missing_path_exits_nonzero():
    result = subprocess.run(
        [str(SCRIPT), "release", "--pr", "1", "--branch", "b", "--created", "true"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0


def test_release_relative_path_exits_nonzero():
    result = subprocess.run(
        [str(SCRIPT), "release", "--pr", "1", "--path", "relative/x", "--branch", "b", "--created", "true"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0


def test_release_invalid_created_value_exits_nonzero():
    result = subprocess.run(
        [str(SCRIPT), "release", "--pr", "1", "--path", "/tmp/x", "--branch", "b", "--created", "yes"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0


# ── acquire: reuse-current ────────────────────────────────────────────────────


class TestAcquireReuseCurrent:
    def test_reuses_cwd_when_already_on_pr_branch(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        _run("git", "checkout", "-b", branch, f"origin/{branch}", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["schema"] == "swb.address-feedback-worktree-acquire/1"
            assert payload["data"]["reused"] is True
            assert payload["data"]["reuse_reason"] == "current-worktree"
            assert payload["data"]["path"] == str(clone)
        finally:
            _cleanup_state_files(pr)


# ── acquire: reuse-existing ───────────────────────────────────────────────────


class TestAcquireReuseExisting:
    def test_reuses_worktree_registered_elsewhere(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        other_wt = tmp_path / "other_wt"
        _run("git", "worktree", "add", str(other_wt), "-b", branch, f"origin/{branch}", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["reused"] is True
            assert payload["data"]["reuse_reason"] == "existing-worktree"
            assert payload["data"]["path"] == str(other_wt)
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, other_wt, None)


# ── acquire: stale / interrupted-run (local branch exists, no worktree yet) ──


class TestAcquireInterruptedRun:
    def test_checks_out_existing_local_branch_instead_of_recreating(self, tmp_path):
        """A local branch left behind by a prior crashed run's release step must be
        checked out (preserving unpushed crash-recovery commits), not re-created."""
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        _run("git", "branch", branch, f"origin/{branch}", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        result = None
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["reused"] is False
            assert payload["data"]["reuse_reason"] == "created-git"
            wt_path = Path(payload["data"]["path"])
            assert wt_path.is_dir()
            assert (wt_path / "feature.txt").exists()
        finally:
            _cleanup_state_files(pr)
            if result is not None:
                try:
                    wt_path = Path(json.loads(result.stdout)["data"]["path"])
                    _cleanup_worktree(clone, wt_path, branch)
                except Exception:
                    pass


# ── acquire: fresh create, rimba absent (ultimate git fallback) ──────────────


class TestAcquireFreshCreateGitFallback:
    def test_creates_worktree_via_git_fallback_when_rimba_absent(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)

        env = _rimba_absent_env(tmp_path / "fake_home")
        result = None
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["reused"] is False
            assert payload["data"]["reuse_reason"] == "created-git"
            wt_path = Path(payload["data"]["path"])
            assert wt_path.is_dir()
            assert (wt_path / "feature.txt").exists()
            branch_out = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, env=dict(_CLEAN_ENV),
            ).stdout.strip()
            assert branch_out == branch
            receipt = json.loads((STATE_DIR / f"{pr}-worktree.json").read_text())
            assert receipt["created"] is True
            assert receipt["branch"] == branch
        finally:
            _cleanup_state_files(pr)
            if result is not None:
                try:
                    wt_path = Path(json.loads(result.stdout)["data"]["path"])
                    _cleanup_worktree(clone, wt_path, branch)
                except Exception:
                    pass


# ── acquire: fork PR (fetch fails) ────────────────────────────────────────────


class TestAcquireForkPrFetchFails:
    def test_fetch_failure_warns_and_skips_reconcile_without_crashing(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        # A branch that exists locally but was never pushed to origin — mirrors a fork
        # PR where `git fetch origin "$PR_BRANCH"` fails because the branch only exists
        # on the fork's remote, not "origin".
        fork_branch = f"fork-branch-{pr}"
        _run("git", "checkout", "-b", fork_branch, "main", cwd=clone)
        (clone / "fork.txt").write_text("fork work\n")
        _run("git", "add", "fork.txt", cwd=clone)
        _run("git", "commit", "-m", "fork commit", cwd=clone)
        _run("git", "checkout", "main", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        result = None
        try:
            result = _run_acquire(clone, pr, fork_branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "partial"
            codes = {w["code"] for w in payload["warnings"]}
            assert "fetch-failed" in codes
            assert payload["data"]["diverged"] is False
        finally:
            _cleanup_state_files(pr)
            if result is not None:
                try:
                    wt_path = Path(json.loads(result.stdout)["data"]["path"])
                    if wt_path != clone:
                        _cleanup_worktree(clone, wt_path, None)
                except Exception:
                    pass
            _run("git", "branch", "-D", fork_branch, cwd=clone)


class TestAcquireBothCreatePathsFail:
    def test_no_local_branch_and_no_origin_ref_fails_loudly_not_silently(self, tmp_path):
        """Regression test: when the branch exists neither locally nor on origin (a
        typo'd branch name, or a fork PR whose branch was force-deleted upstream
        mid-flow), BOTH create-path attempts — `git worktree add -b ... "origin/$PR_BRANCH"`
        and the bare `git worktree add "$WT" "$PR_BRANCH"` fallback — fail. Under
        set -e, a command that is the last member of an `if`'s then-block is not
        exempt from errexit, so an unguarded second attempt would abort the whole
        script silently instead of reaching the documented `[ -e "$WT/.git" ]`
        diagnostic — this must still exit 1 with a loud stderr message."""
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        nonexistent_branch = f"never-existed-{pr}"

        env = _rimba_absent_env(tmp_path / "fake_home")
        result = _run_acquire(clone, pr, nonexistent_branch, env)
        assert result.returncode == 1, (
            f"expected a loud exit 1, got {result.returncode} "
            f"(stdout={result.stdout!r}, stderr={result.stderr!r})"
        )
        assert result.stdout == "", "a hard failure must never emit a (possibly stale) envelope on stdout"
        assert result.stderr.strip() != "", (
            "a hard failure must print an actionable diagnostic to stderr, not fail silently"
        )
        assert "worktree creation failed" in result.stderr


# ── acquire: divergent local vs origin ────────────────────────────────────────


class TestAcquireDivergent:
    def test_diverged_branch_warns_without_forcing_rebase(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        # Local branch with a commit NOT on origin, and origin has moved on too:
        # build local divergence by branching from origin then committing locally,
        # while a second push on origin from the seed advances origin/branch further.
        _run("git", "branch", branch, f"origin/{branch}", cwd=clone)
        wt = tmp_path / "diverge_wt"
        _run("git", "worktree", "add", str(wt), branch, cwd=clone)
        (wt / "local-only.txt").write_text("local\n")
        _run("git", "add", "local-only.txt", cwd=wt)
        _run("git", "commit", "-m", "local-only commit", cwd=wt)
        _run("git", "worktree", "remove", "--force", str(wt), cwd=clone)

        seed = tmp_path / "seed"
        _run("git", "checkout", branch, cwd=seed)
        (seed / "origin-only.txt").write_text("origin\n")
        _run("git", "add", "origin-only.txt", cwd=seed)
        _run("git", "commit", "-m", "origin-only commit", cwd=seed)
        _run("git", "push", "origin", branch, cwd=seed)

        env = _rimba_absent_env(tmp_path / "fake_home")
        result = None
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["diverged"] is True
            codes = {w["code"] for w in payload["warnings"]}
            assert "branch-diverged" in codes
            wt_path = Path(payload["data"]["path"])
            log = subprocess.run(
                ["git", "-C", str(wt_path), "log", "--oneline", "-1"],
                capture_output=True, text=True, env=dict(_CLEAN_ENV),
            ).stdout
            assert "local-only" in log, "diverged branch must NOT be force-rebased/overwritten"
        finally:
            _cleanup_state_files(pr)
            if result is not None:
                try:
                    wt_path = Path(json.loads(result.stdout)["data"]["path"])
                    _cleanup_worktree(clone, wt_path, branch)
                except Exception:
                    pass


# ── acquire: dirty reuse path ─────────────────────────────────────────────────


class TestAcquireDirtyReuse:
    def test_dirty_current_worktree_reports_dirty_non_blocking(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        _run("git", "checkout", "-b", branch, f"origin/{branch}", cwd=clone)
        (clone / "uncommitted.txt").write_text("wip\n")

        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["dirty"] is True
            assert payload["status"] in ("ok", "partial")
        finally:
            _cleanup_state_files(pr)
            (clone / "uncommitted.txt").unlink(missing_ok=True)


# ── acquire: rimba re-prefix teardown (rimba present, stubbed) ───────────────


def _write_rimba_stub(bin_dir: Path, *, reprefix_branch: str) -> Path:
    """A stub `rimba` executable simulating rimba re-prefixing a non-conventional
    branch name — `add` creates a worktree on `reprefix_branch` instead of the
    requested task name, mirroring rimba's DefaultPrefixType=feature/ behavior."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "rimba"
    wt_dir_name = reprefix_branch.split("/", 1)[-1]
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "$1" = "add" ]; then\n'
        "  src=\"\"\n"
        "  shift 2\n"
        "  while [ $# -gt 0 ]; do\n"
        '    case "$1" in\n'
        '      --source) src="$2"; shift 2 ;;\n'
        "      *) shift ;;\n"
        "    esac\n"
        "  done\n"
        f'  wt="$RIMBA_STUB_WT_DIR/{wt_dir_name}"\n'
        f'  git worktree add -b "{reprefix_branch}" "$wt" "$src" >&2\n'
        '  echo "Path:   $wt"\n'
        "  exit 0\n"
        'elif [ "$1" = "remove" ]; then\n'
        "  exit 0\n"
        'elif [ "$1" = "deps" ]; then\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    stub.write_text(script)
    stub.chmod(0o755)
    return stub


class TestAcquireRimbaReprefixTeardown:
    def test_reprefixed_worktree_torn_down_and_falls_back_to_git(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)

        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        stub_dir = fake_home / ".local" / "bin"
        reprefixed = f"feature/{branch}"
        _write_rimba_stub(stub_dir, reprefix_branch=reprefixed)

        env = _rimba_absent_env(fake_home)
        env["HOME"] = str(fake_home)
        env["RIMBA_STUB_WT_DIR"] = str(tmp_path / "rimba_stub_wts")
        (tmp_path / "rimba_stub_wts").mkdir()

        result = None
        try:
            result = _run_acquire(clone, pr, branch, env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            # torn down + fell through to the git fallback, never left on the
            # rimba-fabricated feature/<name> branch.
            assert payload["data"]["reuse_reason"] == "created-git"
            assert payload["data"]["branch"] == branch
            wt_path = Path(payload["data"]["path"])
            branch_out = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, env=dict(_CLEAN_ENV),
            ).stdout.strip()
            assert branch_out == branch
            assert not _branch_exists(clone, reprefixed), (
                "the rimba-fabricated feature/<name> branch must be torn down, "
                "never left behind"
            )
        finally:
            _cleanup_state_files(pr)
            if result is not None:
                try:
                    wt_path = Path(json.loads(result.stdout)["data"]["path"])
                    _cleanup_worktree(clone, wt_path, branch)
                except Exception:
                    pass


# ── release ────────────────────────────────────────────────────────────────


class TestReleaseCreatedFalseIsNoop:
    def test_created_false_removes_nothing_exits_zero(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        wt = tmp_path / "some_wt"
        _run("git", "worktree", "add", str(wt), "-b", branch, "main", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            result = _run_release(clone, pr, str(wt), branch, "false", env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "ok"
            assert payload["data"]["removed"] is False
            assert payload["data"]["method"] == "skipped-not-created"
            assert payload["data"]["branch_preserved"] is True
            assert wt.exists(), "a --created false release must not touch the worktree"
            assert _branch_exists(clone, branch)
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, wt, branch)


class TestReleaseCreatedTrueRemoves:
    def test_full_acquire_then_release_removes_worktree_keeps_branch(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)

        env = _rimba_absent_env(tmp_path / "fake_home")
        acquire_result = _run_acquire(clone, pr, branch, env)
        assert acquire_result.returncode == 0, acquire_result.stderr
        acquire_payload = json.loads(acquire_result.stdout)
        wt_path = acquire_payload["data"]["path"]

        try:
            release_result = _run_release(clone, pr, wt_path, branch, "true", env)
            assert release_result.returncode == 0, release_result.stderr
            release_payload = json.loads(release_result.stdout)
            assert release_payload["status"] == "ok"
            assert release_payload["data"]["removed"] is True
            assert release_payload["data"]["method"] == "git-worktree-remove"
            assert release_payload["data"]["branch_preserved"] is True
            assert not Path(wt_path).exists(), "the worktree directory must be removed"
            assert _branch_exists(clone, branch), (
                "release must NEVER delete $PR_BRANCH — it is the owner's real PR head branch"
            )
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, Path(wt_path), branch)


class TestReleaseAgainstAlreadyGoneWorktree:
    def test_release_succeeds_when_path_already_removed_out_of_band(self, tmp_path):
        """Regression test: a $WPATH that no longer exists at release time (e.g. a
        duplicate/second release call, or removed by something other than this
        script) must not turn the exists_after branch-existence check into a false
        "not a git repository" failure — which would misreport $PR_BRANCH as
        destroyed and abort with a FATAL that has nothing to do with reality."""
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)

        env = _rimba_absent_env(tmp_path / "fake_home")
        acquire_result = _run_acquire(clone, pr, branch, env)
        assert acquire_result.returncode == 0, acquire_result.stderr
        wt_path = Path(json.loads(acquire_result.stdout)["data"]["path"])

        # Remove the worktree out-of-band (not via this script) so its git-common-dir
        # can no longer be resolved from $WPATH, forcing _main_repo_root_for to fail
        # and release onto the SAFE_DIR fallback path this test exists to cover.
        shutil.rmtree(wt_path, ignore_errors=True)

        try:
            result = _run_release(clone, pr, str(wt_path), branch, "true", env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["branch_preserved"] is True
            assert _branch_exists(clone, branch), (
                "the branch must still exist — it was never touched, only the "
                "already-gone worktree directory was 'released'"
            )
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, wt_path, branch)


def _write_git_worktree_remove_fails_stub(bin_dir: Path, *, real_git: str) -> Path:
    """A stub `git` that fails only `worktree remove ...` invocations (both the
    single- and double---force retry, and both with and without a leading
    `-C <dir>` — do_release always passes an explicit -C), delegating every other
    subcommand — branch checks, show-ref, rev-parse, git-common-dir resolution — to
    the real git unchanged. Isolates the release chain's fallback to
    swe-workbench-clean-ephemeral without needing to corrupt real worktree/repo
    state (which entangles with the branch-verification and receipt checks that
    must still pass normally)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "git"
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "args=(\"$@\")\n"
        # Strip a leading -C <dir> pair, if present, before checking the subcommand.
        'if [ "${args[0]:-}" = "-C" ]; then\n'
        "  args=(\"${args[@]:2}\")\n"
        "fi\n"
        'if [ "${args[0]:-}" = "worktree" ] && [ "${args[1]:-}" = "remove" ]; then\n'
        "  exit 1\n"
        "fi\n"
        f'exec "{real_git}" "$@"\n'
    )
    stub.write_text(script)
    stub.chmod(0o755)
    return stub


class TestReleaseCleanEphemeralFallback:
    def test_falls_back_to_clean_ephemeral_when_git_worktree_remove_fails(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)

        env = _rimba_absent_env(tmp_path / "fake_home")
        acquire_result = _run_acquire(clone, pr, branch, env)
        assert acquire_result.returncode == 0, acquire_result.stderr
        wt_path = Path(json.loads(acquire_result.stdout)["data"]["path"])

        real_git = shutil.which("git")
        assert real_git, "git must be resolvable to build the stub"
        stub_dir = tmp_path / "git_stub_bin"
        _write_git_worktree_remove_fails_stub(stub_dir, real_git=real_git)
        stub_env = dict(env)
        stub_env["PATH"] = f"{stub_dir}:{env['PATH']}"

        try:
            result = _run_release(clone, pr, str(wt_path), branch, "true", stub_env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["data"]["removed"] is True
            assert payload["data"]["method"] == "clean-ephemeral"
            assert payload["data"]["branch_preserved"] is True
            assert not wt_path.exists()
            assert _branch_exists(clone, branch), (
                "release must NEVER delete $PR_BRANCH, even on the clean-ephemeral fallback path"
            )
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, wt_path, branch)


class TestReleaseReceiptMismatchRefused:
    def test_release_refuses_when_no_matching_receipt(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        wt = tmp_path / "unowned_wt"
        _run("git", "worktree", "add", str(wt), "-b", branch, "main", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            # No acquire call ran for this PR — no receipt exists.
            result = _run_release(clone, pr, str(wt), branch, "true", env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "partial"
            codes = {w["code"] for w in payload["warnings"]}
            assert "receipt-mismatch" in codes
            assert payload["data"]["removed"] is False
            assert wt.exists(), "a release with no matching receipt must not remove anything"
            assert _branch_exists(clone, branch)
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, wt, branch)

    def test_release_refuses_when_path_does_not_match_receipt(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)

        env = _rimba_absent_env(tmp_path / "fake_home")
        acquire_result = _run_acquire(clone, pr, branch, env)
        assert acquire_result.returncode == 0, acquire_result.stderr
        real_wt_path = json.loads(acquire_result.stdout)["data"]["path"]

        decoy_wt = tmp_path / "decoy_wt"
        decoy_branch = f"decoy-branch-{pr}"
        _run("git", "worktree", "add", str(decoy_wt), "-b", decoy_branch, "main", cwd=clone)

        try:
            result = _run_release(clone, pr, str(decoy_wt), decoy_branch, "true", env)
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "partial"
            codes = {w["code"] for w in payload["warnings"]}
            assert "receipt-mismatch" in codes
            assert decoy_wt.exists(), "a path not matching the receipt must never be removed"
        finally:
            _cleanup_state_files(pr)
            _cleanup_worktree(clone, Path(real_wt_path), branch)
            _cleanup_worktree(clone, decoy_wt, decoy_branch)


# ── branch survives every removal path ────────────────────────────────────────


def test_branch_survives_receipt_ok_but_branch_mismatch(tmp_path):
    """A worktree whose checked-out branch no longer matches --branch (e.g. someone
    manually switched it) must be refused, not removed."""
    pr = _unique_n()
    branch = f"pr-branch-{pr}"
    _remote, clone = _build_remote_and_clone(tmp_path, branch)

    env = _rimba_absent_env(tmp_path / "fake_home")
    acquire_result = _run_acquire(clone, pr, branch, env)
    assert acquire_result.returncode == 0, acquire_result.stderr
    wt_path = Path(json.loads(acquire_result.stdout)["data"]["path"])

    other_branch = f"other-branch-{pr}"
    _run("git", "checkout", "-b", other_branch, cwd=wt_path)

    try:
        result = _run_release(clone, pr, str(wt_path), branch, "true", env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "partial"
        codes = {w["code"] for w in payload["warnings"]}
        assert "branch-mismatch" in codes
        assert wt_path.exists(), "a worktree whose branch no longer matches must not be removed"
    finally:
        _cleanup_state_files(pr)
        _cleanup_worktree(clone, wt_path, branch)
        _run("git", "branch", "-D", other_branch, cwd=clone)


# ── source-level ratchet: release never issues a branch-delete or branch-keyed removal ──


def test_release_region_never_deletes_branches_or_uses_rimba_remove():
    """Static guard for design decision 5.4: the release codepath must be provably
    path-keyed, not just "we didn't happen to write branch-deletion code" — grep the
    do_release function body specifically, not the whole file (do_acquire legitimately
    tears down a rimba-fabricated junk branch during the re-prefix rollback)."""
    text = SCRIPT.read_text()
    start = text.index("do_release() {")
    end = text.index("\n[ $# -ge 1 ] || usage")
    release_body = text[start:end]
    assert "git branch -d" not in release_body.lower(), (
        "do_release must never delete a branch — $PR_BRANCH is the owner's real PR head"
    )
    assert "rimba remove" not in release_body, (
        "do_release must never call rimba remove — it is branch-keyed and can hit a "
        "different concurrent session's live worktree on the same branch"
    )


# ── release cwd-inside-target case ────────────────────────────────────────────


def test_release_succeeds_when_invoked_with_cwd_inside_target(tmp_path):
    """The caller (the skill) may still be cwd'd inside the worktree being released —
    release must hop to the main repo root before attempting removal rather than
    failing to remove its own cwd."""
    pr = _unique_n()
    branch = f"pr-branch-{pr}"
    _remote, clone = _build_remote_and_clone(tmp_path, branch)

    env = _rimba_absent_env(tmp_path / "fake_home")
    acquire_result = _run_acquire(clone, pr, branch, env)
    assert acquire_result.returncode == 0, acquire_result.stderr
    wt_path = Path(json.loads(acquire_result.stdout)["data"]["path"])

    try:
        result = _run_release(wt_path, pr, str(wt_path), branch, "true", env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["data"]["removed"] is True
        assert not wt_path.exists()
        assert _branch_exists(clone, branch)
    finally:
        _cleanup_state_files(pr)
        _cleanup_worktree(clone, wt_path, branch)


# ── envelope round-trip through swe-workbench-result-check ───────────────────


def test_acquire_envelope_round_trips_through_result_check(tmp_path):
    pr = _unique_n()
    branch = f"pr-branch-{pr}"
    _remote, clone = _build_remote_and_clone(tmp_path, branch)
    env = _rimba_absent_env(tmp_path / "fake_home")

    result = None
    try:
        result = _run_acquire(clone, pr, branch, env)
        assert result.returncode == 0, result.stderr
        checker = ROOT / "bin" / "swe-workbench-result-check"
        checked = subprocess.run(
            ["python3", str(checker), "swb.address-feedback-worktree-acquire/1"],
            input=result.stdout, capture_output=True, text=True, env=dict(_CLEAN_ENV),
        )
        assert checked.returncode == 0, checked.stderr
    finally:
        _cleanup_state_files(pr)
        if result is not None:
            try:
                wt_path = Path(json.loads(result.stdout)["data"]["path"])
                _cleanup_worktree(clone, wt_path, branch)
            except Exception:
                pass


def test_release_envelope_round_trips_through_result_check(tmp_path):
    pr = _unique_n()
    branch = f"pr-branch-{pr}"
    _remote, clone = _build_remote_and_clone(tmp_path, branch)
    env = _rimba_absent_env(tmp_path / "fake_home")
    wt = tmp_path / "rt_wt"
    _run("git", "worktree", "add", str(wt), "-b", branch, "main", cwd=clone)

    try:
        result = _run_release(clone, pr, str(wt), branch, "false", env)
        assert result.returncode == 0, result.stderr
        checker = ROOT / "bin" / "swe-workbench-result-check"
        checked = subprocess.run(
            ["python3", str(checker), "swb.address-feedback-worktree-release/1"],
            input=result.stdout, capture_output=True, text=True, env=dict(_CLEAN_ENV),
        )
        assert checked.returncode == 0, checked.stderr
    finally:
        _cleanup_state_files(pr)
        _cleanup_worktree(clone, wt, branch)


# ── Repo-scoped receipts ────────────────────────────────────────


class TestRepoScopedReceipts:
    def test_acquire_with_repo_writes_slugged_receipt(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        _run("git", "checkout", "-b", branch, "origin/" + branch, cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            result = _run_acquire(clone, pr, branch, env, extra_args=["--repo", "octocat/widgets"])
            assert result.returncode == 0, result.stderr
            slugged = STATE_DIR / f"octocat-widgets-{pr}-worktree.json"
            legacy = STATE_DIR / f"{pr}-worktree.json"
            assert slugged.exists(), "acquire --repo must write the slugged receipt"
            assert not legacy.exists(), "acquire --repo must not write the legacy receipt"
        finally:
            _cleanup_state_files(pr, slug="octocat-widgets")

    def test_acquire_rejects_invalid_repo_value(self, tmp_path):
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        env = _rimba_absent_env(tmp_path / "fake_home")
        try:
            result = _run_acquire(clone, pr, branch, env, extra_args=["--repo", "bogus"])
            assert result.returncode != 0
            assert "invalid --repo" in result.stderr
        finally:
            _cleanup_state_files(pr)

    def test_release_dual_reads_legacy_receipt(self, tmp_path):
        """Pre-upgrade acquire (legacy receipt) / post-upgrade release (--repo
        given, slugged receipt absent): the legacy receipt must still satisfy
        ownership so release does not refuse. Uses created=true — the only path
        that actually consults the receipt."""
        pr = _unique_n()
        branch = f"pr-branch-{pr}"
        _remote, clone = _build_remote_and_clone(tmp_path, branch)
        _run("git", "fetch", "origin", branch, cwd=clone)
        _run("git", "branch", branch, f"origin/{branch}", cwd=clone)

        env = _rimba_absent_env(tmp_path / "fake_home")
        acquired = None
        try:
            acquired = _run_acquire(clone, pr, branch, env, extra_args=["--repo", "octocat/widgets"])
            assert acquired.returncode == 0, acquired.stderr
            payload = json.loads(acquired.stdout)
            assert payload["data"]["reused"] is False, payload
            assert payload["data"]["reuse_reason"] == "created-git", payload
            wt_path = Path(payload["data"]["path"])
            # Simulate the pre-upgrade receipt spelling.
            slugged = STATE_DIR / f"octocat-widgets-{pr}-worktree.json"
            legacy = STATE_DIR / f"{pr}-worktree.json"
            assert slugged.exists()
            slugged.rename(legacy)

            released = _run_release(clone, pr, str(wt_path), branch, "true", env,
                                    extra_args=["--repo", "octocat/widgets"])
            assert released.returncode == 0, released.stderr
            rpayload = json.loads(released.stdout)
            assert rpayload["status"] == "ok", rpayload
            assert not wt_path.exists()
        finally:
            _cleanup_state_files(pr, slug="octocat-widgets")
            if acquired is not None:
                try:
                    wt_path = Path(json.loads(acquired.stdout)["data"]["path"])
                    _cleanup_worktree(clone, wt_path, branch)
                except Exception:
                    pass
