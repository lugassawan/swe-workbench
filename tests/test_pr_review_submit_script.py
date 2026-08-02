"""Tests for bin/swe-workbench-pr-review-submit (issue #550). Unit tests import the pure
helpers directly; behavioral tests drive the script as a subprocess against a PATH-scoped,
call-index-driven `gh` stub (extends test_gh_timeout_script.py's stub convention to a
multi-call state machine). `git show`/`swe-workbench-diff-line-lookup` are real, not
stubbed, for line-validation tests, which build a throwaway repo via _init_repo and run
with cwd set to it (test_diff_line_lookup_script.py's precedent).
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-pr-review-submit"

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


def _load_module():
    loader = SourceFileLoader("pr_review_submit", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("pr_review_submit", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pr_review_submit"] = module
    spec.loader.exec_module(module)
    return module


prs = _load_module()


# ── Behavioral test harness ─────────────────────────────────────────────────


def _git(args, *, cwd):
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(cwd), env=dict(_CLEAN_ENV))
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(tmp_path: Path, contents: str = "line1\nline2\nline3\n", filename: str = "src.py") -> str:
    """A throwaway repo with one commit, mirroring test_diff_line_lookup_script.py's precedent."""
    _git(["init", "-b", "main", str(tmp_path)], cwd=tmp_path)
    (tmp_path / filename).write_text(contents)
    _git(["add", filename], cwd=tmp_path)
    _git(["commit", "-m", "initial"], cwd=tmp_path)
    return _git(["rev-parse", "HEAD"], cwd=tmp_path).stdout.strip()


def _write_gh_stub(tmp_path: Path, responses: list[dict]) -> tuple[Path, Path]:
    """Writes the gh stub + its canned responses (at tmp_path/gh_responses.json,
    the fixed path every test's own `responses_file` variable points at)."""
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


def _run(args: list[str], *, cwd: Path, stub_dir: Path, state_dir: Path, responses_file: Path, stdin: str | None = None):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    env["GH_STUB_STATE"] = str(state_dir)
    env["GH_STUB_RESPONSES"] = str(responses_file)
    return subprocess.run(
        [str(SCRIPT), *args],
        input=stdin, capture_output=True, text=True,
        cwd=str(cwd),
        env=env,
    )


def _threads_response(nodes: list[dict], *, has_next_page: bool = False, end_cursor: str | None = None) -> dict:
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
    return {"stdout": json.dumps(body), "exit": 0}


def _thread_node(*, id, path, line, is_resolved=False, body="", author="bob", reactor_logins=None):
    return {
        "id": id, "isResolved": is_resolved, "path": path, "line": line, "startLine": None,
        "comments": {
            "nodes": [{
                "id": f"{id}-c0", "databaseId": 1, "body": body,
                "author": {"login": author},
                "reactions": {"nodes": [{"user": {"login": u}} for u in (reactor_logins or [])]},
            }]
        },
    }


def _repo_view_response(is_private: bool | None) -> dict:
    if is_private is None:
        return {"stdout": "", "stderr": "gh: permission denied", "exit": 1}
    return {"stdout": json.dumps({"isPrivate": is_private}), "exit": 0}


def _review_post_response(*, html_url="https://github.com/o/r/pull/1#pullrequestreview-1", exit=0, stderr=""):
    if exit == 0:
        return {"stdout": json.dumps({"html_url": html_url}), "exit": 0}
    return {"stdout": "", "stderr": stderr, "exit": exit}


_BASE_ARGS = {
    "--repo": "o/r",
    "--pr": "1",
    "--head-sha": "a" * 40,
    "--base": "main",
    "--decision": "COMMENT",
    "--byline": "_Reviewed by `bot`_",
    "--caller-tag": "general",
}


def _args(findings_path, **overrides):
    merged = dict(_BASE_ARGS, **overrides)
    out = []
    for k, v in merged.items():
        out += [k, v]
    out += ["--findings-json", str(findings_path)]
    return out


def _write_findings(tmp_path: Path, findings: list[dict]) -> Path:
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(findings))
    return path


# ── Existence ────────────────────────────────────────────────────────────────


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-pr-review-submit must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-pr-review-submit must be executable (chmod +x)"


# ── Unit: jaccard ────────────────────────────────────────────────────────────


def test_jaccard_empty_body_is_zero():
    assert prs.jaccard("", "something here") == 0.0
    assert prs.jaccard("something here", "") == 0.0


def test_jaccard_disjoint_is_zero():
    assert prs.jaccard("apple banana", "car truck") == 0.0


def test_jaccard_just_below_threshold():
    # {w1 w2 w3 w4 w5} vs {w1 w2 w3 w6 w7 w8}: intersection=3, union=8 -> 0.375 < 0.4
    a = "alpha bravo charlie delta echo"
    b = "alpha bravo charlie foxtrot golf hotel"
    assert prs.jaccard(a, b) == pytest.approx(0.375)
    assert prs.jaccard(a, b) < 0.4


def test_jaccard_at_threshold_boundary():
    # {w1 w2 w3} vs {w1 w2 w4 w5}: intersection=2, union=5 -> exactly 0.4
    a = "alpha bravo charlie"
    b = "alpha bravo delta echo"
    assert prs.jaccard(a, b) == pytest.approx(0.4)


# ── Unit: thread_matches (each of the 4 conjuncts independently) ─────────────


def _thread(**overrides):
    defaults = dict(id="T1", path="src.py", line=10, is_resolved=False, head_comment_id="C1", head_comment_body="alpha bravo charlie")
    defaults.update(overrides)
    return prs.Thread(**defaults)


def test_thread_matches_all_conjuncts_true():
    t = _thread()
    assert prs.thread_matches("src.py", 12, "alpha bravo charlie", t) is True


def test_thread_matches_false_when_resolved():
    t = _thread(is_resolved=True)
    assert prs.thread_matches("src.py", 12, "alpha bravo charlie", t) is False


def test_thread_matches_false_on_different_path():
    t = _thread(path="other.py")
    assert prs.thread_matches("src.py", 12, "alpha bravo charlie", t) is False


def test_thread_matches_false_when_line_delta_exceeds_5():
    t = _thread(line=10)
    assert prs.thread_matches("src.py", 16, "alpha bravo charlie", t) is False
    assert prs.thread_matches("src.py", 15, "alpha bravo charlie", t) is True


def test_thread_matches_false_below_jaccard_threshold():
    t = _thread(head_comment_body="unrelated words entirely")
    assert prs.thread_matches("src.py", 12, "alpha bravo charlie", t) is False


# ── Unit: resolve_event — 24-case truth table ─────────────────────────────────

_IDENTITY_CASES = [
    ("alice", "alice", True, True),   # same login, known -> self-review
    ("alice", "bob", False, True),    # different login, known -> cross-author
    ("", "bob", False, False),        # current empty -> identity unknown
    ("alice", "", False, False),      # author empty -> identity unknown
]


@pytest.mark.parametrize(
    "decision,scope,identity",
    list(itertools.product(("APPROVE", "COMMENT"), ("NONE", "OUT-OF-DIFF-ONLY", "IN-DIFF"), _IDENTITY_CASES)),
)
def test_resolve_event_truth_table(decision, scope, identity):
    current_user, author_login, expect_self, expect_known = identity
    event, out_decision, is_self, known = prs.resolve_event(decision, scope, current_user, author_login)
    assert is_self is expect_self
    assert known is expect_known
    expected_decision = "APPROVE" if (decision == "COMMENT" and scope == "OUT-OF-DIFF-ONLY" and expect_known and not expect_self) else decision
    assert out_decision == expected_decision
    expected_event = "COMMENT" if expect_self else expected_decision
    assert event == expected_event


def test_resolve_event_identity_unknown_suppresses_flip():
    """Fail-safe: never auto-approve when authorship can't be verified."""
    event, decision, is_self, known = prs.resolve_event("COMMENT", "OUT-OF-DIFF-ONLY", "", "bob")
    assert known is False
    assert decision == "COMMENT", "flip must not fire when identity is unknown"
    assert event == "COMMENT"


def test_resolve_event_self_review_never_yields_approve():
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "alice")
    assert is_self is True
    assert event == "COMMENT", "self-review must never submit APPROVE"


# ── Unit: build_byline / build_summary ────────────────────────────────────────


def test_build_byline_public_repo_includes_remark():
    result = prs.build_byline("_Reviewed by `bot`_", False, 2, 1, 3)
    assert prs.REMARK_TEXT in result
    assert "Posted 2 inline comment(s) and 1 PR-level note(s), deduped 3." in result


def test_build_byline_private_repo_omits_remark():
    result = prs.build_byline("_Reviewed by `bot`_", True, 2, 1, 3)
    assert prs.REMARK_TEXT not in result


def test_build_byline_lookup_failed_omits_remark_failsafe():
    result = prs.build_byline("_Reviewed by `bot`_", None, 0, 0, 0)
    assert prs.REMARK_TEXT not in result


def test_build_summary_self_review_omits_decision_line():
    summary = prs.build_summary("APPROVE", "byline text", True)
    assert "Review Decision" not in summary
    assert summary.strip() == "byline text"


def test_build_summary_non_self_review_includes_decision_line():
    summary = prs.build_summary("COMMENT", "byline text", False)
    assert "**Review Decision: COMMENT**" in summary
    assert "byline text" in summary


# ── Unit: partition_findings ──────────────────────────────────────────────────


def test_partition_findings_splits_by_anchor():
    findings = [
        {"anchor": "inline", "body": "a"},
        {"anchor": "pr-level", "body": "b"},
        {"anchor": "inline", "body": "c"},
    ]
    inline, pr_level = prs.partition_findings(findings)
    assert [f["body"] for f in inline] == ["a", "c"]
    assert [f["body"] for f in pr_level] == ["b"]


# ── Behavioral: input-contract validation aborts before any network call ──────


def test_invalid_decision_aborts_with_message_and_no_findings_read(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "MAYBE"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode != 0
    assert "workflow-pr-review-post: invalid payload — --decision" in result.stderr
    assert "Refusing to post." in result.stderr
    assert _gh_calls(state_dir) == [], "no gh call may occur when validation fails"


@pytest.mark.parametrize(
    "field,value",
    [
        ("--repo", "not-owner-slash-repo"),
        ("--pr", "0"),
        ("--pr", "abc"),
        ("--head-sha", "tooshort"),
        ("--base", ""),
        ("--byline", ""),
        ("--caller-tag", ""),
        ("--blocking-scope", "SOMETHING-ELSE"),
    ],
)
def test_each_invalid_field_aborts_before_any_gh_call(tmp_path, field, value):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    args = _args(findings, **{field: value})
    result = _run(args, cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0, f"{field}={value!r} must abort"
    assert "invalid payload" in result.stderr
    assert _gh_calls(state_dir) == []


@pytest.mark.parametrize(
    "byline",
    [
        "_Reviewed by `bot`_ ([swe-workbench](https://github.com/lugassawan/swe-workbench))",
        "_Reviewed by `bot`_. Posted 3 inline comment(s)",
        "_Reviewed by `bot`_, deduped 2.",
    ],
)
def test_byline_forbidden_content_aborts(tmp_path, byline):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--byline": byline}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode != 0
    assert "--byline" in result.stderr
    assert _gh_calls(state_dir) == []


def test_inline_finding_missing_path_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [{"severity": "High", "body": "x", "anchor": "inline", "line": 3}])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0
    assert "--findings-json[0]" in result.stderr
    assert _gh_calls(state_dir) == []


def test_finding_body_embedding_remark_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [{
        "severity": "High",
        "body": f"nice work {prs.REMARK_TEXT}",
        "anchor": "pr-level",
    }])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0
    assert "--findings-json[0]" in result.stderr
    assert _gh_calls(state_dir) == []


def test_check_siblings_raises_on_missing_sibling(tmp_path):
    with pytest.raises(prs.PostingError):
        prs._check_siblings(tmp_path)


def test_malformed_findings_json_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    result = _run(_args(bad), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0
    assert "--findings-json" in result.stderr
    assert _gh_calls(state_dir) == []


def test_findings_json_via_stdin(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff (no inline findings, content irrelevant)
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    args = _args("-", **{"--decision": "APPROVE"})
    result = _run(
        args, cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
        stdin=json.dumps([]),
    )
    assert result.returncode == 0, result.stderr
    assert "POSTED_INLINE=0" in result.stdout


# ── Behavioral: dedup + reactions ─────────────────────────────────────────────


def test_dedup_match_adds_one_reaction_and_posts_nothing(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, body="alpha bravo charlie", reactor_logins=[])
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([node]),
            {"stdout": "", "exit": 0},  # addReaction mutation
            {"stdout": "", "exit": 0},  # pr diff
            _repo_view_response(True),
            _review_post_response(),  # N=0 -> falls through to plain review submit
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "alpha bravo charlie", "anchor": "inline", "path": "src.py", "line": 12},
    ])
    result = _run(
        _args(findings, **{"--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "DEDUPED=1" in result.stdout
    assert "POSTED_INLINE=0" in result.stdout
    calls = _gh_calls(state_dir)
    reaction_calls = [c for c in calls if "addReaction(input:" in json.dumps(c["argv"])]
    assert len(reaction_calls) == 1, f"expected exactly one addReaction call, got calls={calls}"


def test_already_reacted_thread_adds_no_reaction(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, body="alpha bravo charlie", reactor_logins=["alice"])
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([node]),
            {"stdout": "", "exit": 0},  # pr diff
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "alpha bravo charlie", "anchor": "inline", "path": "src.py", "line": 12},
    ])
    result = _run(
        _args(findings, **{"--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    reaction_calls = [c for c in calls if "addReaction(input:" in json.dumps(c["argv"])]
    assert reaction_calls == [], "must not react again when current_user already reacted"


def test_pagination_follows_has_next_page_across_two_pages(tmp_path):
    node_a = _thread_node(id="PRRT_A", path="src.py", line=10, body="alpha bravo charlie")
    node_b = _thread_node(id="PRRT_B", path="src.py", line=20, body="delta echo foxtrot")
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([node_a], has_next_page=True, end_cursor="CURSOR1"),
            _threads_response([node_b], has_next_page=False),
            {"stdout": "", "exit": 0},  # pr diff
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    threads_calls = [c for c in calls if "reviewThreads(first:" in json.dumps(c["argv"])]
    assert len(threads_calls) == 2, f"expected two paginated threads fetch calls, got {calls}"
    assert "after=CURSOR1" in json.dumps(threads_calls[1]["argv"])


# ── Behavioral: pre-validate / demote out-of-diff findings ───────────────────


def test_out_of_diff_row_is_demoted_never_dropped(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},  # pr diff
            {"stdout": "", "exit": 0},  # pr comment (demoted batch, one call)
            _repo_view_response(True),
            _review_post_response(),  # N=0 (the only inline row was demoted)
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "out of diff finding", "anchor": "inline", "path": "src.py", "line": 999},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "POSTED_PR_LEVEL=1" in result.stdout
    assert "POSTED_INLINE=0" in result.stdout
    calls = _gh_calls(state_dir)
    pr_comment_calls = [c for c in calls if c["argv"][:2] == ["pr", "comment"]]
    assert len(pr_comment_calls) == 1, "demoted findings must batch into exactly one gh pr comment call"


def test_failing_pr_level_batch_leaves_posted_pr_level_zero(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff
            {"stdout": "", "stderr": "gh: connection reset", "exit": 1},  # pr comment fails
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "Low", "body": "a dependency finding", "anchor": "pr-level"},
    ])
    result = _run(
        _args(findings),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "POSTED_PR_LEVEL=0" in result.stdout


# ── Behavioral: atomic submit / 422 / 5xx / model-A fallback ─────────────────


def test_atomic_post_carries_candidate_count_in_body(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "issue on line2", "anchor": "inline", "path": "src.py", "line": 2},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "POSTED_INLINE=1" in result.stdout
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert "Posted 1 inline comment(s)" in payload["body"], payload["body"]
    assert payload["comments"][0]["body"] == "issue on line2"


def test_confirmed_422_retries_once_demotes_and_posts_second_review(tmp_path):
    head = _init_repo(tmp_path)
    # A real second commit — src.py unchanged, so re-validating against it still resolves
    # line 2 in-diff (the point under test is the single-retry mechanics, not a content change).
    (tmp_path / "other.txt").write_text("noop\n")
    _git(["add", "other.txt"], cwd=tmp_path)
    _git(["commit", "-m", "second"], cwd=tmp_path)
    new_head = _git(["rev-parse", "HEAD"], cwd=tmp_path).stdout.strip()
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},  # pr diff
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 422: Unprocessable Entity", "exit": 1},  # first atomic POST 422s
            {"stdout": json.dumps({"headRefOid": new_head}), "exit": 0},  # re-fetch HEAD
            _review_post_response(),  # retry POST succeeds
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "issue on line2", "anchor": "inline", "path": "src.py", "line": 2},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "SUBMITTED=true" in result.stdout
    assert "POSTED_INLINE=1" in result.stdout
    calls = _gh_calls(state_dir)
    post_calls = [c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"]]
    assert len(post_calls) == 2, "a confirmed 422 must retry exactly once"
    head_view_calls = [c for c in calls if c["argv"][:2] == ["pr", "view"]]
    assert len(head_view_calls) == 1


def test_double_422_falls_through_to_per_comment_model_a(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # first atomic POST 422s
            {"stdout": json.dumps({"headRefOid": head}), "exit": 0},  # re-fetch HEAD (unchanged)
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # retry POST 422s again
            {"stdout": "[]", "exit": 0},  # read-your-write list: nothing landed
            {"stdout": "", "exit": 0},  # per-comment fallback POST succeeds
            _review_post_response(),  # final plain review submit
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "issue on line2", "anchor": "inline", "path": "src.py", "line": 2},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "POSTED_INLINE=1" in result.stdout
    assert "SUBMITTED=true" in result.stdout
    calls = _gh_calls(state_dir)
    per_comment_calls = [c for c in calls if "/comments" in json.dumps(c["argv"]) and c["argv"][0] == "api"]
    assert len(per_comment_calls) == 1


def test_5xx_issues_zero_retries_and_one_read_your_write_call(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 503: Service Unavailable", "exit": 1},  # network/5xx
            {"stdout": "[]", "exit": 0},  # read-your-write: nothing landed
            {"stdout": "", "exit": 0},  # per-comment fallback POST succeeds
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "issue on line2", "anchor": "inline", "path": "src.py", "line": 2},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    # Scoped to payloads carrying comments[] — the model-A fallback's own final decision-only
    # POST hits the same endpoint with the same flags but is a distinct event, not a retry.
    atomic_post_calls = [
        c for c in calls
        if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"] and "comments" in json.loads(c["stdin"])
    ]
    assert len(atomic_post_calls) == 1, "network/5xx must never blind-retry the atomic POST"
    list_calls = [
        c for c in calls
        if c["argv"][0] == "api" and c["argv"][1] == "repos/o/r/pulls/1/reviews" and len(c["argv"]) == 2
    ]
    assert len(list_calls) == 1, f"expected exactly one read-your-write list call, got {calls}"


def test_confirmed_landed_5xx_reports_submitted_without_reposting(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    landed_url = "https://github.com/o/r/pull/1#pullrequestreview-999"
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "connection reset by peer", "exit": 1},  # ambiguous network failure
            {"stdout": json.dumps([{"user": {"login": "alice"}, "commit_id": head, "html_url": landed_url}]), "exit": 0},
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": "issue on line2", "anchor": "inline", "path": "src.py", "line": 2},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "SUBMITTED=true" in result.stdout
    assert "POSTED_INLINE=1" in result.stdout
    assert landed_url.replace(":", "\\:") in result.stdout or landed_url in result.stdout
    calls = _gh_calls(state_dir)
    post_calls = [c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"]]
    assert len(post_calls) == 1, "a confirmed read-your-write landing must not trigger a repost"


def test_self_review_submits_comment_event_never_approve(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE", "--current-user": "alice", "--author-login": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert "EVENT=COMMENT" in result.stdout
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert payload["event"] == "COMMENT"


def test_body_with_quotes_backslash_and_leading_at_survives_byte_identical(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    hazardous_body = '@author said "this" is \\wrong\\'
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        {"severity": "High", "body": hazardous_body, "anchor": "inline", "path": "src.py", "line": 2},
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert payload["comments"][0]["body"] == hazardous_body


def test_n_zero_skips_atomic_post_entirely(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff
            _repo_view_response(True),
            _review_post_response(),  # the only /reviews POST call — no comments key
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    post_calls = [c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"]]
    assert len(post_calls) == 1
    payload = json.loads(post_calls[0]["stdin"])
    assert "comments" not in payload
