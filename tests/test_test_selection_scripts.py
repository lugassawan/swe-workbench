"""Tests for scripts/select-tests.sh, scripts/test-all.sh and their use by .githooks/pre-push.

The pre-push gate must stay short: git holds the push connection idle while it runs, and
GitHub drops an idle SSH session after ~6 minutes, so the gate runs only the tests that
cover the pushed change. These tests pin that selection, the polite runner, and the wiring.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SELECT = ROOT / "scripts" / "select-tests.sh"
TEST_ALL = ROOT / "scripts" / "test-all.sh"
PRE_PUSH = ROOT / ".githooks" / "pre-push"
ZERO = "0" * 40


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, env=dict(_CLEAN_ENV), capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def _write(repo: Path, rel: str, text: str = "") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """A small repo on `main` whose tests mention the files they cover."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, "scripts/alpha.sh", "#!/bin/bash\necho alpha\n")
    _write(root, "tests/test_alpha.py", "# covers alpha.sh\n")
    _write(root, "bin/beta-tool", "#!/bin/bash\n")
    _write(root, "tests/test_beta.py", "# covers beta-tool\n")
    _write(root, "skills/gamma/SKILL.md", "# gamma\n")
    _write(root, "tests/test_gamma.py", "# covers the gamma skill\n")
    _write(root, "docs/README.md", "# docs\n")
    _write(root, "tests/test_docs.py", "# reads docs/README.md\n")
    _write(root, "scripts/zed.py", "VALUE = 1\n")
    _write(root, "tests/test_zed.py", "import zed\n")
    _write(root, "tests/conftest.py", "")
    _write(root, "notes.txt", "unrelated\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "switch", "-q", "-c", "feature")
    return root


def _commit(repo: Path, *paths: str, text: str = "changed\n", delete: bool = False) -> str:
    for rel in paths:
        if delete:
            _git(repo, "rm", "-q", rel)
        elif rel.endswith(".sh") or rel.startswith("bin/"):
            _write(repo, rel, "#!/bin/bash\necho changed\n")  # the hook shellchecks these
        else:
            _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    return _git(repo, "rev-parse", "HEAD")


def _select(repo: Path, *args: str):
    return subprocess.run(
        ["bash", str(SELECT), *args],
        cwd=repo, env=dict(_CLEAN_ENV), capture_output=True, text=True,
    )  # fmt: skip


def _selected(repo: Path, *args: str) -> list[str]:
    done = _select(repo, *args)
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


class TestSelectTests:
    def test_changed_source_selects_the_tests_that_mention_it(self, repo):
        _commit(repo, "scripts/alpha.sh")
        assert _selected(repo) == ["tests/test_alpha.py"]

    def test_unrelated_change_selects_nothing(self, repo):
        _commit(repo, "notes.txt")
        assert _selected(repo) == []

    def test_changed_test_selects_itself(self, repo):
        _commit(repo, "tests/test_beta.py", text="# covers beta-tool, edited\n")
        assert _selected(repo) == ["tests/test_beta.py"]

    def test_deleted_source_still_selects_the_tests_that_mention_it(self, repo):
        _commit(repo, "bin/beta-tool", delete=True)
        assert _selected(repo) == ["tests/test_beta.py"]

    def test_a_skill_file_is_matched_by_its_directory_name(self, repo):
        _commit(repo, "skills/gamma/SKILL.md")
        assert _selected(repo) == ["tests/test_gamma.py"]

    def test_generic_readme_is_matched_by_path_not_basename(self, repo):
        _write(repo, "other/README.md", "# other\n")
        _commit(repo, "other/README.md")
        assert _selected(repo) == []
        _commit(repo, "docs/README.md")
        assert _selected(repo) == ["tests/test_docs.py"]

    def test_python_module_is_matched_by_its_import(self, repo):
        _commit(repo, "scripts/zed.py")
        assert _selected(repo) == ["tests/test_zed.py"]

    def test_selection_is_deduplicated_and_sorted(self, repo):
        _commit(repo, "scripts/alpha.sh", "bin/beta-tool", "scripts/zed.py")
        assert _selected(repo) == [
            "tests/test_alpha.py",
            "tests/test_beta.py",
            "tests/test_zed.py",
        ]

    def test_shared_test_infrastructure_warns_instead_of_selecting_everything(self, repo):
        _commit(repo, "tests/conftest.py", text="# shared\n")
        done = _select(repo)
        assert done.returncode == 0
        assert done.stdout.split() == []
        assert "scripts/test-all.sh" in done.stderr

    def test_explicit_base_and_head(self, repo):
        first = _commit(repo, "scripts/alpha.sh")
        second = _commit(repo, "bin/beta-tool")
        assert _selected(repo, "--base", first, "--head", second) == ["tests/test_beta.py"]

    def test_list_changed_prints_paths_not_tests(self, repo):
        _commit(repo, "scripts/alpha.sh", "notes.txt")
        done = _select(repo, "--list-changed")
        assert sorted(done.stdout.split()) == ["notes.txt", "scripts/alpha.sh"]

    def test_non_ascii_paths_are_listed_and_selected_unquoted(self, repo):
        _commit(repo, "tests/test_café.py", text="# covers café\n")
        assert _selected(repo) == ["tests/test_café.py"]
        assert "tests/test_café.py" in _select(repo, "--list-changed").stdout.split("\n")

    def test_unknown_base_is_not_an_error(self, repo):
        _commit(repo, "scripts/alpha.sh")
        done = _select(repo, "--base", "f" * 40)
        assert done.returncode == 0
        assert done.stdout == ""
        assert "no usable base" in done.stderr

    def test_unknown_argument_is_rejected(self, repo):
        assert _select(repo, "--bogus").returncode == 64


# ── scripts/test-all.sh ───────────────────────────────────────────────────────

SHIM = textwrap.dedent(
    """\
    #!/bin/bash
    if [ "$1" = "-c" ]; then [ "${SHIM_XDIST:-0}" = "1" ]; exit $?; fi
    printf '%s\\n' "$@" > "$SHIM_OUT"
    exit "${SHIM_RC:-0}"
    """
)


@pytest.fixture
def runner(tmp_path):
    """Run test-all.sh with a shim `python3` that records its arguments."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "python3"
    shim.write_text(SHIM)
    shim.chmod(0o755)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    out = tmp_path / "argv.txt"

    class Runner:
        lock = scratch / "swe-workbench-test-all.lock"

        def __call__(self, *args: str, xdist=True, rc=0, timeout=60, **extra: str):
            base = dict(_CLEAN_ENV)
            base.pop("SWE_WORKBENCH_TEST_WORKERS", None)
            env = {
                **base,
                "PATH": f"{shim_dir}:/usr/bin:/bin",
                "TMPDIR": str(scratch),
                "SHIM_OUT": str(out),
                "SHIM_XDIST": "1" if xdist else "0",
                "SHIM_RC": str(rc),
                **extra,
            }
            return subprocess.run(
                ["bash", str(TEST_ALL), *args],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout,
            )  # fmt: skip

        def argv(self) -> list[str]:
            return out.read_text().split() if out.exists() else []

    return Runner()


class TestTestAll:
    def test_defaults_to_three_workers_over_the_whole_suite(self, runner):
        done = runner()
        assert done.returncode == 0, done.stderr
        assert runner.argv() == ["-m", "pytest", "-n", "3", "--dist", "loadfile", "tests/"]

    def test_workers_flag_and_env_override(self, runner):
        assert runner("--workers", "2").returncode == 0
        assert runner.argv()[2:4] == ["-n", "2"]
        runner(SWE_WORKBENCH_TEST_WORKERS="5")
        assert runner.argv()[2:4] == ["-n", "5"]

    def test_one_worker_is_serial(self, runner):
        runner("--workers", "1")
        assert runner.argv() == ["-m", "pytest", "tests/"]

    def test_without_xdist_it_runs_serially_and_says_so(self, runner):
        done = runner(xdist=False)
        assert done.returncode == 0
        assert runner.argv() == ["-m", "pytest", "tests/"]
        assert "pytest-xdist" in done.stderr

    def test_paths_and_options_are_passed_through(self, runner):
        runner("tests/test_alpha.py", "-k", "beta")
        assert runner.argv()[-3:] == ["tests/test_alpha.py", "-k", "beta"]
        assert "tests/" not in runner.argv()[:-3]

    def test_exit_status_is_pytests(self, runner):
        assert runner(rc=5).returncode == 5

    def test_bad_worker_count_is_rejected(self, runner):
        assert runner("--workers", "many").returncode == 64

    def test_lock_is_released_after_a_run(self, runner):
        runner()
        assert not runner.lock.exists()

    def test_a_live_holder_blocks_until_the_timeout(self, runner):
        runner.lock.mkdir()
        (runner.lock / "pid").write_text(str(os.getpid()))
        done = runner(SWE_WORKBENCH_TEST_LOCK_TIMEOUT="2")
        assert done.returncode == 75
        assert "gave up waiting" in done.stderr
        assert runner.argv() == []
        assert runner.lock.exists(), "a live holder's lock must be left alone"

    def test_a_stale_lock_is_reclaimed(self, runner):
        child = subprocess.Popen(["true"])
        child.wait()
        runner.lock.mkdir()
        (runner.lock / "pid").write_text(str(child.pid))
        done = runner(SWE_WORKBENCH_TEST_LOCK_TIMEOUT="5")
        assert done.returncode == 0, done.stderr
        assert runner.argv() != []
        assert not runner.lock.exists()

    def test_no_lock_ignores_a_held_lock(self, runner):
        runner.lock.mkdir()
        (runner.lock / "pid").write_text(str(os.getpid()))
        done = runner("--no-lock", "tests/test_alpha.py")
        assert done.returncode == 0, done.stderr
        assert runner.lock.exists()


# ── .githooks/pre-push wiring ─────────────────────────────────────────────────


@pytest.fixture
def hook_repo(repo):
    """`repo` plus the real hook and selector, a no-op validate.sh and a recording runner."""
    shutil.copy(SELECT, repo / "scripts" / "select-tests.sh")
    _write(repo, "scripts/validate.sh", "#!/bin/bash\nexit 0\n")
    _write(
        repo,
        "scripts/test-all.sh",
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$(dirname "$0")/../runner-args.txt"\n',
    )
    _write(repo, ".githooks/pre-push", PRE_PUSH.read_text(encoding="utf-8"))
    for rel in (
        "scripts/select-tests.sh",
        "scripts/validate.sh",
        "scripts/test-all.sh",
        ".githooks/pre-push",
    ):
        (repo / rel).chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "hook")
    return repo


def _push(repo: Path, *lines: str, **env: str):
    # nested pytest runs must not inherit an outer xdist worker's identity
    base = {k: v for k, v in _CLEAN_ENV.items() if not k.startswith("PYTEST_XDIST")}
    return subprocess.run(
        ["bash", str(repo / ".githooks" / "pre-push")],
        cwd=repo, env={**base, **env}, input="\n".join(lines) + "\n",
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip


def _runner_calls(repo: Path) -> list[str]:
    """One entry per runner invocation, each the arguments it received."""
    path = repo / "runner-args.txt"
    return path.read_text().splitlines() if path.exists() else []


class TestPrePushWiring:
    def test_runs_only_the_covering_tests_without_the_queue(self, hook_repo):
        remote = _git(hook_repo, "rev-parse", "main")
        head = _commit(hook_repo, "scripts/alpha.sh")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {remote}")
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == ["--no-lock tests/test_alpha.py"]

    def test_a_new_branch_is_compared_with_the_default_branch(self, hook_repo):
        head = _commit(hook_repo, "bin/beta-tool")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == ["--no-lock tests/test_beta.py"]

    def test_smallest_files_run_first(self, hook_repo):
        _write(hook_repo, "tests/test_alpha.py", "# covers alpha.sh\n" + "# pad\n" * 400)
        head = _commit(hook_repo, "scripts/alpha.sh", "bin/beta-tool")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == [
            "--no-lock tests/test_beta.py",
            "--no-lock tests/test_alpha.py",
        ]

    def test_a_spent_budget_leaves_the_rest_to_ci_and_says_which(self, hook_repo):
        head = _commit(hook_repo, "scripts/alpha.sh", "bin/beta-tool")
        done = _push(
            hook_repo,
            f"refs/heads/feature {head} refs/heads/feature {ZERO}",
            SWE_WORKBENCH_PREPUSH_BUDGET="0",
        )
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == []
        assert "left to CI" in done.stdout
        assert "tests/test_alpha.py" in done.stdout and "tests/test_beta.py" in done.stdout

    def test_the_first_failing_file_stops_the_run(self, hook_repo):
        _write(hook_repo, "scripts/test-all.sh", '#!/bin/bash\necho "$*" >> runner-args.txt\nexit 3\n')
        head = _commit(hook_repo, "scripts/alpha.sh", "bin/beta-tool")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 3
        assert len(_runner_calls(hook_repo)) == 1

    def test_nothing_covered_means_no_runner_and_a_note(self, hook_repo):
        head = _commit(hook_repo, "notes.txt")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == []
        assert "CI runs the full suite" in done.stdout

    def test_ref_deletion_and_tags_are_skipped(self, hook_repo):
        head = _git(hook_repo, "rev-parse", "HEAD")
        done = _push(
            hook_repo,
            f"(delete) {ZERO} refs/heads/gone {head}",
            f"refs/tags/v1 {head} refs/tags/v1 {ZERO}",
        )
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == []

    def test_a_failing_runner_fails_the_push(self, hook_repo):
        _write(hook_repo, "scripts/test-all.sh", "#!/bin/bash\nexit 1\n")
        head = _commit(hook_repo, "scripts/alpha.sh")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 1

    def test_a_failing_validate_fails_the_push_before_any_test_runs(self, hook_repo):
        _write(hook_repo, "scripts/validate.sh", "#!/bin/bash\nexit 1\n")
        head = _commit(hook_repo, "scripts/alpha.sh")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 1
        assert _runner_calls(hook_repo) == []

    def test_it_never_runs_the_whole_suite_directly(self):
        body = PRE_PUSH.read_text(encoding="utf-8")
        assert "scripts/test-all.sh" in body and "--no-lock" in body
        assert 'pytest "$REPO_ROOT/tests/"' not in body


PASSING_TEST = "def test_alpha():\n    assert True\n"
FAILING_TEST = "def test_alpha():\n    assert False, 'edited test must run'\n"


@pytest.fixture
def old_branch(hook_repo):
    """A branch cut before the helper scripts existed: the hook is shared, the scripts are not."""
    for rel in ("scripts/select-tests.sh", "scripts/test-all.sh"):
        _git(hook_repo, "rm", "-q", rel)
    _git(hook_repo, "commit", "-q", "-m", "branch without the helpers")
    return hook_repo


class TestPrePushOnABranchWithoutTheHelpers:
    """The hook comes from the main checkout; the scripts come from each branch."""

    def test_it_says_so_and_how_to_fix_it(self, old_branch):
        head = _commit(old_branch, "tests/test_alpha.py", text=PASSING_TEST)
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "predates" in done.stdout
        assert "merge main" in done.stdout
        assert "select-tests.sh" not in done.stderr, "the raw missing-script error must not leak"

    def test_the_changed_test_files_still_run_and_can_block_the_push(self, old_branch):
        head = _commit(old_branch, "tests/test_alpha.py", text=FAILING_TEST)
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode != 0
        assert "edited test must run" in done.stdout

    def test_a_passing_changed_test_is_run_not_skipped(self, old_branch):
        head = _commit(old_branch, "tests/test_alpha.py", text=PASSING_TEST)
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert "1 passed" in done.stdout

    def test_it_never_claims_no_tests_cover_the_change(self, old_branch):
        head = _commit(old_branch, "scripts/alpha.sh")
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "no tests cover this change" not in done.stdout
        assert "predates" in done.stdout

    def test_a_deleted_test_leaves_nothing_to_run_and_says_so(self, old_branch):
        head = _commit(old_branch, "tests/test_alpha.py", delete=True)
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "no changed test files to run" in done.stdout

    def test_the_budget_applies_to_the_direct_run_too(self, old_branch):
        _write(old_branch, "tests/test_beta.py", PASSING_TEST.replace("alpha", "beta"))
        head = _commit(old_branch, "tests/test_alpha.py", text=PASSING_TEST)
        done = _push(
            old_branch,
            f"refs/heads/feature {head} refs/heads/feature {ZERO}",
            SWE_WORKBENCH_PREPUSH_BUDGET="0",
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "left to CI" in done.stdout
        assert "tests/test_alpha.py" in done.stdout

    def test_smaller_changed_files_run_before_larger_ones(self, old_branch):
        _write(old_branch, "tests/test_beta.py", "def test_beta():\n    assert False, 'large'\n" + "# pad\n" * 300)
        head = _commit(old_branch, "tests/test_alpha.py", text=PASSING_TEST)
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        # the small passing file ran first; the large failing one then stopped the push
        assert "1 passed" in done.stdout
        assert done.returncode != 0

    def test_non_ascii_test_file_names_are_still_run(self, old_branch):
        head = _commit(old_branch, "tests/test_café.py", text=FAILING_TEST)
        done = _push(old_branch, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode != 0, "a failing test with a non-ASCII name must not slip through"

    def test_the_selector_is_borrowed_from_the_checkout_the_hook_lives_in(self, hook_repo, tmp_path):
        # `hook_repo` plays the main checkout: it has the scripts. `old` is a branch cut
        # before them, running the hook through the hooks-symlink like a real worktree.
        old = tmp_path / "old"
        old.mkdir()
        _git(old, "init", "-q", "-b", "main")
        _write(old, "scripts/alpha.sh", "#!/bin/bash\necho alpha\n")
        _write(old, "scripts/validate.sh", "#!/bin/bash\nexit 0\n")
        _write(old, "tests/test_alpha.py", PASSING_TEST + "# covers alpha.sh\n")
        _git(old, "add", "-A")
        _git(old, "commit", "-q", "-m", "base")
        _git(old, "switch", "-q", "-c", "feature")
        head = _commit(old, "scripts/alpha.sh")
        link = old / ".git" / "hooks" / "pre-push"
        link.symlink_to(hook_repo / ".githooks" / "pre-push")
        done = subprocess.run(
            ["bash", str(link)], cwd=old, env=dict(_CLEAN_ENV),
            input=f"refs/heads/feature {head} refs/heads/feature {ZERO}\n",
            capture_output=True, text=True, timeout=60,
        )  # fmt: skip
        assert done.returncode == 0, done.stdout + done.stderr
        assert "predates" in done.stdout and "merge main" in done.stdout
        assert "1 passed" in done.stdout, "the source-only edit must still select its test"
        assert "no changed test files" not in done.stdout


class TestPrePushWhenTheSelectorBreaks:
    def test_a_failing_selector_is_a_selection_failure_not_nothing_selected(self, hook_repo):
        _write(hook_repo, "scripts/select-tests.sh", "#!/bin/bash\necho boom >&2\nexit 7\n")
        head = _commit(hook_repo, "tests/test_alpha.py", text=FAILING_TEST)
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert "selection failed" in done.stdout
        assert "no tests cover this change" not in done.stdout
        assert done.returncode != 0, "the changed test is still run directly and fails"
        assert _runner_calls(hook_repo) == []

    def test_an_unknown_remote_sha_falls_back_to_the_default_branch(self, hook_repo):
        head = _commit(hook_repo, "scripts/alpha.sh")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {'f' * 40}")
        assert done.returncode == 0, done.stderr
        assert _runner_calls(hook_repo) == ["--no-lock tests/test_alpha.py"]

    def test_nothing_selected_by_a_working_selector_still_says_so(self, hook_repo):
        head = _commit(hook_repo, "notes.txt")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert "no tests cover this change" in done.stdout

    def test_one_failing_selector_does_not_drop_the_other_refs_selection(self, hook_repo):
        real = hook_repo / "scripts" / "real-select.sh"
        shutil.copy(SELECT, real)
        head_a = _commit(hook_repo, "tests/test_beta.py", text=PASSING_TEST.replace("alpha", "beta"))
        head_b = _commit(hook_repo, "tests/test_alpha.py", text=PASSING_TEST)
        _write(
            hook_repo,
            "scripts/select-tests.sh",
            "#!/bin/bash\n"
            f'case " $* " in *" --head {head_a} "*) echo boom >&2; exit 7 ;; esac\n'
            'exec bash "$(dirname "$0")/real-select.sh" "$@"\n',
        )
        done = _push(
            hook_repo,
            f"refs/heads/a {head_a} refs/heads/a {ZERO}",
            f"refs/heads/b {head_b} refs/heads/b {ZERO}",
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "selection failed" in done.stdout
        assert "running 2 test file(s)" in done.stdout

    def test_no_default_branch_to_compare_with_is_said_not_swallowed(self, hook_repo):
        _git(hook_repo, "branch", "-D", "main")
        head = _commit(hook_repo, "scripts/alpha.sh")
        done = _push(hook_repo, f"refs/heads/feature {head} refs/heads/feature {ZERO}")
        assert done.returncode == 0, done.stderr
        assert "could not tell what changed" in done.stdout
        assert "no tests cover this change" not in done.stdout
        assert _runner_calls(hook_repo) == []

    def test_an_unknown_base_on_one_ref_is_reported_even_when_another_ref_ran(self, hook_repo):
        known = _git(hook_repo, "rev-parse", "HEAD")
        _git(hook_repo, "branch", "-D", "main")
        head = _commit(hook_repo, "scripts/alpha.sh")
        done = _push(
            hook_repo,
            f"refs/heads/new {head} refs/heads/new {ZERO}",
            f"refs/heads/feature {head} refs/heads/feature {known}",
        )
        assert done.returncode == 0, done.stderr
        assert "could not tell what changed for 1 ref" in done.stdout
        assert _runner_calls(hook_repo) == ["--no-lock tests/test_alpha.py"]

    def test_a_push_with_no_branch_updates_does_not_claim_coverage(self, hook_repo):
        head = _git(hook_repo, "rev-parse", "HEAD")
        done = _push(hook_repo, f"refs/tags/v1 {head} refs/tags/v1 {ZERO}")
        assert done.returncode == 0, done.stderr
        assert "no branch updates" in done.stdout
        assert "no tests cover this change" not in done.stdout
