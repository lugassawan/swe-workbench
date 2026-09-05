"""Tests for bin/swe-workbench-pr-review-threads (the `evidence` subcommand).

Unit tests import the pure helpers directly (SourceFileLoader, mirroring
test_address_feedback_fetch_script.py's precedent). Behavioral tests drive the
script as a subprocess against a PATH-scoped, call-index-driven `gh` stub
(STUB_BODY convention from test_pr_review_submit_script.py) plus a real temp
git repository as `--worktree`, so `git log` (commits_since) and file reads
(excerpt, anchor status) exercise real git/filesystem behavior rather than a
second layer of mocking.

Note: `commits_since` and `compute_anchor`/`build_evidence_record` (which read
files and shell out to `git`) are exercised only via the full-script subprocess
path, never by calling the module's functions directly in-process — this
process's own subprocess.run is wrapped by conftest.py's session-scoped
GIT_DIR leak guard, which injects a GIT_DIR sentinel into os.environ; a
direct in-process call that shells out to `git` without an explicit env=
would inherit that sentinel and trip the guard. Spawning the script as a
real subprocess (with an explicit env=dict(_CLEAN_ENV) | overrides) sidesteps
this entirely, matching how bin/swe-workbench-pr-review-submit's own
git-touching helpers are tested.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-pr-review-threads"


def _load_module():
    loader = SourceFileLoader("pr_review_threads", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("pr_review_threads", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pr_review_threads"] = module
    spec.loader.exec_module(module)
    return module


prt = _load_module()


# ── Existence / syntax ───────────────────────────────────────────────────────


def test_script_exists_and_executable():
    import os

    assert SCRIPT.exists(), "bin/swe-workbench-pr-review-threads must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-pr-review-threads must be executable (chmod +x)"


def test_script_compiles():
    import py_compile

    py_compile.compile(str(SCRIPT), doraise=True)


# ── Unit: filter_own_open_threads ─────────────────────────────────────────────


def _thread(
    *,
    id="T1",
    path="a.py",
    line=10,
    is_resolved=False,
    is_outdated=False,
    head_author="me",
    created_at="2020-01-01T00:00:00Z",
):
    return {
        "id": id,
        "path": path,
        "line": line,
        "is_resolved": is_resolved,
        "is_outdated": is_outdated,
        "head_author": head_author,
        "head_comment_database_id": 1,
        "created_at": created_at,
    }


def test_filter_keeps_own_open_thread():
    survivors, skipped_other, skipped_outdated = prt.filter_own_open_threads([_thread()], "me")
    assert [t["id"] for t in survivors] == ["T1"]
    assert skipped_other == 0
    assert skipped_outdated == 0


def test_filter_skips_other_author():
    survivors, skipped_other, skipped_outdated = prt.filter_own_open_threads(
        [_thread(head_author="someone-else")], "me"
    )
    assert survivors == []
    assert skipped_other == 1
    assert skipped_outdated == 0


def test_filter_empty_current_user_never_matches_empty_head_author():
    """Design intent: never guess identity. An empty --current-user must not match
    a thread whose head author is also empty/null via accidental string equality —
    both threads must fall out of the *other-author* bucket by explicit code."""
    survivors, skipped_other, skipped_outdated = prt.filter_own_open_threads([_thread(head_author="")], "")
    assert survivors == []
    assert skipped_other == 1


def test_filter_skips_outdated():
    survivors, skipped_other, skipped_outdated = prt.filter_own_open_threads([_thread(is_outdated=True)], "me")
    assert survivors == []
    assert skipped_outdated == 1
    assert skipped_other == 0


def test_filter_skips_resolved_without_counting_either_bucket():
    survivors, skipped_other, skipped_outdated = prt.filter_own_open_threads([_thread(is_resolved=True)], "me")
    assert survivors == []
    assert skipped_other == 0
    assert skipped_outdated == 0


# ── Unit: compute_anchor (pure Path checks — no subprocess) ──────────────────


def test_anchor_no_line_anchor(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    status, reason = prt.compute_anchor(tmp_path, "a.py", None)
    assert (status, reason) == ("missing", "no_line_anchor")


def test_anchor_file_deleted(tmp_path):
    status, reason = prt.compute_anchor(tmp_path, "does-not-exist.py", 3)
    assert (status, reason) == ("missing", "file_deleted")


def test_anchor_line_beyond_eof(tmp_path):
    (tmp_path / "a.py").write_text("x\ny\n")
    status, reason = prt.compute_anchor(tmp_path, "a.py", 50)
    assert (status, reason) == ("missing", "line_beyond_eof")


def test_anchor_ok_within_bounds(tmp_path):
    (tmp_path / "a.py").write_text("\n".join(str(i) for i in range(1, 21)) + "\n")
    status, reason = prt.compute_anchor(tmp_path, "a.py", 10)
    assert (status, reason) == ("ok", None)


def test_anchor_path_traversal_guard_treated_as_file_deleted(tmp_path):
    """A path escaping the worktree root (e.g. from an attacker-influenced GitHub API
    field on an external contributor's PR) must fail closed into the existing
    file_deleted bucket rather than reading outside the worktree."""
    (tmp_path / "sentinel-outside").mkdir()
    worktree = tmp_path / "sentinel-outside" / "worktree"
    worktree.mkdir()
    status, reason = prt.compute_anchor(worktree, "../../../../../../etc/passwd", 1)
    assert (status, reason) == ("missing", "file_deleted")


def test_anchor_path_traversal_guard_does_not_escape_even_when_target_exists(tmp_path):
    """Stronger form of the guard: a traversal path that *does* resolve to a real,
    readable file outside the worktree must still be rejected — the guard checks
    containment, not merely existence."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret = outside_dir / "secret.txt"
    secret.write_text("line1\nline2\nline3\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    status, reason = prt.compute_anchor(worktree, "../outside/secret.txt", 1)
    assert (status, reason) == ("missing", "file_deleted")


# ── Unit: build_excerpt (pure file read — no subprocess) ─────────────────────


def test_build_excerpt_window_and_formatting(tmp_path):
    lines = [f"line{i}" for i in range(1, 41)]
    (tmp_path / "f.py").write_text("\n".join(lines) + "\n")
    excerpt = prt.build_excerpt(tmp_path, "f.py", 20)
    excerpt_lines = excerpt.split("\n")
    assert excerpt_lines[0] == "5: line5"
    assert excerpt_lines[-1] == "35: line35"
    assert len(excerpt_lines) == 31


def test_build_excerpt_clamps_at_start_of_file(tmp_path):
    lines = [f"line{i}" for i in range(1, 11)]
    (tmp_path / "f.py").write_text("\n".join(lines) + "\n")
    excerpt = prt.build_excerpt(tmp_path, "f.py", 2)
    excerpt_lines = excerpt.split("\n")
    assert excerpt_lines[0] == "1: line1"
    assert excerpt_lines[-1] == "10: line10"


# ── Behavioral: call-index-driven gh stub + real git worktree ────────────────

STUB_BODY = '''#!/usr/bin/env python3
import json, os, sys

state_dir = os.environ["GH_STUB_STATE"]
responses = json.load(open(os.environ["GH_STUB_RESPONSES"]))
count_file = os.path.join(state_dir, "count")
i = int(open(count_file).read()) if os.path.exists(count_file) else 0
open(count_file, "w").write(str(i + 1))
argv = sys.argv[1:]
stdin_data = sys.stdin.read()
with open(os.path.join(state_dir, f"call-{i}.json"), "w") as f:
    json.dump({"argv": argv, "stdin": stdin_data}, f)
resp = responses[i] if i < len(responses) else {
    "stdout": "", "stderr": f"gh-stub: no response configured for call {i} (argv={argv})", "exit": 99,
}
sys.stdout.write(resp.get("stdout", ""))
sys.stderr.write(resp.get("stderr", ""))
sys.exit(resp.get("exit", 0))
'''


def _write_gh_stub(tmp_path: Path, responses: list[dict]) -> tuple[Path, Path]:
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "gh"
    stub.write_text(STUB_BODY)
    stub.chmod(0o755)
    state_dir = tmp_path / "gh_state"
    state_dir.mkdir(exist_ok=True)
    (tmp_path / "gh_responses.json").write_text(json.dumps(responses))
    return stub_dir, state_dir


def _gh_calls(state_dir: Path) -> list[dict]:
    calls = []
    i = 0
    while (state_dir / f"call-{i}.json").exists():
        calls.append(json.loads((state_dir / f"call-{i}.json").read_text()))
        i += 1
    return calls


def _ok(stdout="", exit=0, stderr=""):
    return {"stdout": stdout, "exit": exit, "stderr": stderr}


def _threads_page_response(nodes: list[dict], *, has_next_page=False, end_cursor=None):
    body = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next_page},
                        "nodes": nodes,
                    }
                }
            }
        }
    }
    return _ok(json.dumps(body))


def _thread_node(
    *,
    id,
    path="a.py",
    line=10,
    is_resolved=False,
    is_outdated=False,
    author="me",
    created_at="2020-01-01T00:00:00Z",
    database_id=1,
):
    return {
        "id": id,
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "path": path,
        "line": line,
        "startLine": None,
        "comments": {
            "nodes": [
                {
                    "id": f"{id}-c0",
                    "databaseId": database_id,
                    "body": "please fix",
                    "createdAt": created_at,
                    "author": {"login": author},
                }
            ]
        },
    }


def _init_repo(tmp_path: Path, name: str = "worktree") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, env=dict(_CLEAN_ENV), check=True, capture_output=True)
    return repo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=dict(_CLEAN_ENV), check=True, capture_output=True)


def _run(argv: list[str], *, stub_dir: Path, state_dir: Path, responses_file: Path):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    env["GH_STUB_STATE"] = str(state_dir)
    env["GH_STUB_RESPONSES"] = str(responses_file)
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, env=env)


def _evidence_args(*, repo="owner/repo", pr="1", current_user="me", worktree, out_dir):
    return [
        "evidence",
        "--repo", repo,
        "--pr", pr,
        "--current-user", current_user,
        "--worktree", str(worktree),
        "--out-dir", str(out_dir),
    ]


class TestPagination:
    def test_pagination_two_pages_both_appear(self, tmp_path):
        worktree = _init_repo(tmp_path)
        (worktree / "a.py").write_text("\n".join(f"l{i}" for i in range(1, 31)) + "\n")
        page1 = _threads_page_response([_thread_node(id="T1", line=5)], has_next_page=True, end_cursor="CUR1")
        page2 = _threads_page_response([_thread_node(id="T2", line=10)], has_next_page=False)
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page1, page2])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["schema"] == "swb.pr-review-threads-evidence/1"
        assert envelope["data"]["eligible_threads"] == 2
        records = json.loads((out_dir / "threads-evidence.json").read_text())
        assert {r["thread_id"] for r in records} == {"T1", "T2"}
        calls = _gh_calls(state_dir)
        graphql_calls = [c for c in calls if c["argv"][:2] == ["api", "graphql"]]
        assert len(graphql_calls) == 2, "must issue exactly one gh call per reviewThreads page"
        assert any("after" in a for a in graphql_calls[1]["argv"]), (
            "the second page's call must pass the endCursor from page 1 as -F after=..."
        )


class TestFilteringCounters:
    def test_other_author_thread_counted_and_excluded(self, tmp_path):
        worktree = _init_repo(tmp_path)
        (worktree / "a.py").write_text("x\n")
        page = _threads_page_response([_thread_node(id="T1", author="someone-else")])
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["data"]["skipped_other_author"] == 1
        assert envelope["data"]["eligible_threads"] == 0

    def test_outdated_thread_counted_and_excluded(self, tmp_path):
        worktree = _init_repo(tmp_path)
        (worktree / "a.py").write_text("x\n")
        page = _threads_page_response([_thread_node(id="T1", is_outdated=True)])
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["data"]["skipped_outdated"] == 1
        assert envelope["data"]["eligible_threads"] == 0


class TestNothingToVerify:
    def test_true_when_zero_threads_at_all(self, tmp_path):
        worktree = _init_repo(tmp_path)
        page = _threads_page_response([])
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["data"]["eligible_threads"] == 0
        assert envelope["data"]["skipped_no_anchor"] == 0
        assert envelope["data"]["nothing_to_verify"] is True

    def test_false_when_skipped_no_anchor_positive_but_eligible_zero(self, tmp_path):
        """A thread that survives the identity/resolved/outdated filter but whose file
        was deleted still means there is something for the caller to report as
        still-open — nothing_to_verify must stay False, not short-circuit."""
        worktree = _init_repo(tmp_path)
        page = _threads_page_response([_thread_node(id="T1", path="deleted.py", line=3)])
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["data"]["eligible_threads"] == 0
        assert envelope["data"]["skipped_no_anchor"] == 1
        assert envelope["data"]["nothing_to_verify"] is False
        records = json.loads((out_dir / "threads-evidence.json").read_text())
        assert records[0]["anchor_status"] == "missing"
        assert records[0]["reason"] == "file_deleted"


class TestEvidenceContent:
    def test_ok_thread_excerpt_and_commits_since(self, tmp_path):
        worktree = _init_repo(tmp_path)
        lines = [f"line{i}" for i in range(1, 41)]
        (worktree / "f.py").write_text("\n".join(lines) + "\n")
        _git(worktree, "add", "f.py")
        _git(worktree, "commit", "-m", "initial commit")
        (worktree / "f.py").write_text("\n".join(lines) + "\nline41\n")
        _git(worktree, "add", "f.py")
        _git(worktree, "commit", "-m", "second commit touching f")

        page = _threads_page_response(
            [_thread_node(id="T1", path="f.py", line=20, created_at="2020-01-01T00:00:00Z")]
        )
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        records = json.loads((out_dir / "threads-evidence.json").read_text())
        rec = records[0]
        assert rec["anchor_status"] == "ok"
        assert rec["reason"] is None
        assert rec["comment_database_id"] == 1
        assert rec["line"] == 20

        excerpt_lines = rec["excerpt"].split("\n")
        assert excerpt_lines[0] == "5: line5"
        assert excerpt_lines[-1] == "35: line35"

        commits = rec["commits_since"]
        assert len(commits) == 2
        subjects = {c["subject"] for c in commits}
        assert subjects == {"initial commit", "second commit touching f"}
        assert all(len(c["sha"]) == 40 for c in commits)

    def test_no_line_anchor_record_has_null_line_and_empty_evidence(self, tmp_path):
        worktree = _init_repo(tmp_path)
        (worktree / "f.py").write_text("x\n")
        page = _threads_page_response([_thread_node(id="T1", path="f.py", line=None)])
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        rec = json.loads((out_dir / "threads-evidence.json").read_text())[0]
        assert rec["anchor_status"] == "missing"
        assert rec["reason"] == "no_line_anchor"
        assert rec["line"] is None
        assert rec["excerpt"] is None
        assert rec["commits_since"] == []

    def test_line_beyond_eof_record(self, tmp_path):
        worktree = _init_repo(tmp_path)
        (worktree / "f.py").write_text("only-one-line\n")
        page = _threads_page_response([_thread_node(id="T1", path="f.py", line=999)])
        stub_dir, state_dir = _write_gh_stub(tmp_path, [page])
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 0, result.stderr
        rec = json.loads((out_dir / "threads-evidence.json").read_text())[0]
        assert rec["anchor_status"] == "missing"
        assert rec["reason"] == "line_beyond_eof"
        assert rec["line"] == 999


class TestFailClosed:
    def test_gh_nonzero_exit_fails_closed(self, tmp_path):
        worktree = _init_repo(tmp_path)
        responses = [{"stdout": "", "stderr": "gh: 502 Bad Gateway", "exit": 1}]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.strip() != ""
        assert not (out_dir / "threads-evidence.json").exists()

    def test_malformed_graphql_shape_fails_closed(self, tmp_path):
        worktree = _init_repo(tmp_path)
        responses = [_ok(json.dumps({"data": {"repository": None}}))]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.strip() != ""
        assert "Traceback" not in result.stderr

    def test_non_json_graphql_response_fails_closed(self, tmp_path):
        worktree = _init_repo(tmp_path)
        responses = [_ok("not json at all")]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        out_dir = tmp_path / "out"
        result = _run(
            _evidence_args(worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.strip() != ""

    def test_malformed_repo_missing_slash_fails_closed(self, tmp_path):
        worktree = _init_repo(tmp_path)
        out_dir = tmp_path / "out"
        stub_dir, state_dir = _write_gh_stub(tmp_path, [])
        result = _run(
            _evidence_args(repo="norepo", worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.strip() != ""
        assert "Traceback" not in result.stderr
        assert not (out_dir / "threads-evidence.json").exists()

    def test_malformed_repo_empty_fails_closed(self, tmp_path):
        worktree = _init_repo(tmp_path)
        out_dir = tmp_path / "out"
        stub_dir, state_dir = _write_gh_stub(tmp_path, [])
        result = _run(
            _evidence_args(repo="", worktree=worktree, out_dir=out_dir),
            stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.strip() != ""
        assert "Traceback" not in result.stderr
        assert not (out_dir / "threads-evidence.json").exists()


# ── CLI validation ───────────────────────────────────────────────────────────


def test_missing_subcommand_exits_nonzero():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0


def test_unknown_subcommand_exits_nonzero():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "bogus"], capture_output=True, text=True, env=dict(_CLEAN_ENV)
    )
    assert result.returncode != 0


def test_missing_required_evidence_flag_exits_nonzero():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "evidence", "--repo", "o/r"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0
