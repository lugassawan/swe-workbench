"""Tests for bin/swe-workbench-address-feedback-fetch.

Unit tests import the pure eligibility helpers directly (SourceFileLoader, mirroring
test_result_check_script.py's precedent for a python bin/ module). Behavioral tests
drive the script as a subprocess against a PATH-scoped, call-index-driven `gh` stub —
extends test_pr_review_submit_script.py's STUB_BODY convention (each `gh` invocation
consumes the next canned response from an ordered list, recording its argv/stdin for
later inspection) down through the real bin/swe-workbench-preflight-pr,
bin/swe-workbench-fetch-pr, and bin/swe-workbench-gh-timeout siblings — only the
final `gh` binary itself is stubbed, so the whole real wrapper chain is exercised.

The 6 fixture cases from the jq program this replaces (test_workflow_address_feedback_skill.py's
now-deleted _run_pr_comments_filter tests) are ported verbatim as unit-test inputs/outputs
against compute_pr_comment_eligibility — a characterization-test migration, not a coverage loss.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-address-feedback-fetch"
SWEEP_RESIDUALS = ROOT / "bin" / "swe-workbench-sweep-residuals"
STATE_DIR = Path("/tmp/swe-workbench-address-feedback")


def _load_module():
    loader = SourceFileLoader("address_feedback_fetch", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("address_feedback_fetch", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["address_feedback_fetch"] = module
    spec.loader.exec_module(module)
    return module


aff = _load_module()


def _unique_n() -> str:
    return str(20_000_000 + int.from_bytes(os.urandom(3), "big"))


def _cleanup_state_files(pr: str) -> None:
    for suffix in (".json", "-threads.json", "-pr-comments.json", "-triage.json"):
        (STATE_DIR / f"{pr}{suffix}").unlink(missing_ok=True)


# ── Existence / syntax ───────────────────────────────────────────────────────


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-address-feedback-fetch must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-address-feedback-fetch must be executable (chmod +x)"


def test_script_compiles():
    import py_compile

    py_compile.compile(str(SCRIPT), doraise=True)


# ── Snapshot path parity with swe-workbench-sweep-residuals' hardcoded literals ──


def test_snapshot_paths_match_sweep_residuals_hardcoded_literals():
    """sweep-residuals hardcodes these paths for its own merged-PR backstop sweep —
    both spellings must stay byte-identical or that sweep silently stops reaping
    this flow's state files: the legacy un-scoped names ($N) and the #713 scoped
    names (${SCOPE_STEM}, literal in sweep's Block A candidate array)."""
    pr = "424242"
    threads_path = STATE_DIR / f"{pr}-threads.json"
    pr_comments_path = STATE_DIR / f"{pr}-pr-comments.json"
    pr_json_path = STATE_DIR / f"{pr}.json"

    sweep_text = SWEEP_RESIDUALS.read_text()
    for suffix in (".json", "-threads.json", "-pr-comments.json"):
        assert f'"$ADDR_FEEDBACK_DIR/$N{suffix}"' in sweep_text, (
            f"legacy candidate for {suffix} drifted — sweep-residuals must keep reaping it"
        )
        assert f'"$ADDR_FEEDBACK_DIR/${{SCOPE_STEM}}{suffix}"' in sweep_text, (
            f"scoped candidate for {suffix} drifted — sweep-residuals must reap the slugged spelling"
        )

    assert str(pr_json_path) == f"/tmp/swe-workbench-address-feedback/{pr}.json"
    assert str(threads_path) == f"/tmp/swe-workbench-address-feedback/{pr}-threads.json"
    assert str(pr_comments_path) == f"/tmp/swe-workbench-address-feedback/{pr}-pr-comments.json"


# ── Unit: compute_thread_eligibility ──────────────────────────────────────────


def _thread(*, is_resolved=False, reply_authors=()):
    return {
        "id": "T1",
        "isResolved": is_resolved,
        "path": "a.py",
        "line": 1,
        "startLine": None,
        "comments": {
            "nodes": [
                {"id": "c0", "databaseId": 1, "body": "opening", "author": {"login": "reviewer"}},
                *[
                    {"id": f"c{i}", "databaseId": i + 1, "body": "reply", "author": {"login": a}}
                    for i, a in enumerate(reply_authors)
                ],
            ]
        },
    }


def test_thread_resolved_is_ineligible():
    eligible, reason = aff.compute_thread_eligibility(_thread(is_resolved=True), "owner-login")
    assert eligible is False
    assert reason == "resolved"


def test_thread_unresolved_no_replies_is_eligible():
    eligible, reason = aff.compute_thread_eligibility(_thread(is_resolved=False), "owner-login")
    assert eligible is True
    assert reason is None


def test_thread_unresolved_owner_reply_is_already_clarified():
    eligible, reason = aff.compute_thread_eligibility(
        _thread(is_resolved=False, reply_authors=["owner-login"]), "owner-login"
    )
    assert eligible is False
    assert reason == "already-clarified"


def test_thread_opening_comment_by_current_user_does_not_count_as_reply():
    """nodes[0] is the thread-opening comment — even if authored by $CURRENT_USER, it
    must not itself mark the thread already-clarified (only nodes[1:] replies count)."""
    node = {
        "id": "T2",
        "isResolved": False,
        "path": "a.py",
        "line": 1,
        "startLine": None,
        "comments": {"nodes": [{"id": "c0", "databaseId": 1, "body": "opening", "author": {"login": "owner-login"}}]},
    }
    eligible, reason = aff.compute_thread_eligibility(node, "owner-login")
    assert eligible is True
    assert reason is None


def test_thread_unresolved_other_reply_is_eligible():
    eligible, reason = aff.compute_thread_eligibility(
        _thread(is_resolved=False, reply_authors=["someone-else"]), "owner-login"
    )
    assert eligible is True
    assert reason is None


# ── Unit: compute_pr_comment_eligibility (ported jq-program fixtures) ────────


def test_pr_comments_drops_bots_and_author():
    comments = [
        {"id": 1, "user": {"login": "some-bot", "type": "Bot"}, "body": "lgtm", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "user": {"login": "renovate[bot]", "type": "User"}, "body": "bump", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 3, "user": {"login": "pr-author", "type": "User"}, "body": "self note", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 4, "user": {"login": "reviewer1", "type": "User"}, "body": "please fix X", "created_at": "2026-01-01T00:00:00Z"},
    ]
    result = aff.compute_pr_comment_eligibility(comments, author="pr-author", me="pr-author")
    ids = {c["id"] for c in result}
    assert ids == {4}, f"bot/[bot]/author comments must be dropped entirely; got ids {ids}"
    assert result[0]["eligible"] is True


def test_pr_comments_drops_current_user_on_non_author_run():
    """Regression: on a non-author run, the runner's own past marker-bearing reply
    must not resurface as a fresh triage candidate (duplicate-reply spam)."""
    comments = [
        {"id": 20, "user": {"login": "reviewer6", "type": "User"}, "body": "please fix V", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 21, "user": {"login": "maintainer-x", "type": "User"}, "body": "done <!-- swe-workbench:handled:20 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = aff.compute_pr_comment_eligibility(comments, author="pr-author", me="maintainer-x")
    by_id = {c["id"]: c for c in result}
    assert 21 not in by_id, "comment 21 was authored by $me and must be dropped as a candidate entirely"
    assert by_id[20]["eligible"] is False, "comment 20 must still be marker-deduped via owner comment 21's marker"


def test_pr_comments_marker_dedup():
    comments = [
        {"id": 5, "user": {"login": "reviewer2", "type": "User"}, "body": "please fix Y", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 6, "user": {"login": "pr-author", "type": "User"}, "body": "done <!-- swe-workbench:handled:5 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = aff.compute_pr_comment_eligibility(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[5]["eligible"] is False, "a comment whose own marker is present must be ineligible"


def test_pr_comments_marker_match_is_anchored():
    """Regression: a marker for id 1234 must not dedup-suppress unrelated id 123 (a
    numeric prefix) via an unanchored substring match."""
    comments = [
        {"id": 123, "user": {"login": "reviewer3", "type": "User"}, "body": "please fix Z", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 999, "user": {"login": "pr-author", "type": "User"}, "body": "done <!-- swe-workbench:handled:1234 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = aff.compute_pr_comment_eligibility(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[123]["eligible"] is True, (
        "comment 123 must stay eligible — the marker is for a different comment (1234) "
        "that merely shares a numeric prefix"
    )


def test_pr_comments_manual_reply_dedup():
    comments = [
        {"id": 7, "user": {"login": "reviewer4", "type": "User"}, "body": "please fix W", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 8, "user": {"login": "pr-author", "type": "User"}, "body": "thanks, will look", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = aff.compute_pr_comment_eligibility(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[7]["eligible"] is False, (
        "a marker-less owner comment posted after the reviewer comment counts as a "
        "manual reply and must dedup-suppress it"
    )


def test_pr_comments_own_marker_replies_excluded_from_manual_heuristic():
    """A prior marker-bearing tool reply must not itself count as a 'manual reply'
    that over-suppresses a different, still-open reviewer comment posted before it."""
    comments = [
        {"id": 9, "user": {"login": "reviewer5", "type": "User"}, "body": "issue A", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 10, "user": {"login": "reviewer5", "type": "User"}, "body": "issue B", "created_at": "2026-01-01T01:00:00Z"},
        {"id": 11, "user": {"login": "pr-author", "type": "User"}, "body": "done <!-- swe-workbench:handled:10 -->", "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = aff.compute_pr_comment_eligibility(comments, author="pr-author", me="pr-author")
    by_id = {c["id"]: c for c in result}
    assert by_id[10]["eligible"] is False, "comment 10's own marker must dedup-suppress it"
    assert by_id[9]["eligible"] is True, (
        "comment 9 must stay eligible — the only later owner comment is a marker-bearing "
        "tool reply for a different comment, which the manual-reply heuristic must ignore"
    )


# ── Behavioral: call-index-driven gh stub (mirrors test_pr_review_submit_script.py) ──

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


def _run(pr: str, *, stub_dir: Path, state_dir: Path, responses_file: Path,
         extra_args: list[str] | None = None, cwd: Path | None = None):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    env["GH_STUB_STATE"] = str(state_dir)
    env["GH_STUB_RESPONSES"] = str(responses_file)
    # Fresh non-git cwd by default: no origin -> legacy un-scoped paths (what these
    # tests characterize); scoped runs pass --repo explicitly.
    if cwd is None:
        cwd = Path(tempfile.mkdtemp(prefix="aff-nogit-"))
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--pr", pr, *(extra_args or [])],
        capture_output=True, text=True, env=env, cwd=str(cwd),
    )


def _ok(stdout="", exit=0, stderr=""):
    return {"stdout": stdout, "exit": exit, "stderr": stderr}


def _pr_view_response(pr: str, *, state="OPEN", branch="feature-x", author="pr-author"):
    return _ok(json.dumps({
        "state": state, "number": int(pr), "headRefName": branch, "baseRefName": "main",
        "headRefOid": "a" * 40, "title": "t", "body": "b",
        "author": {"login": author}, "reviewDecision": None,
    }))


def _preflight_responses(pr: str, *, state="OPEN", branch="feature-x", author="pr-author", owner="test-owner", repo="test-repo"):
    """The 4 canned gh calls preflight-pr always makes, in order: auth status, pr view,
    repo view --json owner, repo view --json name."""
    return [
        _ok(""),  # auth status
        _pr_view_response(pr, state=state, branch=branch, author=author),  # pr view
        _ok(owner + "\n"),  # repo view --json owner -q .owner.login
        _ok(repo + "\n"),  # repo view --json name -q .name
    ]


def _threads_page_response(nodes: list[dict], *, has_next_page=False, end_cursor=None):
    body = {
        "data": {"repository": {"pullRequest": {"reviewThreads": {
            "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next_page},
            "nodes": nodes,
        }}}}
    }
    return _ok(json.dumps(body))


def _thread_node(*, id, path="a.py", line=1, is_resolved=False, author="reviewer", body="please fix"):
    return {
        "id": id, "isResolved": is_resolved, "path": path, "line": line, "startLine": None,
        "comments": {"nodes": [{"id": f"{id}-c0", "databaseId": 1, "body": body, "author": {"login": author}}]},
    }


def _pr_comments_response(comments: list[dict]):
    return _ok("\n".join(json.dumps(c) for c in comments) + ("\n" if comments else ""))


class TestOpenPrFullFetch:
    def test_pagination_two_pages_of_threads(self, tmp_path):
        pr = _unique_n()
        page1 = _threads_page_response([_thread_node(id="T1")], has_next_page=True, end_cursor="CURSOR1")
        page2 = _threads_page_response([_thread_node(id="T2")], has_next_page=False)
        responses = _preflight_responses(pr) + [_ok("me\n"), page1, page2, _pr_comments_response([])]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["schema"] == "swb.address-feedback-fetch/1"
            assert envelope["status"] == "ok"
            assert envelope["data"]["eligible_threads"] == 2
            threads = json.loads(Path(envelope["data"]["threads_path"]).read_text())
            assert {t["id"] for t in threads} == {"T1", "T2"}
            calls = _gh_calls(state_dir)
            graphql_calls = [c for c in calls if len(c["argv"]) >= 2 and c["argv"][0] == "api" and c["argv"][1] == "graphql"]
            assert len(graphql_calls) == 2, "must issue exactly one gh call per reviewThreads page"
            assert any("after" in a for a in graphql_calls[1]["argv"]), (
                "the second page's call must pass the endCursor from page 1 as -F after=..."
            )
        finally:
            _cleanup_state_files(pr)

    def test_multi_line_rest_comments_all_captured(self, tmp_path):
        pr = _unique_n()
        comments = [
            {"id": 1, "user": {"login": "reviewer1", "type": "User"}, "body": "a", "created_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "user": {"login": "reviewer2", "type": "User"}, "body": "b", "created_at": "2026-01-01T00:00:01Z"},
        ]
        responses = _preflight_responses(pr) + [
            _ok("me\n"), _threads_page_response([]), _pr_comments_response(comments),
        ]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["eligible_pr_comments"] == 2
            written = json.loads(Path(envelope["data"]["pr_comments_path"]).read_text())
            assert {c["id"] for c in written} == {1, 2}
        finally:
            _cleanup_state_files(pr)

    def test_empty_results_nothing_to_address(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [_ok("me\n"), _threads_page_response([]), _pr_comments_response([])]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["eligible_threads"] == 0
            assert envelope["data"]["eligible_pr_comments"] == 0
            assert envelope["data"]["nothing_to_address"] is True
            assert json.loads(Path(envelope["data"]["threads_path"]).read_text()) == []
            assert json.loads(Path(envelope["data"]["pr_comments_path"]).read_text()) == []
        finally:
            _cleanup_state_files(pr)

    def test_nothing_to_address_false_when_any_eligible_item_exists(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [
            _ok("me\n"), _threads_page_response([_thread_node(id="T1")]), _pr_comments_response([]),
        ]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["nothing_to_address"] is False
        finally:
            _cleanup_state_files(pr)

    def test_resume_available_reflects_triage_file_existence(self, tmp_path):
        pr = _unique_n()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"{pr}-triage.json").write_text("{}")
        responses = _preflight_responses(pr) + [_ok("me\n"), _threads_page_response([]), _pr_comments_response([])]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["resume_available"] is True
        finally:
            _cleanup_state_files(pr)

    def test_snapshot_files_written_at_exact_hardcoded_paths(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [_ok("me\n"), _threads_page_response([]), _pr_comments_response([])]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["pr_json_path"] == f"/tmp/swe-workbench-address-feedback/{pr}.json"
            assert envelope["data"]["threads_path"] == f"/tmp/swe-workbench-address-feedback/{pr}-threads.json"
            assert envelope["data"]["pr_comments_path"] == f"/tmp/swe-workbench-address-feedback/{pr}-pr-comments.json"
        finally:
            _cleanup_state_files(pr)


class TestNotOpenShortCircuit:
    def test_closed_pr_skips_paginated_fetch_entirely(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr, state="CLOSED")
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["status"] == "ok"
            assert envelope["data"]["state"] == "CLOSED"
            assert envelope["data"]["threads_path"] == ""
            assert envelope["data"]["pr_comments_path"] == ""
            calls = _gh_calls(state_dir)
            assert len(calls) == 4, (
                f"a non-OPEN PR must stop after preflight's 4 calls (auth/pr-view/repo-view x2), "
                f"got {len(calls)} calls: {calls}"
            )
        finally:
            _cleanup_state_files(pr)

    def test_merged_pr_reports_state_and_pr_level_fields(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr, state="MERGED")
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["state"] == "MERGED"
            assert envelope["data"]["pr_json_path"] == f"/tmp/swe-workbench-address-feedback/{pr}.json"
            assert envelope["data"]["pr_branch"] == "feature-x"
            assert envelope["data"]["nothing_to_address"] is True
        finally:
            _cleanup_state_files(pr)


class TestMalformedApiData:
    def test_non_json_graphql_response_fails_cleanly(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [_ok("me\n"), _ok("not json at all")]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode != 0
            assert result.stdout == ""
            assert "Traceback" not in result.stderr
            assert not (STATE_DIR / f"{pr}-threads.json").exists()
        finally:
            _cleanup_state_files(pr)

    def test_graphql_response_missing_expected_key_fails_cleanly(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [_ok("me\n"), _ok(json.dumps({"data": {"repository": None}}))]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode != 0
            assert result.stdout == ""
            assert "Traceback" not in result.stderr
        finally:
            _cleanup_state_files(pr)

    def test_malformed_pr_comment_line_fails_cleanly(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [_ok("me\n"), _threads_page_response([]), _ok("{not valid json}\n")]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode != 0
            assert result.stdout == ""
            assert "Traceback" not in result.stderr
            assert not (STATE_DIR / f"{pr}-pr-comments.json").exists()
        finally:
            _cleanup_state_files(pr)


class TestPartialNetworkFailure:
    def test_second_threads_page_failure_leaves_no_snapshot_files(self, tmp_path):
        pr = _unique_n()
        page1 = _threads_page_response([_thread_node(id="T1")], has_next_page=True, end_cursor="CURSOR1")
        page2_failure = {"stdout": "", "stderr": "gh: 502 Bad Gateway", "exit": 1}
        responses = _preflight_responses(pr) + [_ok("me\n"), page1, page2_failure]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode != 0
            assert result.stdout == ""
            assert not (STATE_DIR / f"{pr}-threads.json").exists(), (
                "a mid-pagination failure must never leave a partial/truncated snapshot file"
            )
            assert not (STATE_DIR / f"{pr}-pr-comments.json").exists()
        finally:
            _cleanup_state_files(pr)

    def test_pr_comments_fetch_failure_after_threads_succeed_leaves_no_comment_file(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [
            _ok("me\n"), _threads_page_response([]), {"stdout": "", "stderr": "gh: timeout", "exit": 124},
        ]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode != 0
            assert result.stdout == ""
            assert not (STATE_DIR / f"{pr}-pr-comments.json").exists()
        finally:
            _cleanup_state_files(pr)


class TestPreflightFailure:
    def test_auth_failure_exits_nonzero_no_stdout(self, tmp_path):
        pr = _unique_n()
        responses = [{"stdout": "", "stderr": "gh: not authenticated", "exit": 1}]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
            assert result.returncode != 0
            assert result.stdout == ""
            assert "Traceback" not in result.stderr
        finally:
            _cleanup_state_files(pr)


# ── CLI validation ───────────────────────────────────────────────────────────


def test_missing_pr_flag_exits_nonzero():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0


def test_non_integer_pr_exits_nonzero_no_stdout():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--pr", "abc"], capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0
    assert result.stdout == ""


# ── Envelope round-trip through swe-workbench-result-check ───────────────────


def test_envelope_round_trips_through_result_check(tmp_path):
    pr = _unique_n()
    responses = _preflight_responses(pr) + [_ok("me\n"), _threads_page_response([]), _pr_comments_response([])]
    stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
    try:
        result = _run(pr, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json")
        assert result.returncode == 0, result.stderr
        checker = ROOT / "bin" / "swe-workbench-result-check"
        checked = subprocess.run(
            [sys.executable, str(checker), "swb.address-feedback-fetch/1"],
            input=result.stdout, capture_output=True, text=True, env=dict(_CLEAN_ENV),
        )
        assert checked.returncode == 0, checked.stderr
    finally:
        _cleanup_state_files(pr)


# ── Repo-scoped state paths (issue #713) ────────────────────────────────────


class TestRepoScopedState:
    def test_explicit_repo_slugs_all_snapshot_paths(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr) + [_ok("me\n"), _threads_page_response([]), _pr_comments_response([])]
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir,
                          responses_file=tmp_path / "gh_responses.json",
                          extra_args=["--repo", "octocat/widgets"])
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["pr_json_path"] == f"/tmp/swe-workbench-address-feedback/octocat-widgets-{pr}.json"
            assert envelope["data"]["threads_path"] == f"/tmp/swe-workbench-address-feedback/octocat-widgets-{pr}-threads.json"
            assert envelope["data"]["pr_comments_path"] == f"/tmp/swe-workbench-address-feedback/octocat-widgets-{pr}-pr-comments.json"
            assert Path(envelope["data"]["threads_path"]).exists()
            assert Path(envelope["data"]["pr_json_path"]).exists()
        finally:
            for suffix in (".json", "-threads.json", "-pr-comments.json", "-triage.json"):
                (STATE_DIR / f"octocat-widgets-{pr}{suffix}").unlink(missing_ok=True)

    def test_invalid_repo_value_rejected(self, tmp_path):
        pr = _unique_n()
        responses = _preflight_responses(pr, state="MERGED")
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir,
                          responses_file=tmp_path / "gh_responses.json",
                          extra_args=["--repo", "bogus"])
            assert result.returncode == 1
            assert "invalid --repo" in result.stderr
        finally:
            _cleanup_state_files(pr)

    def test_resume_dual_reads_legacy_triage(self, tmp_path):
        """A pre-upgrade session left <N>-triage.json; a scoped run must still
        see the resume point (dual-read), while writing slugged paths."""
        pr = _unique_n()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"{pr}-triage.json").write_text("{}")
        responses = _preflight_responses(pr, state="MERGED")
        stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
        try:
            result = _run(pr, stub_dir=stub_dir, state_dir=state_dir,
                          responses_file=tmp_path / "gh_responses.json",
                          extra_args=["--repo", "octocat/widgets"])
            assert result.returncode == 0, result.stderr
            envelope = json.loads(result.stdout)
            assert envelope["data"]["resume_available"] is True
        finally:
            _cleanup_state_files(pr)
            (STATE_DIR / f"octocat-widgets-{pr}-triage.json").unlink(missing_ok=True)


def test_envelope_exposes_triage_path(tmp_path):
    """The skill's triage save/resume sites need the (possibly slugged) triage
    path without reconstructing naming logic — the envelope is the contract."""
    pr = _unique_n()
    responses = _preflight_responses(pr, state="MERGED")
    stub_dir, state_dir = _write_gh_stub(tmp_path, responses)
    try:
        result = _run(pr, stub_dir=stub_dir, state_dir=state_dir,
                      responses_file=tmp_path / "gh_responses.json",
                      extra_args=["--repo", "octocat/widgets"])
        assert result.returncode == 0, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["data"]["triage_path"] == f"/tmp/swe-workbench-address-feedback/octocat-widgets-{pr}-triage.json"
    finally:
        _cleanup_state_files(pr)
        (STATE_DIR / f"octocat-widgets-{pr}-triage.json").unlink(missing_ok=True)
