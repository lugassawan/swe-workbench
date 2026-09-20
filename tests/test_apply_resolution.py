"""Tests for bin/swe-workbench-apply-conflict-resolution — the ours/theirs
inversion mapping, plus the precondition gate that runs before any mutation.

git inverts --ours/--theirs under rebase relative to merge:
  merge:  --ours = HEAD (your branch)         --theirs = incoming branch
  rebase: --ours = rebase target (default br)  --theirs = replayed commit (your branch)

The command takes a user-intent side (--intent mine|main) and an operation
(--operation merge|rebase) and must translate to git's --ours/--theirs
accordingly — callers must never pass raw ours/theirs. Before touching the
worktree or index it must also confirm: a merge/rebase is actually in
progress, the declared --operation matches the one git is really running,
and --file is an unmerged path in that operation.
"""

import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "bin" / "swe-workbench-apply-conflict-resolution"

CONFLICT_FILE = "shared.txt"
MINE_CONTENT = "feature-version\n"
MAIN_CONTENT = "main-version\n"
CLEAN_FILE = "untouched.txt"
CLEAN_CONTENT = "shared-untouched\n"
SPACE_FILE = "a file with spaces.txt"


def _run(*args, cwd):
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=_CLEAN_ENV
    )


def _build_repo(base: Path, filename: str = CONFLICT_FILE) -> Path:
    """main with one commit, feature branch diverging on the same file/line.

    Also carries a second file (CLEAN_FILE) added once at init and never
    touched by either branch, so it exists but never conflicts — used to
    test the "path is not unmerged" precondition.
    """
    repo = base / "repo"
    _run("git", "init", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    (repo / filename).write_text("base\n")
    (repo / CLEAN_FILE).write_text(CLEAN_CONTENT)
    _run("git", "add", filename, CLEAN_FILE, cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "branch", "-M", "main", cwd=repo)

    _run("git", "checkout", "-b", "feature", cwd=repo)
    (repo / filename).write_text(MINE_CONTENT)
    _run("git", "add", filename, cwd=repo)
    _run("git", "commit", "-m", "feature change", cwd=repo)

    _run("git", "checkout", "main", cwd=repo)
    (repo / filename).write_text(MAIN_CONTENT)
    _run("git", "add", filename, cwd=repo)
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


def _run_script(repo: Path, file_: str, intent: str, operation: str):
    return subprocess.run(
        [str(SCRIPT), "--file", file_, "--intent", intent, "--operation", operation],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


def _run_raw(repo: Path, args):
    return subprocess.run(
        [str(SCRIPT), *args],
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


def _is_unmerged(repo: Path, file_: str) -> bool:
    return not _is_staged(repo, file_)


def _parse_kv(stdout: str) -> dict:
    parsed = {}
    for line in stdout.strip().splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


class TestApplyResolutionMerge:
    """merge: mine -> --ours (HEAD/feature), main -> --theirs (incoming/main)."""

    def test_mine_under_merge_keeps_feature_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_main_under_merge_keeps_main_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "theirs"
        assert (repo / CONFLICT_FILE).read_text() == MAIN_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)


class TestApplyResolutionRebase:
    """rebase inverts: mine -> --theirs (replayed feature), main -> --ours (target)."""

    def test_mine_under_rebase_keeps_feature_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_rebase_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "rebase")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "theirs"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_main_under_rebase_keeps_main_content(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_rebase_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "rebase")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert (repo / CONFLICT_FILE).read_text() == MAIN_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)


def _build_delete_modify_repo(base: Path, *, feature_deletes: bool) -> Path:
    """main + feature diverge on shared.txt where one side deletes it and the
    other modifies it — a delete/modify conflict, distinct from the
    both-modified conflicts the other fixtures use.
    """
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
    if feature_deletes:
        _run("git", "rm", CONFLICT_FILE, cwd=repo)
        _run("git", "commit", "-m", "feature deletes", cwd=repo)
    else:
        (repo / CONFLICT_FILE).write_text(MINE_CONTENT)
        _run("git", "add", CONFLICT_FILE, cwd=repo)
        _run("git", "commit", "-m", "feature modifies", cwd=repo)

    _run("git", "checkout", "main", cwd=repo)
    if feature_deletes:
        (repo / CONFLICT_FILE).write_text(MAIN_CONTENT)
        _run("git", "add", CONFLICT_FILE, cwd=repo)
        _run("git", "commit", "-m", "main modifies", cwd=repo)
    else:
        _run("git", "rm", CONFLICT_FILE, cwd=repo)
        _run("git", "commit", "-m", "main deletes", cwd=repo)

    _run("git", "checkout", "feature", cwd=repo)
    return repo


class TestApplyResolutionDeleteModifyConflict:
    """Regression: the chosen side may have deleted the file, in which case
    `git checkout --ours/--theirs` has no blob to check out and fails with
    'does not have our/their version' — must resolve as `git rm`, not abort.
    """

    def test_merge_keep_mine_when_feature_modified_main_deleted(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=False)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_merge_keep_main_when_feature_modified_main_deleted(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=False)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "theirs"
        assert not (repo / CONFLICT_FILE).exists()
        assert _is_staged(repo, CONFLICT_FILE)

    def test_merge_keep_mine_when_feature_deleted_main_modified(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=True)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert not (repo / CONFLICT_FILE).exists()
        assert _is_staged(repo, CONFLICT_FILE)

    def test_merge_keep_main_when_feature_deleted_main_modified(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=True)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "theirs"
        assert (repo / CONFLICT_FILE).read_text() == MAIN_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_rebase_keep_mine_when_feature_modified_main_deleted(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=False)
        _induce_rebase_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "rebase")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "theirs"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)

    def test_rebase_keep_main_when_feature_modified_main_deleted(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=False)
        _induce_rebase_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "rebase")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert not (repo / CONFLICT_FILE).exists()
        assert _is_staged(repo, CONFLICT_FILE)


class TestApplyResolutionPathNormalization:
    """Regression: a caller-supplied leading './' must not defeat the exact-match
    check against git's unmerged-path list, which never carries that prefix."""

    def test_leading_dot_slash_still_resolves(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, f"./{CONFLICT_FILE}", "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert (repo / CONFLICT_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, CONFLICT_FILE)


class TestApplyResolutionInvalidArgs:
    def test_rejects_unknown_intent(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "theirs", "merge")

        assert result.returncode != 0
        assert "--intent" in result.stderr

    def test_rejects_unknown_operation(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "cherry-pick")

        assert result.returncode != 0
        assert "--operation" in result.stderr

    def test_missing_args_usage_error(self, tmp_path):
        repo = _build_repo(tmp_path)
        result = _run_raw(repo, [])
        assert result.returncode != 0
        assert "Usage" in result.stderr


class TestApplyResolutionPreconditions:
    """Precondition gate: every check must run before any mutation."""

    def test_no_operation_in_progress_fails_without_mutation(self, tmp_path):
        repo = _build_repo(tmp_path)
        before = (repo / CONFLICT_FILE).read_bytes()

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode != 0
        assert "no merge or rebase" in result.stderr.lower()
        assert (repo / CONFLICT_FILE).read_bytes() == before

    def test_merge_in_progress_declared_rebase_fails_without_mutation(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)
        before = (repo / CONFLICT_FILE).read_bytes()

        result = _run_script(repo, CONFLICT_FILE, "mine", "rebase")

        assert result.returncode != 0
        assert "merge" in result.stderr.lower()
        assert "rebase" in result.stderr.lower()
        assert (repo / CONFLICT_FILE).read_bytes() == before
        assert _is_unmerged(repo, CONFLICT_FILE)

    def test_rebase_in_progress_declared_merge_fails_without_mutation(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_rebase_conflict(repo)
        before = (repo / CONFLICT_FILE).read_bytes()

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode != 0
        assert "merge" in result.stderr.lower()
        assert "rebase" in result.stderr.lower()
        assert (repo / CONFLICT_FILE).read_bytes() == before
        assert _is_unmerged(repo, CONFLICT_FILE)

    def test_path_not_unmerged_fails_without_mutation(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)
        before = (repo / CLEAN_FILE).read_bytes()

        result = _run_script(repo, CLEAN_FILE, "mine", "merge")

        assert result.returncode != 0
        assert "unmerged" in result.stderr.lower()
        assert (repo / CLEAN_FILE).read_bytes() == before

    def test_nonexistent_path_fails_without_mutation(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, "does-not-exist.txt", "mine", "merge")

        assert result.returncode != 0
        assert not (repo / "does-not-exist.txt").exists()
        assert _is_unmerged(repo, CONFLICT_FILE)

    def test_not_inside_git_work_tree_fails(self, tmp_path):
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()

        result = _run_script(non_repo, "whatever.txt", "mine", "merge")

        assert result.returncode != 0
        assert "git work tree" in result.stderr.lower()


class TestApplyResolutionPathsWithSpaces:
    def test_merge_keep_mine_with_spaces_in_filename(self, tmp_path):
        repo = _build_repo(tmp_path, filename=SPACE_FILE)
        _induce_merge_conflict(repo)

        result = _run_script(repo, SPACE_FILE, "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "ours"
        assert (repo / SPACE_FILE).read_text() == MINE_CONTENT
        assert _is_staged(repo, SPACE_FILE)

    def test_merge_keep_main_with_spaces_in_filename(self, tmp_path):
        repo = _build_repo(tmp_path, filename=SPACE_FILE)
        _induce_merge_conflict(repo)

        result = _run_script(repo, SPACE_FILE, "main", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout)["GIT_SIDE"] == "theirs"
        assert (repo / SPACE_FILE).read_text() == MAIN_CONTENT
        assert _is_staged(repo, SPACE_FILE)


class TestApplyResolutionStructuredOutput:
    def test_all_four_keys_present_on_checkout(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "mine", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout) == {
            "INTENT": "mine",
            "OPERATION": "merge",
            "GIT_SIDE": "ours",
            "ACTION": "checkout",
        }

    def test_action_remove_on_delete_modify_resolution(self, tmp_path):
        repo = _build_delete_modify_repo(tmp_path, feature_deletes=False)
        _induce_merge_conflict(repo)

        result = _run_script(repo, CONFLICT_FILE, "main", "merge")

        assert result.returncode == 0, result.stderr
        assert _parse_kv(result.stdout) == {
            "INTENT": "main",
            "OPERATION": "merge",
            "GIT_SIDE": "theirs",
            "ACTION": "remove",
        }


class TestApplyResolutionMalformedArguments:
    def test_unknown_flag_rejected(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_raw(
            repo,
            ["--file", CONFLICT_FILE, "--intent", "mine", "--operation", "merge", "--bogus"],
        )

        assert result.returncode != 0
        assert "Usage" in result.stderr
        assert _is_unmerged(repo, CONFLICT_FILE)

    def test_flag_missing_value_rejected(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_raw(repo, ["--file", CONFLICT_FILE, "--intent"])

        assert result.returncode != 0
        assert "Usage" in result.stderr
        assert _is_unmerged(repo, CONFLICT_FILE)

    def test_empty_file_value_rejected(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_raw(repo, ["--file", "", "--intent", "mine", "--operation", "merge"])

        assert result.returncode != 0
        assert "Usage" in result.stderr

    def test_equals_form_rejected(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_raw(
            repo, [f"--file={CONFLICT_FILE}", "--intent", "mine", "--operation", "merge"]
        )

        assert result.returncode != 0
        assert "Usage" in result.stderr
        assert _is_unmerged(repo, CONFLICT_FILE)

    def test_duplicate_flag_rejected(self, tmp_path):
        repo = _build_repo(tmp_path)
        _induce_merge_conflict(repo)

        result = _run_raw(
            repo,
            [
                "--file", CONFLICT_FILE,
                "--file", CONFLICT_FILE,
                "--intent", "mine",
                "--operation", "merge",
            ],
        )

        assert result.returncode != 0
        assert "Usage" in result.stderr
        assert _is_unmerged(repo, CONFLICT_FILE)
