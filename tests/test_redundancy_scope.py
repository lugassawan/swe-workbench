"""Tests for redundancy-scope.sh — the deterministic gather step behind
`sync --check-redundancy` (issue #510).

Stdout contract (eval-safe KEY=VALUE, %q-quoted):
  MERGE_BASE=<sha>                          (echoed back; empty input -> empty output)
  CANDIDATE id=<n> path=<p> refs=<count>     one per whole file the branch ADDED
  CANDIDATES=<n>                            count of CANDIDATE lines
  MAIN_ADD path=<p>                         one per file the default branch added/changed
"""

import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "workflow-branch-sync"
    / "scripts"
    / "redundancy-scope.sh"
)


def _run(*args, cwd):
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=_CLEAN_ENV
    )


def _build_repo(base: Path, branch_adds: dict, main_adds: dict, base_files: dict | None = None) -> dict:
    """A merge-base commit, then `feature` and `main` each add distinct files.

    branch_adds / main_adds: {filename: content}. base_files (optional):
    {filename: content} committed as part of the merge-base itself — a
    main_adds entry with the same filename becomes a *modification* (status
    M) instead of an addition (status A). Returns a dict with repo path,
    merge_base sha, and feature-branch (pre-sync) head sha. Leaves HEAD on
    `feature` with nothing left uncommitted.
    """
    repo = base / "repo"
    _run("git", "init", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)

    (repo / "README.md").write_text("base\n")
    _run("git", "add", "README.md", cwd=repo)
    for name, content in (base_files or {}).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _run("git", "add", name, cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "branch", "-M", "main", cwd=repo)
    merge_base = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()

    _run("git", "checkout", "-b", "feature", cwd=repo)
    for name, content in branch_adds.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if branch_adds:
        _run("git", "add", *branch_adds.keys(), cwd=repo)
        _run("git", "commit", "-m", "branch adds", cwd=repo)
    pre_sync_head = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()

    _run("git", "checkout", "main", cwd=repo)
    for name, content in main_adds.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if main_adds:
        _run("git", "add", *main_adds.keys(), cwd=repo)
        _run("git", "commit", "-m", "main adds", cwd=repo)

    _run("git", "checkout", "feature", cwd=repo)
    return {"repo": repo, "merge_base": merge_base, "pre_sync_head": pre_sync_head}


def _run_script(repo: Path, merge_base: str, pre_sync_head: str, default_ref: str = "main"):
    return subprocess.run(
        ["bash", str(SCRIPT), merge_base, pre_sync_head, default_ref],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


class TestRedundancyScopePostMerge:
    """Regression: Step 6 calls this script AFTER Step 3's mechanical sync has
    already merged main into the branch — the working tree at that point
    contains BOTH the candidate and its main-side counterpart. The refs guard
    must not count a candidate's own MAIN_ADD counterpart as a "reference";
    otherwise a genuine whole-file duplicate always shows refs>0 and can
    never reach the AUTO-APPLY tier it exists to enable."""

    def test_refs_excludes_main_counterpart_after_actual_merge(self, tmp_path):
        ctx = _build_repo(
            tmp_path,
            branch_adds={"utils/foo.sh": "echo foo\n"},
            main_adds={"lib/foo.sh": "echo foo\n"},
        )
        _run("git", "merge", "-q", "main", "-m", "merge", cwd=ctx["repo"])

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        assert "CANDIDATE id=1 path=utils/foo.sh refs=0" in lines, lines

    def test_refs_still_catches_genuine_third_party_reference_after_merge(self, tmp_path):
        ctx = _build_repo(
            tmp_path,
            branch_adds={
                "utils/foo.sh": "echo foo\n",
                "consumer.sh": "source utils/foo.sh  # uses foo\n",
            },
            main_adds={"lib/foo.sh": "echo foo\n"},
        )
        _run("git", "merge", "-q", "main", "-m", "merge", cwd=ctx["repo"])

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        lines = result.stdout.strip().splitlines()
        assert any(
            ln.startswith("CANDIDATE ") and "path=utils/foo.sh" in ln and "refs=1" in ln for ln in lines
        ), lines

    def test_refs_catches_reference_added_in_a_file_main_only_modified(self, tmp_path):
        """Regression: the refs-exclusion set must only cover main's newly
        ADDED counterpart files, not every file main merely modified — a
        live reference living in a pre-existing file that main happened to
        touch (for any reason) in the same window must not be swallowed."""
        ctx = _build_repo(
            tmp_path,
            branch_adds={"utils/foo.sh": "echo foo\n"},
            main_adds={
                "lib/foo.sh": "echo foo\n",
                "consumer.sh": "source utils/foo.sh  # calls foo\n",
            },
            base_files={"consumer.sh": "echo placeholder\n"},
        )
        _run("git", "merge", "-q", "main", "-m", "merge", cwd=ctx["repo"])

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        lines = result.stdout.strip().splitlines()
        assert any(
            ln.startswith("CANDIDATE ") and "path=utils/foo.sh" in ln and "refs=1" in ln for ln in lines
        ), lines


class TestRedundancyScopeCandidates:
    def test_reports_candidate_with_zero_refs_and_main_add(self, tmp_path):
        ctx = _build_repo(
            tmp_path,
            branch_adds={"utils/foo.sh": "echo foo\n"},
            main_adds={"lib/foo.sh": "echo foo\n"},
        )

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        assert f"MERGE_BASE={ctx['merge_base']}" in lines
        assert "CANDIDATE id=1 path=utils/foo.sh refs=0" in lines
        assert "MAIN_ADD path=lib/foo.sh" in lines
        assert "CANDIDATES=1" in lines

    def test_candidate_with_inbound_reference_has_nonzero_refs(self, tmp_path):
        ctx = _build_repo(
            tmp_path,
            branch_adds={
                "utils/foo.sh": "echo foo\n",
                "consumer.sh": "source utils/foo.sh  # uses foo\n",
            },
            main_adds={},
        )

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        lines = result.stdout.strip().splitlines()
        assert any(ln.startswith("CANDIDATE ") and "path=utils/foo.sh" in ln and "refs=1" in ln for ln in lines), lines

    def test_reports_multiple_candidates_with_sequential_ids(self, tmp_path):
        ctx = _build_repo(
            tmp_path,
            branch_adds={"a.sh": "echo a\n", "b.sh": "echo b\n"},
            main_adds={},
        )

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        lines = result.stdout.strip().splitlines()
        candidate_lines = [ln for ln in lines if ln.startswith("CANDIDATE ")]
        assert len(candidate_lines) == 2
        ids = sorted(int(ln.split("id=")[1].split()[0]) for ln in candidate_lines)
        assert ids == [1, 2]
        assert "CANDIDATES=2" in lines

    def test_dotfile_candidate_does_not_collapse_stem_to_match_everything(self, tmp_path):
        """Regression: basename(".env") stripped of its "extension" collapses
        to an empty stem, turning the refs guard into `git grep -e ""`, which
        matches every tracked file regardless of actual usage."""
        ctx = _build_repo(
            tmp_path,
            branch_adds={"config/.env": "KEY=value\n"},
            main_adds={},
        )

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        lines = result.stdout.strip().splitlines()
        assert "CANDIDATE id=1 path=config/.env refs=0" in lines, lines

    def test_candidates_zero_when_branch_added_nothing(self, tmp_path):
        ctx = _build_repo(tmp_path, branch_adds={}, main_adds={"lib/foo.sh": "echo foo\n"})

        result = _run_script(ctx["repo"], ctx["merge_base"], ctx["pre_sync_head"])

        lines = result.stdout.strip().splitlines()
        assert "CANDIDATES=0" in lines
        assert not any(ln.startswith("CANDIDATE ") for ln in lines)


class TestRedundancyScopeEmptyMergeBase:
    def test_empty_merge_base_skips_without_crashing(self, tmp_path):
        ctx = _build_repo(
            tmp_path,
            branch_adds={"utils/foo.sh": "echo foo\n"},
            main_adds={"lib/foo.sh": "echo foo\n"},
        )

        result = _run_script(ctx["repo"], "", ctx["pre_sync_head"])

        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        assert "MERGE_BASE=" in lines
        assert "CANDIDATES=0" in lines
        assert not any(ln.startswith("CANDIDATE ") for ln in lines)
        assert not any(ln.startswith("MAIN_ADD ") for ln in lines)


class TestRedundancyScopeNotAGitRepo:
    def test_exits_nonzero_outside_git_repo(self, tmp_path):
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        result = subprocess.run(
            ["bash", str(SCRIPT), "abc123", "def456", "main"],
            cwd=str(not_a_repo),
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )

        assert result.returncode != 0
        assert "git work tree" in result.stderr


class TestRedundancyScopeUsage:
    def test_missing_required_args_exits_nonzero(self, tmp_path):
        result = subprocess.run(
            ["bash", str(SCRIPT), "abc123"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            env=_CLEAN_ENV,
        )

        assert result.returncode != 0
