"""Tests for bin/swe-workbench-pr-review-submit (issue #550). Unit tests import the pure
helpers directly; behavioral tests drive the script as a subprocess against a PATH-scoped,
call-index-driven `gh` stub (extends test_gh_timeout_script.py's stub convention to a
multi-call state machine). `git show`/`swe-workbench-diff-line-lookup` are real, not
stubbed, for line-validation tests, which build a throwaway repo via _init_repo and run
with cwd set to it (test_diff_line_lookup_script.py's precedent).

The `printf %q`-quoted `KEY=VALUE` stdout contract was later replaced with the standard
JSON envelope (schema `swb.pr-review-submit/1`, see shared/docs/runtime-result-contract.md)
— `_data(result)` reads `.data` from the parsed envelope in place of the old
`"KEY=value" in result.stdout` substring checks.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import re
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
routes_file = os.environ.get("GH_STUB_ROUTES", "")
routes = json.load(open(routes_file)) if routes_file and os.path.exists(routes_file) else {}
argv = sys.argv[1:]
stdin_data = sys.stdin.read()


def bump(name):
    path = os.path.join(state_dir, name)
    n = int(open(path).read()) if os.path.exists(path) else 0
    open(path, "w").write(str(n + 1))
    return n


def route_key(args):
    if args and args[0] == "api":
        method, path, i = "GET", "", 1
        while i < len(args):
            if args[i] in ("--method", "-X") and i + 1 < len(args):
                method, i = args[i + 1], i + 2
                continue
            if not args[i].startswith("-") and not path:
                path = args[i]
            i += 1
        return f"{method} {path}"
    return " ".join(args[:2])


key = route_key(argv)
seq = bump("seq")
if key in routes:
    # Route-keyed responses are consumed in order (the last one repeats) and logged apart from
    # the positional queue, so adding a read never shifts the call-N.json indices.
    n = bump("route-count-" + key.replace("/", "_").replace(" ", "_"))
    route_i = bump("route-log-count")
    with open(os.path.join(state_dir, f"route-call-{route_i}.json"), "w") as f:
        json.dump({"argv": argv, "stdin": stdin_data, "route": key, "seq": seq}, f)
    seq_resp = routes[key]
    resp = seq_resp[min(n, len(seq_resp) - 1)]
else:
    i = bump("count")
    with open(os.path.join(state_dir, f"call-{i}.json"), "w") as f:
        json.dump({"argv": argv, "stdin": stdin_data, "seq": seq}, f)
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


_EMPTY_LIST_READ = [{"stdout": "", "exit": 0}]
# Reads every run now makes; served by route so they never shift the positional queue.
_DEFAULT_ROUTES = {
    "GET repos/o/r/pulls/1/reviews": _EMPTY_LIST_READ,
    "GET repos/o/r/issues/1/comments": _EMPTY_LIST_READ,
}


def _write_gh_stub(tmp_path: Path, responses: list[dict], routes: dict[str, list[dict]] | None = None) -> tuple[Path, Path]:
    """Writes the gh stub + its canned responses (at tmp_path/gh_responses.json,
    the fixed path every test's own `responses_file` variable points at).

    `routes` maps "METHOD path" (or "cmd subcmd" for non-api calls) to a response sequence
    that is checked before the positional queue; it overrides the empty-list defaults for
    the review and issue-comment list reads."""
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "gh"
    stub.write_text(STUB_BODY)
    stub.chmod(0o755)
    state_dir = tmp_path / "gh_state"
    state_dir.mkdir(exist_ok=True)
    (tmp_path / "gh_responses.json").write_text(json.dumps(responses))
    (tmp_path / "gh_routes.json").write_text(json.dumps({**_DEFAULT_ROUTES, **(routes or {})}))
    return stub_dir, state_dir


def _data(result: subprocess.CompletedProcess) -> dict:
    """Parses the standard envelope from a successful run's stdout and returns `.data`."""
    return json.loads(result.stdout)["data"]


def _gh_calls(state_dir: Path) -> list[dict]:
    calls = []
    i = 0
    while (state_dir / f"call-{i}.json").exists():
        calls.append(json.loads((state_dir / f"call-{i}.json").read_text()))
        i += 1
    return calls


def _routed_calls(state_dir: Path) -> list[dict]:
    """Calls served by a route (not the positional queue), in arrival order."""
    calls = []
    i = 0
    while (state_dir / f"route-call-{i}.json").exists():
        calls.append(json.loads((state_dir / f"route-call-{i}.json").read_text()))
        i += 1
    return calls


def _all_calls(state_dir: Path) -> list[dict]:
    """Positional and routed calls merged into arrival order."""
    return sorted(_gh_calls(state_dir) + _routed_calls(state_dir), key=lambda call: call["seq"])


def _is_mutating(call: dict) -> bool:
    argv = call["argv"]
    if argv[:2] == ["pr", "comment"] or argv[:2] == ["pr", "review"]:
        return True
    if argv[:1] != ["api"]:
        return False
    text = json.dumps(argv)
    if "mutation" in text:
        return True
    return any(flag in argv for flag in ("--method", "-X")) and "GET" not in argv


def _mutating_calls(state_dir: Path) -> list[dict]:
    return [call for call in _all_calls(state_dir) if _is_mutating(call)]


def _run(args: list[str], *, cwd: Path, stub_dir: Path, state_dir: Path, responses_file: Path, stdin: str | None = None):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    env["GH_STUB_STATE"] = str(state_dir)
    env["GH_STUB_RESPONSES"] = str(responses_file)
    env["GH_STUB_ROUTES"] = str(responses_file.with_name("gh_routes.json"))
    return subprocess.run(
        [str(SCRIPT), *args],
        input=stdin, capture_output=True, text=True,
        cwd=str(cwd),
        env=env,
    )


def _row(**overrides) -> dict:
    """A valid structured inline finding row; override any field, or pass None to drop one."""
    row = {
        "severity": "High", "issue": "issue on line2", "why": "why", "fix": "fix",
        "anchor": "inline", "path": "src.py", "line": 2,
    }
    row.update(overrides)
    return {k: v for k, v in row.items() if v is not None}


def _key_line(row: dict, anchor_text: str) -> str:
    """The trailing finding-key marker line a posted row carries."""
    return f"<!-- swe-workbench:finding-key:v1:{prs.finding_key(row, anchor_text)} -->"


_DEDUP_ROW = _row(issue="alpha bravo charlie", why="delta echo foxtrot", fix="golf hotel india", line=12)


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


def _thread_node(*, id, path, line, is_resolved=False, is_outdated=False, body="", author="bob", reactor_logins=None):
    return {
        "id": id, "isResolved": is_resolved, "isOutdated": is_outdated, "path": path, "line": line, "startLine": None,
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


# ── Stub infra: route-keyed responses leave positional indices alone ──────────


def _stub_call(stub_dir, state_dir, tmp_path, *argv):
    env = dict(_CLEAN_ENV)
    env.update(
        GH_STUB_STATE=str(state_dir),
        GH_STUB_RESPONSES=str(tmp_path / "gh_responses.json"),
        GH_STUB_ROUTES=str(tmp_path / "gh_routes.json"),
    )
    return subprocess.run([str(stub_dir / "gh"), *argv], capture_output=True, text=True, env=env, input="")


def test_routed_reads_do_not_consume_or_shift_the_positional_queue(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [{"stdout": "first", "exit": 0}],
        routes={"GET repos/o/r/pulls/1/reviews": [{"stdout": "a", "exit": 0}, {"stdout": "b", "exit": 0}]},
    )
    reviews = ("api", "--paginate", "repos/o/r/pulls/1/reviews")
    assert _stub_call(stub_dir, state_dir, tmp_path, *reviews).stdout == "a"
    assert _stub_call(stub_dir, state_dir, tmp_path, "pr", "diff", "1").stdout == "first"
    assert _stub_call(stub_dir, state_dir, tmp_path, *reviews).stdout == "b"
    assert _stub_call(stub_dir, state_dir, tmp_path, *reviews).stdout == "b", "last route response repeats"
    assert [c["argv"][:2] for c in _gh_calls(state_dir)] == [["pr", "diff"]]
    assert len(_routed_calls(state_dir)) == 3
    assert [c["argv"][0] for c in _all_calls(state_dir)] == ["api", "pr", "api", "api"]


def test_default_routes_serve_empty_review_and_issue_comment_lists(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    for path in ("repos/o/r/pulls/1/reviews", "repos/o/r/issues/1/comments"):
        proc = _stub_call(stub_dir, state_dir, tmp_path, "api", path)
        assert (proc.returncode, proc.stdout) == (0, "")
    assert _gh_calls(state_dir) == []


def test_post_calls_are_classified_as_mutating_and_reads_are_not(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [{"stdout": "", "exit": 0}] * 3)
    _stub_call(stub_dir, state_dir, tmp_path, "api", "repos/o/r/pulls/1/reviews")
    _stub_call(stub_dir, state_dir, tmp_path, "api", "--method", "POST", "repos/o/r/pulls/1/reviews", "--input", "-")
    _stub_call(stub_dir, state_dir, tmp_path, "pr", "comment", "1", "--body", "x")
    _stub_call(stub_dir, state_dir, tmp_path, "pr", "diff", "1")
    assert [c["argv"][:2] for c in _mutating_calls(state_dir)] == [["api", "--method"], ["pr", "comment"]]


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


# ── Unit: blocking_threads ─────────────────────────────────────────────────────


def test_blocking_threads_excludes_resolved():
    threads = [_thread(id="T1", is_resolved=True)]
    assert prs.blocking_threads(threads) == []


def test_blocking_threads_excludes_outdated():
    threads = [_thread(id="T1", is_outdated=True)]
    assert prs.blocking_threads(threads) == []


def test_blocking_threads_includes_plain_unresolved_non_outdated():
    threads = [_thread(id="T1")]
    assert prs.blocking_threads(threads) == threads


def test_blocking_threads_empty_list_returns_empty():
    assert prs.blocking_threads([]) == []


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


# ── Unit: resolve_event — n_blocking_threads downgrade ─────────────────────────


def test_resolve_event_blocking_threads_downgrades_approve_to_comment():
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "bob", 1)
    assert decision == "COMMENT"
    assert event == "COMMENT"


def test_resolve_event_zero_blocking_threads_leaves_approve_untouched():
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "bob", 0)
    assert decision == "APPROVE"
    assert event == "APPROVE"


def test_resolve_event_default_n_blocking_threads_preserves_existing_truth_table():
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "bob")
    assert decision == "APPROVE"
    assert event == "APPROVE"


def test_resolve_event_blocking_downgrade_wins_over_out_of_diff_upgrade():
    """COMMENT + OUT-OF-DIFF-ONLY upgrades to APPROVE; blocking threads must downgrade it
    back to COMMENT — the downgrade is applied after the upgrade (ordering)."""
    event, decision, is_self, known = prs.resolve_event("COMMENT", "OUT-OF-DIFF-ONLY", "alice", "bob", 1)
    assert decision == "COMMENT"
    assert event == "COMMENT"


def test_resolve_event_self_review_with_blocking_threads_downgrades_decision_too():
    """Self-review already forces `event` to COMMENT regardless of `decision` — but the
    blocking-threads downgrade must still apply to `decision` itself (not just `event`),
    since callers read `decision`, not `event`, to tell whether anything is left to
    address."""
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "alice", 1)
    assert is_self is True
    assert decision == "COMMENT", "decision must be downgraded even under self-review"
    assert event == "COMMENT"


# ── Unit: resolve_event — override ─────────────────────────────────────────────


def test_resolve_event_override_prevents_blocking_downgrade():
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "bob", 1, override=True)
    assert decision == "APPROVE"
    assert event == "APPROVE"


def test_resolve_event_override_with_zero_blocking_threads_is_a_no_op():
    """No blocking threads means there's nothing to override — override=True must behave
    identically to override=False."""
    with_override = prs.resolve_event("APPROVE", "NONE", "alice", "bob", 0, override=True)
    without_override = prs.resolve_event("APPROVE", "NONE", "alice", "bob", 0, override=False)
    assert with_override == without_override
    assert with_override[1] == "APPROVE"


def test_resolve_event_override_does_not_defeat_self_review_clamp():
    """The override bypasses exactly the thread-count downgrade — it must never let a
    self-authored review submit as APPROVE. Under self-review, override has zero effect
    on either `event` or `decision`: callers read `decision`, not `event`, to tell
    whether anything is left to address, so `decision` must be downgraded too, not
    just `event`."""
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "alice", 1, override=True)
    assert is_self is True
    assert event == "COMMENT", "self-review must never submit APPROVE, override or not"
    assert decision == "COMMENT", "override must not defeat the self-review clamp on decision either"


def test_resolve_event_default_override_preserves_existing_truth_table_row():
    """Calling resolve_event with the exact positional args a pre-override test used must
    yield identical output — the new `override` parameter's default must not shift behavior."""
    event, decision, is_self, known = prs.resolve_event("APPROVE", "NONE", "alice", "bob", 1)
    assert decision == "COMMENT"
    assert event == "COMMENT"


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


def test_build_summary_override_note_appears_when_set_and_not_self_review():
    summary = prs.build_summary("APPROVE", "byline text", False, override_note="verified manually", n_blocking=2)
    assert "**Review Decision: APPROVE**" in summary
    assert "Approved with 2 unresolved review thread(s) still open" in summary
    assert "override: verified manually" in summary


def test_build_summary_no_override_note_when_not_set():
    summary = prs.build_summary("APPROVE", "byline text", False)
    assert "override:" not in summary


def test_build_summary_self_review_omits_override_note_even_if_passed():
    """Defensive: even a caller misuse (passing override_note under self-review) must not
    produce a summary that references 'Approved' when no decision line was even printed."""
    summary = prs.build_summary("APPROVE", "byline text", True, override_note="verified manually", n_blocking=2)
    assert summary.strip() == "byline text"
    assert "override:" not in summary


# ── Unit: partition_findings ──────────────────────────────────────────────────


def test_partition_findings_splits_by_anchor():
    findings = [
        {"anchor": "inline", "issue": "a"},
        {"anchor": "pr-level", "issue": "b"},
        {"anchor": "inline", "issue": "c"},
    ]
    inline, pr_level = prs.partition_findings(findings)
    assert [f["issue"] for f in inline] == ["a", "c"]
    assert [f["issue"] for f in pr_level] == ["b"]


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


def test_approve_over_open_threads_multiline_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--approve-over-open-threads": "line one\nline two"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode != 0
    assert "--approve-over-open-threads" in result.stderr
    assert "single line" in result.stderr
    assert _gh_calls(state_dir) == []


def test_approve_over_open_threads_over_200_chars_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--approve-over-open-threads": "x" * 201}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode != 0
    assert "--approve-over-open-threads" in result.stderr
    assert "200 characters" in result.stderr
    assert _gh_calls(state_dir) == []


def test_approve_over_open_threads_embedding_remark_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--approve-over-open-threads": f"verified {prs.REMARK_TEXT}"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode != 0
    assert "--approve-over-open-threads" in result.stderr
    assert "swe-workbench remark" in result.stderr
    assert _gh_calls(state_dir) == []


def test_approve_over_open_threads_valid_reason_flows_to_envelope(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE", "--approve-over-open-threads": "verified manually"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    data = _data(result)
    assert data["approve_over_open_threads"] is True
    assert data["override_reason"] == "verified manually"


def test_inline_finding_missing_path_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [_row(path=None, line=3)])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0
    assert "--findings-json[0]" in result.stderr
    assert _gh_calls(state_dir) == []


def test_finding_body_embedding_remark_aborts(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [_row(issue=f"nice work {prs.REMARK_TEXT}", anchor="pr-level")])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0
    assert "--findings-json[0].issue" in result.stderr
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
    assert _data(result)["posted_inline"] == 0


# ── Behavioral: dedup + reactions ─────────────────────────────────────────────


def test_dedup_match_adds_one_reaction_and_posts_nothing(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, body=prs.render_finding(_DEDUP_ROW, False), reactor_logins=[])
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
        _DEDUP_ROW,
    ])
    result = _run(
        _args(findings, **{"--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["deduped"] == 1
    assert _data(result)["posted_inline"] == 0
    calls = _gh_calls(state_dir)
    reaction_calls = [c for c in calls if "addReaction(input:" in json.dumps(c["argv"])]
    assert len(reaction_calls) == 1, f"expected exactly one addReaction call, got calls={calls}"


def test_already_reacted_thread_adds_no_reaction(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, body=prs.render_finding(_DEDUP_ROW, False), reactor_logins=["alice"])
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
        _DEDUP_ROW,
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


def test_failed_pr_diff_fetch_aborts_loudly_instead_of_silent_demotion(tmp_path):
    """A failed `gh pr diff` must not silently flow an empty diff into validate_lines and
    demote every inline finding to one pr-level comment with no signal (PR #580 review fix)."""
    stub_dir, state_dir = _write_gh_stub(tmp_path, [
        _threads_response([]),
        {"stdout": "", "stderr": "gh: connection reset", "exit": 1},  # pr diff fails
    ])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
    ])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode != 0
    assert "failed to fetch PR diff" in result.stderr
    calls = _gh_calls(state_dir)
    assert len(calls) == 2, "must abort immediately after the failed pr diff call, no further gh calls"


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
        _row(issue="out of diff finding", line=999),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 1
    assert _data(result)["posted_inline"] == 0
    calls = _gh_calls(state_dir)
    pr_comment_calls = [c for c in calls if c["argv"][:2] == ["pr", "comment"]]
    assert len(pr_comment_calls) == 1, "demoted findings must batch into exactly one gh pr comment call"
    body = pr_comment_calls[0]["argv"][pr_comment_calls[0]["argv"].index("--body") + 1]
    assert body == (
        "<!-- swe-workbench:review-findings -->\n\n"
        "<!-- swe-workbench:review-finding:1 -->\n"
        "**High** · `src.py:999` — out of diff finding\n\n**Why it matters:** why\n\n**Suggested fix:** fix\n"
        + _key_line(_row(issue="out of diff finding", line=999), "")
    ), "a demoted row must gain its path:line and retain its provenance marker"


def test_middle_pr_level_batch_failure_continues_and_counts_successful_chunks(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff
            {"stdout": "", "exit": 0},  # first 50-row chunk
            {"stdout": "", "stderr": "gh: connection reset", "exit": 1},  # second chunk
            {"stdout": "", "exit": 0},  # final one-row chunk
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(issue=f"pr-level {index}", anchor="pr-level", path=None, line=None)
        for index in range(101)
    ])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)

    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 51
    assert _data(result)["submitted"] is True
    assert "chunk of 50 finding(s) NOT posted" in result.stderr
    assert len([call for call in _gh_calls(state_dir) if call["argv"][:2] == ["pr", "comment"]]) == 3


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
        _row(severity="Low", issue="a dependency finding", anchor="pr-level", path=None, line=None),
    ])
    result = _run(
        _args(findings),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 0


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
        _row(),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_inline"] == 1
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert "Posted 1 inline comment(s)" in payload["body"], payload["body"]
    assert payload["comments"][0]["body"] == (
        "<!-- swe-workbench:review-finding:1 -->\n"
        "**High** — issue on line2\n\n**Why it matters:** why\n\n**Suggested fix:** fix\n"
        + _key_line(_row(), "line2")
    )


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
            {"stdout": pr_diff, "exit": 0},  # re-fetch PR diff alongside HEAD
            _review_post_response(),  # retry POST succeeds
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["submitted"] == True
    assert _data(result)["posted_inline"] == 1
    calls = _gh_calls(state_dir)
    post_calls = [c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"]]
    assert len(post_calls) == 2, "a confirmed 422 must retry exactly once"
    head_view_calls = [c for c in calls if c["argv"][:2] == ["pr", "view"]]
    assert len(head_view_calls) == 1
    diff_calls = [c for c in calls if c["argv"][:2] == ["pr", "diff"]]
    assert len(diff_calls) == 2, "the 422 retry must re-fetch the PR diff alongside HEAD, not reuse the stale one"


def test_422_retry_demotes_one_of_two_findings_and_preserves_ordinals(tmp_path):
    """Ordinal stability through 422 re-validation with a partial demotion: the
    surviving inline row keeps ID 1 and the demoted row keeps ID 2 — no
    renumbering of either after the partition moves between buckets."""
    head = _init_repo(tmp_path)
    hunk = (
        "diff --git a/src.py b/src.py\nindex e69de29..1234567 100644\n--- a/src.py\n+++ b/src.py\n"
    )
    diff_before = hunk + "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n"
    diff_after = hunk + "@@ -0,0 +1,2 @@\n+line1\n+line2\n"  # line 3 left the diff
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": diff_before, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 422: Unprocessable Entity", "exit": 1},  # atomic POST 422s
            {"stdout": json.dumps({"headRefOid": head}), "exit": 0},  # re-fetch HEAD
            {"stdout": diff_after, "exit": 0},  # re-fetch PR diff
            _review_post_response(),  # retry POST succeeds with the surviving row
            {"stdout": "", "exit": 0},  # pr comment carrying the demoted row
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(issue="issue on line2", line=2),
        _row(issue="issue on line3", line=3),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_inline"] == 1
    assert _data(result)["posted_pr_level"] == 1
    calls = _gh_calls(state_dir)
    post_calls = [c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"]]
    retry_payload = json.loads(post_calls[-1]["stdin"])
    assert len(retry_payload["comments"]) == 1
    assert retry_payload["comments"][0]["body"].startswith("<!-- swe-workbench:review-finding:1 -->\n")
    assert "review-finding:2" not in post_calls[-1]["stdin"]
    pr_comment = next(c for c in calls if c["argv"][:2] == ["pr", "comment"])
    body = pr_comment["argv"][pr_comment["argv"].index("--body") + 1]
    assert body.startswith(
        "<!-- swe-workbench:review-findings -->\n\n<!-- swe-workbench:review-finding:2 -->\n"
        "**High** · `src.py:3` — issue on line3\n\n"
    )
    assert "review-finding:1" not in body


def test_422_retry_falls_back_to_stale_diff_when_refetch_fails(tmp_path):
    """A refetch failure during the 422 retry is a degraded retry, not a foundational one —
    it must warn and fall back to the stale diff (PR #580 followup review fix) rather than
    aborting an in-flight submission."""
    head = _init_repo(tmp_path)
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
            {"stdout": "", "stderr": "gh: rate limited", "exit": 1},  # PR diff re-fetch fails
            _review_post_response(),  # retry POST succeeds, using the stale diff
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["submitted"] == True
    assert _data(result)["posted_inline"] == 1
    assert "PR diff re-fetch failed during 422 retry — reusing the pre-retry diff: gh: rate limited" in result.stderr


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
            {"stdout": pr_diff, "exit": 0},  # re-fetch PR diff alongside HEAD
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # retry POST 422s again
            {"stdout": "", "exit": 0},  # per-comment fallback POST succeeds
            _review_post_response(),  # final plain review submit
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_inline"] == 1
    assert _data(result)["submitted"] == True
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
            {"stdout": "", "exit": 0},  # per-comment fallback POST succeeds
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
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
    list_calls = [c for c in _routed_calls(state_dir) if c["route"] == "GET repos/o/r/pulls/1/reviews"]
    # One read up front for key dedup, one read-your-write after the ambiguous failure.
    assert len(list_calls) == 2, f"expected the dedup read plus one read-your-write list call, got {calls}"


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
        ],
        routes={"GET repos/o/r/pulls/1/reviews": [
            {"stdout": json.dumps([{"user": {"login": "alice"}, "commit_id": head, "html_url": landed_url}]), "exit": 0},
        ]},
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["submitted"] == True
    assert _data(result)["posted_inline"] == 1
    assert _data(result)["review_url"] == landed_url
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
    assert _data(result)["event"] == 'COMMENT'
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
        _row(issue=hazardous_body),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert payload["comments"][0]["body"].startswith(
        f"<!-- swe-workbench:review-finding:1 -->\n**High** — {hazardous_body}\n\n"
    )


# ── Behavioral: blocking-thread gate ────────────────────────────────────────────


def test_unresolved_non_outdated_thread_blocks_approve(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=False, is_outdated=False)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["event"] == 'COMMENT'
    assert _data(result)["blocked_by_unresolved"] == 1
    assert "APPROVE downgraded to COMMENT" in result.stderr
    assert "1 unresolved review" in result.stderr


def test_blocking_thread_with_decision_already_comment_prints_no_downgrade_message(tmp_path):
    """When --decision is already COMMENT, blocking threads have nothing to downgrade —
    the informational stderr message must only fire on an actual APPROVE->COMMENT
    transition, not merely whenever blocking threads exist."""
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=False, is_outdated=False)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "COMMENT"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["blocked_by_unresolved"] == 1
    assert "downgraded" not in result.stderr


def test_resolved_thread_does_not_block_approve(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=True, is_outdated=False)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["event"] == 'APPROVE'
    assert _data(result)["blocked_by_unresolved"] == 0


def test_outdated_thread_does_not_block_approve(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=False, is_outdated=True)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["event"] == 'APPROVE'
    assert _data(result)["blocked_by_unresolved"] == 0


# ── Behavioral: --approve-over-open-threads override ────────────────────────────


def test_override_prevents_downgrade_but_blocked_by_unresolved_stays_true_count(tmp_path):
    """The single most important behavioral assertion in this feature: the override lets
    APPROVE stand, but `blocked_by_unresolved` must remain the true non-zero count — it is
    the only evidence in the envelope that a downgrade would otherwise have applied."""
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=False, is_outdated=False)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE", "--approve-over-open-threads": "verified manually"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    data = _data(result)
    assert data["event"] == "APPROVE"
    assert data["decision"] == "APPROVE"
    assert data["blocked_by_unresolved"] == 1, "override must never launder away the true blocking count"
    assert "downgraded" not in result.stderr, "nothing to warn about once the override handled it"


def test_override_note_appears_in_posted_review_body(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=False, is_outdated=False)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "APPROVE", "--approve-over-open-threads": "verified manually"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert "Approved with 1 unresolved review thread(s) still open" in payload["body"]
    assert "override: verified manually" in payload["body"]


def test_override_has_no_effect_when_decision_never_reaches_approve(tmp_path):
    """--approve-over-open-threads is meant to override the blocking-threads downgrade of
    an APPROVE. If the caller's --decision was never going to be APPROVE in the first
    place (here: explicit COMMENT, default IN-DIFF blocking-scope so no OUT-OF-DIFF-ONLY
    upgrade fires), the override must be a no-op: no override-note text in the posted
    review body, and the envelope's decision stays COMMENT — there is nothing to
    override."""
    node = _thread_node(id="PRRT_1", path="src.py", line=10, is_resolved=False, is_outdated=False)
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
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(
            findings,
            **{
                "--decision": "COMMENT",
                "--blocking-scope": "IN-DIFF",
                "--approve-over-open-threads": "some reason",
            },
        ),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    data = _data(result)
    assert data["decision"] == "COMMENT"
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "/reviews" in json.dumps(c["argv"]) and "--input" in c["argv"])
    payload = json.loads(post_call["stdin"])
    assert "override:" not in payload["body"]
    assert "Approved with" not in payload["body"]


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


# ── Behavioral: envelope shape ─────────────────────────────────────────────────


def test_stdout_is_one_envelope_with_data_holding_ten_fields(tmp_path):
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
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"schema", "status", "data", "warnings"}
    assert payload["schema"] == "swb.pr-review-submit/1"
    assert payload["warnings"] == []
    assert set(payload["data"].keys()) == {
        "posted_inline", "posted_pr_level", "deduped", "submitted",
        "event", "decision", "review_url", "blocked_by_unresolved",
        "approve_over_open_threads", "override_reason",
    }


def test_status_is_ok_when_submitted_true(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["submitted"] is True
    assert payload["status"] == "ok"


def test_status_is_partial_when_submitted_false(tmp_path):
    """Every fallback exhausted (double-422 -> per-comment attempt also fails -> no
    confirmed landing -> final plain submit also fails) leaves submitted=false — the
    script still exits 0 (never aborts the caller), but status must reflect the
    genuine partial failure. Same call sequence as
    test_double_422_falls_through_to_per_comment_model_a, with the last two calls
    made to fail instead of succeed."""
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
            {"stdout": pr_diff, "exit": 0},  # re-fetch PR diff alongside HEAD
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # retry POST 422s again
            {"stdout": "", "stderr": "still failing", "exit": 1},  # per-comment fallback POST fails
            {"stdout": "", "stderr": "final submit fails too", "exit": 1},  # final plain review submit fails
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["submitted"] is False
    assert payload["status"] == "partial"


def test_invalid_payload_exits_nonzero_with_empty_stdout_no_envelope(tmp_path):
    """Input-contract validation failures never emit an envelope at all — the
    non-zero exit is the whole signal, matching the contract's fail-closed rule."""
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(
        _args(findings, **{"--decision": "MAYBE"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_envelope_round_trips_through_result_check(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 0, result.stderr

    checker = ROOT / "bin" / "swe-workbench-result-check"
    checked = subprocess.run(
        [sys.executable, str(checker), "swb.pr-review-submit/1"],
        input=result.stdout, capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == json.loads(result.stdout)


# ── Unit: structured rendering (render_finding / dedup_text) ─────────────────


def test_render_inline_golden():
    row = _row(severity="Medium", issue="Unchecked nil deref", why="panics in prod", fix="guard the call")
    assert prs.render_finding(row, pr_level=False) == (
        "**Medium** — Unchecked nil deref\n\n**Why it matters:** panics in prod\n\n**Suggested fix:** guard the call"
    )


def test_render_inline_omits_location_even_when_path_and_line_present():
    assert "src.py" not in prs.render_finding(_row(), pr_level=False)


def test_assign_finding_ids_precedes_partition_and_preserves_order():
    findings = [
        _row(issue="first", anchor="pr-level", path=None, line=None),
        _row(issue="second"),
        _row(issue="third", anchor="pr-level", path=None, line=None),
    ]

    assigned = prs.assign_finding_ids(findings)
    inline, pr_level = prs.partition_findings(assigned)

    assert [row["_finding_id"] for row in assigned] == [1, 2, 3]
    assert [row["_finding_id"] for row in inline] == [2]
    assert [row["_finding_id"] for row in pr_level] == [1, 3]


def test_render_marked_finding_prefixes_exact_provenance_marker():
    row = prs.assign_finding_ids([_row()])[0]

    assert prs.render_marked_finding(row, pr_level=False) == (
        "<!-- swe-workbench:review-finding:1 -->\n"
        "**High** — issue on line2\n\n**Why it matters:** why\n\n**Suggested fix:** fix"
    )


def test_render_pr_level_batch_prefixes_batch_marker_and_preserves_separators():
    rows = prs.assign_finding_ids([
        _row(issue="first", anchor="pr-level", path=None, line=None),
        _row(issue="second", anchor="pr-level", path=None, line=None),
    ])

    assert prs.render_pr_level_batch(rows) == (
        "<!-- swe-workbench:review-findings -->\n\n"
        "<!-- swe-workbench:review-finding:1 -->\n"
        "**High** — first\n\n**Why it matters:** why\n\n**Suggested fix:** fix\n\n---\n\n"
        "<!-- swe-workbench:review-finding:2 -->\n"
        "**High** — second\n\n**Why it matters:** why\n\n**Suggested fix:** fix"
    )


def test_render_pr_level_with_path_and_line():
    row = _row(anchor="pr-level", path="a/b.go", line=7)
    assert prs.render_finding(row, pr_level=True).splitlines()[0] == "**High** · `a/b.go:7` — issue on line2"


def test_render_pr_level_with_path_only():
    row = _row(anchor="pr-level", path="pkg.lock", line=None)
    assert prs.render_finding(row, pr_level=True).splitlines()[0] == "**High** · `pkg.lock` — issue on line2"


def test_render_pr_level_without_location():
    row = _row(anchor="pr-level", path=None, line=None)
    assert prs.render_finding(row, pr_level=True).splitlines()[0] == "**High** — issue on line2"


def test_render_with_category_precedes_location():
    row = _row(anchor="pr-level", category="Correctness")
    assert prs.render_finding(row, pr_level=True).splitlines()[0] == (
        "**High** · Correctness · `src.py:2` — issue on line2"
    )
    assert prs.render_finding(row, pr_level=False).splitlines()[0] == "**High** · Correctness — issue on line2"


def test_render_paragraphs_are_blank_line_separated():
    parts = prs.render_finding(_row(), pr_level=False).split("\n\n")
    assert [p.split(" ")[0] for p in parts] == ["**High**", "**Why", "**Suggested"]


def test_render_keeps_multiline_fix_with_code_fence():
    fix = "use a guard:\n```go\nif x == nil { return }\n```"
    assert prs.render_finding(_row(fix=fix), pr_level=False).endswith(f"**Suggested fix:** {fix}")


@pytest.mark.parametrize(
    "why, fix",
    [
        ("Why it matters: reason", "Suggested fix: do it"),
        ("**Why it matters:** reason", "**Suggested fix:** do it"),
        ("**Why it matters**: reason", "**Suggested fix**: do it"),
        ("why it matters:reason", "SUGGESTED FIX:do it"),
    ],
)
def test_render_strips_self_labelled_fields_instead_of_doubling(why, fix):
    out = prs.render_finding(_row(why=why, fix=fix), pr_level=False)
    assert out.endswith("**Why it matters:** reason\n\n**Suggested fix:** do it")
    assert out.lower().count("why it matters") == 1
    assert out.lower().count("suggested fix") == 1


def test_dedup_text_strips_headline_and_both_label_forms():
    templated = prs.render_finding(_row(category="Style", anchor="pr-level"), pr_level=True)
    tokens = prs.tokenize(prs.dedup_text(templated))
    assert {"issue", "on", "line2"} <= tokens
    assert tokens.isdisjoint({"high", "style", "src", "py", "matters", "suggested", "it"})
    plain = prs.tokenize(prs.dedup_text("Why it matters: a. Suggested fix: b"))
    assert plain.isdisjoint({"matters", "suggested", "it"})


def test_dedup_text_leaves_plain_text_untouched():
    assert prs.dedup_text("alpha bravo charlie") == "alpha bravo charlie"


def test_dedup_text_strips_provenance_markers_for_legacy_thread_matching():
    row = prs.assign_finding_ids([_row(issue="alpha", why="bravo", fix="charlie")])[0]
    marked = prs.render_marked_finding(row, pr_level=False)
    legacy = prs.render_finding(row, pr_level=False)

    assert prs.dedup_text(marked) == prs.dedup_text(legacy)


def test_label_tokens_alone_do_not_false_dedup_unrelated_findings():
    """Every templated comment shares severity + ~5 label tokens; with one-word fields that overlap
    alone clears the 0.4 threshold. dedup_text must remove it so unrelated findings survive."""
    a = _row(issue="alpha", why="bravo", fix="charlie", line=12)
    b = _row(issue="delta", why="echo", fix="foxtrot", line=10)
    rendered_a, rendered_b = prs.render_finding(a, False), prs.render_finding(b, False)
    assert prs.jaccard(rendered_a, rendered_b) == pytest.approx(0.5)  # 6 shared / 12 — over the 0.4 threshold
    thread = prs.Thread(
        id="T", path="src.py", line=10, is_resolved=False, head_comment_id="C", head_comment_body=rendered_b
    )
    assert prs.thread_matches("src.py", 12, rendered_a, thread) is False


def test_templated_finding_dedups_against_its_own_earlier_post():
    row = _row(issue="alpha", why="bravo", fix="charlie", line=12)
    rendered = prs.render_finding(row, False)
    thread = prs.Thread(
        id="T", path="src.py", line=10, is_resolved=False, head_comment_id="C", head_comment_body=rendered
    )
    assert prs.thread_matches("src.py", 12, rendered, thread) is True


@pytest.mark.parametrize(
    "old_body",
    [
        "**Medium** — Unchecked nil deref. Why it matters: panics in prod. Suggested fix: guard the call",
        "Unchecked nil deref. **Why it matters:** panics in prod. **Suggested fix:** guard the call",
        "**Medium** Unchecked nil deref panics in prod, guard the call",
    ],
)
def test_finding_dedups_against_pre_template_run_on_thread(old_body):
    row = _row(severity="Medium", issue="Unchecked nil deref", why="panics in prod", fix="guard the call")
    thread = prs.Thread(
        id="T", path="src.py", line=10, is_resolved=False, head_comment_id="C", head_comment_body=old_body
    )
    assert prs.thread_matches("src.py", 12, prs.render_finding(row, False), thread) is True


# ── Unit: stable finding key ─────────────────────────────────────────────────

_KEY_MARKER_RE = re.compile(r"<!-- swe-workbench:finding-key:v1:([0-9a-f]{16}) -->")


def test_finding_key_is_sixteen_lowercase_hex_chars():
    assert re.fullmatch(r"[0-9a-f]{16}", prs.finding_key(_row(), "x = 1"))


def test_finding_key_survives_a_line_shift_when_anchor_text_is_unchanged():
    assert prs.finding_key(_row(line=2), "x = 1") == prs.finding_key(_row(line=40), "x = 1")


def test_finding_key_changes_with_anchor_text():
    assert prs.finding_key(_row(), "x = 1") != prs.finding_key(_row(), "x = 2")


def test_finding_key_changes_with_path_and_content():
    base = prs.finding_key(_row(), "x = 1")
    assert prs.finding_key(_row(path="other.py"), "x = 1") != base
    assert prs.finding_key(_row(issue="a different issue"), "x = 1") != base


def test_finding_key_normalizes_case_and_whitespace():
    loose = _row(issue="Unchecked   NIL deref", why="Panics\nin prod", fix="guard  the call")
    tight = _row(issue="unchecked nil deref", why="panics in prod", fix="guard the call")
    assert prs.finding_key(loose, "  X =  1") == prs.finding_key(tight, "x = 1")


def test_finding_key_ignores_severity_and_category_presentation():
    assert prs.finding_key(_row(severity="Low", category="Style"), "x") == prs.finding_key(_row(), "x")


def test_finding_key_is_the_same_for_inline_and_demoted_anchor_kinds():
    inline = _row(anchor="inline")
    demoted = _row(anchor="pr-level")
    assert prs.finding_key(inline, "x = 1") == prs.finding_key(demoted, "x = 1")


def test_finding_key_without_path_or_anchor_text_is_still_stable():
    row = _row(anchor="pr-level", path=None, line=None)
    assert prs.finding_key(row, "") == prs.finding_key(dict(row), "")


def test_render_marked_finding_appends_key_marker_as_last_line():
    row = {**prs.assign_finding_ids([_row()])[0], "_finding_key": "0123456789abcdef"}
    rendered = prs.render_marked_finding(row, pr_level=False)
    assert rendered.splitlines()[-1] == "<!-- swe-workbench:finding-key:v1:0123456789abcdef -->"
    assert rendered.splitlines()[0] == "<!-- swe-workbench:review-finding:1 -->"


def test_key_marker_stays_outside_the_review_marker_namespace():
    row = {**prs.assign_finding_ids([_row()])[0], "_finding_key": "0123456789abcdef"}
    assert "swe-workbench:review-" not in prs.render_marked_finding(row, False).splitlines()[-1]


def test_dedup_text_strips_the_finding_key_marker():
    row = {**prs.assign_finding_ids([_row(issue="alpha", why="bravo", fix="charlie")])[0], "_finding_key": "0123456789abcdef"}
    marked = prs.render_marked_finding(row, pr_level=False)
    assert "finding-key" not in prs.dedup_text(marked)
    assert prs.tokenize(prs.dedup_text(marked)) == prs.tokenize(prs.dedup_text(prs.render_finding(row, False)))


def test_assign_finding_keys_reads_the_anchor_line_text_at_head(monkeypatch):
    lookups = []

    def fake_show(head_sha, path, line):
        lookups.append((head_sha, path, line))
        return {2: "line2", 3: "line3"}.get(line)

    monkeypatch.setattr(prs, "_git_show_line", fake_show)
    keyed = prs.assign_finding_keys([_row(line=2), _row(line=3)], "a" * 40)
    assert lookups == [("a" * 40, "src.py", 2), ("a" * 40, "src.py", 3)]
    assert keyed[0]["_finding_key"] != keyed[1]["_finding_key"]
    assert keyed[0]["_finding_key"] == prs.finding_key(_row(line=2), "line2")


def test_assign_finding_keys_uses_empty_anchor_text_without_path_and_line():
    keyed = prs.assign_finding_keys([_row(anchor="pr-level", path=None, line=None)], "a" * 40)
    assert keyed[0]["_finding_key"] == prs.finding_key(keyed[0], "")


def test_collapse_duplicate_keys_keeps_first_occurrence_and_counts_drops():
    rows = [
        {**_row(issue="one"), "_finding_key": "k1"},
        {**_row(issue="two"), "_finding_key": "k2"},
        {**_row(issue="one again"), "_finding_key": "k1"},
    ]
    unique, dropped = prs.collapse_duplicate_keys(rows)
    assert [r["issue"] for r in unique] == ["one", "two"]
    assert dropped == 1


# ── Exact-key dedup across threads, reviews and issue comments ───────────────

_PR_DIFF_3_LINES = (
    "diff --git a/src.py b/src.py\nindex e69de29..1234567 100644\n--- a/src.py\n+++ b/src.py\n"
    "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n"
)


def _ndjson(objects: list[dict]) -> dict:
    """A `gh api --paginate --jq '.[]'` response: one JSON object per line."""
    return {"stdout": "".join(json.dumps(o) + "\n" for o in objects), "exit": 0}


def _posted_marked(row: dict, anchor_text: str, finding_id: int = 1, pr_level: bool = False) -> str:
    keyed = {**row, "_finding_id": finding_id, "_finding_key": prs.finding_key(row, anchor_text)}
    return prs.render_marked_finding(keyed, pr_level=pr_level)


def _run_dedup_scenario(tmp_path, *, findings, threads=(), reviews=(), issue_comments=(), extra_args=None, positional_tail=()):
    head = _init_repo(tmp_path)
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response(list(threads)),
            *positional_tail,
            {"stdout": _PR_DIFF_3_LINES, "exit": 0},
            _repo_view_response(True),
            _review_post_response(),
        ],
        routes={
            "GET repos/o/r/pulls/1/reviews": [_ndjson(list(reviews))],
            "GET repos/o/r/issues/1/comments": [_ndjson(list(issue_comments))],
        },
    )
    findings_path = _write_findings(tmp_path, findings)
    result = _run(
        _args(findings_path, **{"--head-sha": head, "--current-user": "alice", **(extra_args or {})}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=tmp_path / "gh_responses.json",
    )
    return result, state_dir


def _reaction_calls(state_dir) -> list[dict]:
    return [c for c in _all_calls(state_dir) if "addReaction(input:" in json.dumps(c["argv"])]


def test_resolved_thread_key_match_is_suppressed_without_a_reaction(tmp_path):
    body = _posted_marked(_row(), "line2")
    node = _thread_node(id="PRRT_1", path="src.py", line=40, is_resolved=True, body=body, author="alice")
    result, state_dir = _run_dedup_scenario(tmp_path, findings=[_row()], threads=[node])
    assert result.returncode == 0, result.stderr
    data = _data(result)
    assert (data["deduped"], data["posted_inline"]) == (1, 0)
    assert _reaction_calls(state_dir) == []


def test_outdated_thread_key_match_is_suppressed_without_a_reaction(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=2, is_outdated=True, body=_posted_marked(_row(), "line2"), author="alice")
    result, state_dir = _run_dedup_scenario(tmp_path, findings=[_row()], threads=[node])
    assert _data(result)["deduped"] == 1
    assert _reaction_calls(state_dir) == []


def test_unresolved_thread_key_match_reacts_once_even_after_the_line_shifted(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=90, body=_posted_marked(_row(), "line2"), author="alice")
    result, state_dir = _run_dedup_scenario(
        tmp_path, findings=[_row()], threads=[node], positional_tail=[{"stdout": "", "exit": 0}],
    )
    assert _data(result)["deduped"] == 1
    assert len(_reaction_calls(state_dir)) == 1


def test_key_in_an_earlier_review_body_suppresses_a_pr_level_row(tmp_path):
    pr_level = _row(anchor="pr-level", path=None, line=None, issue="repo-wide concern")
    review_body = "summary\n\n" + prs.REVIEW_BATCH_MARKER + "\n\n" + _posted_marked(pr_level, "", pr_level=True)
    reviews = [{"id": 5, "user": {"login": "alice"}, "body": review_body, "state": "COMMENTED"}]
    result, state_dir = _run_dedup_scenario(tmp_path, findings=[pr_level], reviews=reviews)
    data = _data(result)
    assert (data["deduped"], data["posted_pr_level"]) == (1, 0)
    assert [c for c in _all_calls(state_dir) if c["argv"][:2] == ["pr", "comment"]] == []


def test_key_in_a_legacy_issue_comment_batch_suppresses_the_row(tmp_path):
    pr_level = _row(anchor="pr-level", path=None, line=None, issue="legacy concern")
    batch = prs.REVIEW_BATCH_MARKER + "\n\n" + _posted_marked(pr_level, "", pr_level=True)
    comments = [{"id": 8, "user": {"login": "alice"}, "body": batch}]
    result, state_dir = _run_dedup_scenario(tmp_path, findings=[pr_level], issue_comments=comments)
    assert _data(result)["deduped"] == 1
    assert [c for c in _all_calls(state_dir) if c["argv"][:2] == ["pr", "comment"]] == []


def test_a_row_with_a_different_anchor_text_is_not_suppressed(tmp_path):
    earlier = _posted_marked(_row(line=2), "line2")
    reviews = [{"id": 5, "user": {"login": "alice"}, "body": "x\n\n" + earlier}]
    # Line 999 has no text at head, so its anchor text ("") differs from "line2".
    result, _ = _run_dedup_scenario(tmp_path, findings=[_row(line=999)], reviews=reviews)
    assert _data(result)["deduped"] == 0


def test_a_demoted_row_keeps_the_key_of_its_earlier_inline_post(tmp_path):
    """The same finding, once inline and now anchor-less: only the anchor kind differs."""
    earlier = _posted_marked(_row(), "")
    reviews = [{"id": 5, "user": {"login": "alice"}, "body": "x\n\n" + earlier}]
    demoted_shape = _row(anchor="pr-level", path="src.py", line=999)
    result, _ = _run_dedup_scenario(tmp_path, findings=[demoted_shape], reviews=reviews)
    assert _data(result)["deduped"] == 1


def test_key_markers_from_other_users_never_suppress_a_finding(tmp_path):
    body = _posted_marked(_row(), "line2")
    forged_review = [{"id": 5, "user": {"login": "mallory"}, "body": body}]
    forged_comment = [{"id": 8, "user": {"login": "mallory"}, "body": body}]
    forged_thread = _thread_node(id="PRRT_1", path="elsewhere.py", line=1, body=body, author="mallory")
    result, _ = _run_dedup_scenario(
        tmp_path, findings=[_row()], threads=[forged_thread], reviews=forged_review, issue_comments=forged_comment,
    )
    data = _data(result)
    assert (data["deduped"], data["posted_inline"]) == (0, 1)


def test_fuzzy_matching_still_dedups_an_unkeyed_unresolved_thread(tmp_path):
    node = _thread_node(id="PRRT_1", path="src.py", line=10, body=prs.render_finding(_DEDUP_ROW, False), author="bob")
    result, state_dir = _run_dedup_scenario(
        tmp_path, findings=[_DEDUP_ROW], threads=[node], positional_tail=[{"stdout": "", "exit": 0}],
    )
    assert _data(result)["deduped"] == 1
    assert len(_reaction_calls(state_dir)) == 1


def test_duplicate_rows_in_one_payload_count_as_deduped(tmp_path):
    result, _ = _run_dedup_scenario(tmp_path, findings=[_row(), _row()])
    data = _data(result)
    assert (data["deduped"], data["posted_inline"]) == (1, 1)


def test_collect_known_keys_trusts_only_the_current_users_bodies():
    mine = _posted_marked(_row(issue="mine"), "a")
    theirs = _posted_marked(_row(issue="theirs"), "b")
    threads = [
        prs.Thread(id="T1", path="p", line=1, is_resolved=True, head_comment_id="c", head_comment_body=mine, head_comment_author="alice"),
        prs.Thread(id="T2", path="p", line=1, is_resolved=False, head_comment_id="c", head_comment_body=theirs, head_comment_author="bob"),
    ]
    reviews = [{"user": {"login": "alice"}, "body": _posted_marked(_row(issue="rev"), "c")}, {"user": {"login": "bob"}, "body": theirs}]
    comments = [{"user": {"login": "alice"}, "body": _posted_marked(_row(issue="iss"), "d")}]
    keys = prs.collect_known_keys(threads, reviews, comments, "alice")
    assert keys == {
        prs.finding_key(_row(issue=name), anchor)
        for name, anchor in (("mine", "a"), ("rev", "c"), ("iss", "d"))
    }


def test_collect_known_keys_is_empty_when_identity_is_unknown():
    mine = _posted_marked(_row(), "a")
    assert prs.collect_known_keys([], [{"user": {"login": "alice"}, "body": mine}], [], "") == set()


def test_collect_known_keys_ignores_inline_mentions_of_the_marker():
    quoted = f"see {_key_line(_row(), 'a')} for details"
    assert prs.collect_known_keys([], [{"user": {"login": "alice"}, "body": quoted}], [], "alice") == set()


def test_parse_json_objects_accepts_ndjson_and_concatenated_arrays():
    assert prs._parse_json_objects('{"a": 1}\n{"a": 2}\n') == [{"a": 1}, {"a": 2}]
    assert prs._parse_json_objects('[{"a": 1}][{"a": 2}]') == [{"a": 1}, {"a": 2}]
    assert prs._parse_json_objects("") == []


# ── Unit: structured row validation ──────────────────────────────────────────


def test_valid_rows_have_no_problem():
    assert prs._finding_problem(_row()) is None
    assert prs._finding_problem(_row(anchor="pr-level", path=None, line=None)) is None
    assert prs._finding_problem(_row(anchor="pr-level", line=None)) is None
    assert prs._finding_problem(_row(category="Correctness", fix="a\nb")) is None


@pytest.mark.parametrize("field", ["severity", "issue", "why", "fix"])
def test_missing_or_empty_required_field_names_the_field(field):
    assert prs._finding_problem(_row(**{field: None}))[0] == field
    assert prs._finding_problem(_row(**{field: "   "}))[0] == field


@pytest.mark.parametrize("field, label", [("why", "Why it matters:"), ("fix", "**Suggested fix:**")])
def test_label_only_field_counts_as_empty(field, label):
    assert prs._finding_problem(_row(**{field: label}))[0] == field


@pytest.mark.parametrize("field", ["severity", "issue", "why", "fix", "category"])
def test_remark_embedded_in_any_text_field_is_rejected(field):
    problem = prs._finding_problem(_row(**{field: f"x {prs.REMARK_TEXT}"}))
    assert problem is not None and problem[0] == field and "remark" in problem[1]


@pytest.mark.parametrize("field", ["severity", "issue", "why", "fix", "category", "path"])
def test_reserved_review_marker_in_any_string_field_is_rejected(field):
    problem = prs._finding_problem(_row(**{field: "<!-- swe-workbench:review-finding:7 --> x"}))
    assert problem is not None and problem[0] == field and "reserved swe-workbench marker" in problem[1]


@pytest.mark.parametrize("field", ["severity", "issue", "why", "fix", "category", "path"])
def test_inline_plugin_marker_mention_in_string_field_is_allowed(field):
    """The consumer honours markers only at a line start; prose/code-span mentions
    are harmless and must not reject an otherwise valid review payload."""
    problem = prs._finding_problem(_row(**{field: "mention <!-- swe-workbench:handled:123 --> safely"}))
    assert problem is None


@pytest.mark.parametrize("field", ["severity", "issue", "why", "fix", "category", "path"])
def test_line_start_handled_marker_in_any_string_field_is_rejected(field):
    problem = prs._finding_problem(_row(**{field: "<!-- swe-workbench:handled:123 --> x"}))
    assert problem is not None and problem[0] == field and "reserved swe-workbench marker" in problem[1]


@pytest.mark.parametrize("prefix", ["x\n", "x\r\n", "x\n  ", "x\n\t", "x\n\n---\n\n", "x\r"])
def test_body_field_marker_at_any_line_boundary_is_rejected(prefix):
    problem = prs._finding_problem(_row(why=f"{prefix}<!-- swe-workbench:handled:123 -->"))
    assert problem is not None and problem == ("why", "must not embed a reserved swe-workbench marker")


@pytest.mark.parametrize("field", ["severity", "issue", "category"])
def test_newline_in_headline_field_is_rejected(field):
    problem = prs._finding_problem(_row(**{field: "a\nb"}))
    assert problem is not None and problem[0] == field


def test_leftover_body_key_is_rejected():
    problem = prs._finding_problem(_row(body="legacy prose"))
    assert problem is not None and problem[0] == "body" and "no longer accepted" in problem[1]


def test_pr_level_line_requires_positive_int_and_path():
    assert prs._finding_problem(_row(anchor="pr-level", line=0))[0] == "line"
    assert prs._finding_problem(_row(anchor="pr-level", line=True))[0] == "line"
    assert prs._finding_problem(_row(anchor="pr-level", path=None, line=3))[0] == "line"
    assert prs._finding_problem(_row(anchor="pr-level", path=""))[0] == "path"


def test_leftover_body_aborts_the_whole_batch_naming_the_field(tmp_path):
    stub_dir, state_dir = _write_gh_stub(tmp_path, [])
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [_row(), _row(body="free-form prose")])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 1
    assert "--findings-json[1].body" in result.stderr
    assert result.stdout == ""
    assert _gh_calls(state_dir) == []


def test_row_demoted_on_422_retry_renders_pr_level_with_location(tmp_path):
    """The diff moving between pre-validate and submit demotes a row *after* the inline comment
    payload was built — it must still re-render as PR-level with path:line in its headline."""
    head = _init_repo(tmp_path)
    hunk = "diff --git a/src.py b/src.py\nindex e69de29..1234567 100644\n--- a/src.py\n+++ b/src.py\n"
    diff_before = hunk + "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n"
    diff_after = hunk + "@@ -0,0 +1,1 @@\n+line1\n"  # line 2 left the diff
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": diff_before, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 422: Unprocessable Entity", "exit": 1},  # atomic POST 422s
            {"stdout": json.dumps({"headRefOid": head}), "exit": 0},  # re-fetch HEAD
            {"stdout": diff_after, "exit": 0},  # re-fetch PR diff
            {"stdout": "", "exit": 0},  # pr comment carrying the newly demoted row
            _review_post_response(),  # N=0 -> plain review submit
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [_row(category="Correctness")])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 1
    assert _data(result)["posted_inline"] == 0
    pr_comment = next(c for c in _gh_calls(state_dir) if c["argv"][:2] == ["pr", "comment"])
    body = pr_comment["argv"][pr_comment["argv"].index("--body") + 1]
    assert body == (
        "<!-- swe-workbench:review-findings -->\n\n"
        "<!-- swe-workbench:review-finding:1 -->\n"
        "**High** · Correctness · `src.py:2` — issue on line2\n\n**Why it matters:** why\n\n**Suggested fix:** fix\n"
        + _key_line(_row(category="Correctness"), "line2")
    )


def test_out_of_diff_demoted_row_keeps_batch_ascending_with_pr_level_row(tmp_path):
    """main() posts `pr_level_findings + demoted`: a lower-ID demoted inline row
    must not render after a higher-ID original pr-level row — the consumer
    requires strictly ascending IDs or rejects the whole batch."""
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\n"
        "index e69de29..1234567 100644\n"
        "--- a/src.py\n"
        "+++ b/src.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+line1\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},  # pr diff (line 999 not in it)
            {"stdout": "", "exit": 0},  # pr comment (mixed batch, one call)
            _repo_view_response(True),
            _review_post_response(),  # N=0 (the only inline row was demoted)
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(issue="demoted inline finding", line=999),
        _row(issue="original pr level", anchor="pr-level", path=None, line=None),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 2
    assert _data(result)["posted_inline"] == 0
    calls = _gh_calls(state_dir)
    pr_comment_calls = [c for c in calls if c["argv"][:2] == ["pr", "comment"]]
    assert len(pr_comment_calls) == 1
    body = pr_comment_calls[0]["argv"][pr_comment_calls[0]["argv"].index("--body") + 1]
    assert re.findall(r"swe-workbench:review-finding:(\d+)", body) == ["1", "2"], (
        "the batch must render in ascending finding-ID order regardless of the "
        "pr_level+demoted concatenation order"
    )
    first_section = body.split("\n\n---\n\n")[0]
    assert "`src.py:999` — demoted inline finding" in first_section


def test_post_pr_level_chunks_oversized_batches(tmp_path):
    """The consumer rejects marked batches over its section cap — the producer
    must chunk oversized pr-level payloads into per-batch-parseable comments,
    each internally ascending."""
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff
            {"stdout": "", "exit": 0},  # pr comment — chunk 1
            {"stdout": "", "exit": 0},  # pr comment — chunk 2
            _repo_view_response(True),
            _review_post_response(),  # N=0
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    rows = [
        _row(issue=f"finding {index}", anchor="pr-level", path=None, line=None)
        for index in range(1, 61)
    ]
    findings = _write_findings(tmp_path, rows)
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 60
    calls = _gh_calls(state_dir)
    pr_comment_calls = [c for c in calls if c["argv"][:2] == ["pr", "comment"]]
    assert len(pr_comment_calls) == 2, "60 rows at a 50-row cap must post exactly two batch comments"
    chunks = [
        re.findall(r"swe-workbench:review-finding:(\d+)", c["argv"][c["argv"].index("--body") + 1])
        for c in pr_comment_calls
    ]
    assert [len(ids) for ids in chunks] == [50, 10]
    for ids in chunks:
        assert ids == sorted(ids, key=int), "each chunk must be internally ascending"
    assert [int(i) for i in chunks[0] + chunks[1]] == list(range(1, 61)), "no row may be lost or duplicated"


def test_post_pr_level_sorts_before_chunking_mixed_partition_rows(tmp_path):
    """main() builds `pr_level_findings + demoted`, so positional chunking would
    interleave ranges (46..55 then 1..45). Sort before slicing so every posted
    comment is one contiguous ascending finding-ID run."""
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # empty diff: all inline rows demote
            {"stdout": "", "exit": 0},  # pr comment — IDs 1..50
            {"stdout": "", "exit": 0},  # pr comment — IDs 51..55
            _repo_view_response(True),
            _review_post_response(),  # N=0
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    rows = [
        _row(issue=f"demoted {index}", line=index)
        for index in range(1, 46)
    ] + [
        _row(issue=f"pr-level {index}", anchor="pr-level", path=None, line=None)
        for index in range(46, 56)
    ]
    findings = _write_findings(tmp_path, rows)
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    chunks = [
        [int(finding_id) for finding_id in re.findall(r"swe-workbench:review-finding:(\d+)", c["argv"][c["argv"].index("--body") + 1])]
        for c in calls
        if c["argv"][:2] == ["pr", "comment"]
    ]
    assert chunks == [list(range(1, 51)), list(range(51, 56))]


def test_pr_level_batch_joins_rendered_rows_with_separator(tmp_path):
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": "", "exit": 0},  # pr diff
            {"stdout": "", "exit": 0},  # pr comment
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(issue="first", anchor="pr-level", path=None, line=None),
        _row(issue="second", anchor="pr-level", path="pkg.lock", line=None),
    ])
    result = _run(_args(findings), cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file)
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_pr_level"] == 2
    pr_comment = next(c for c in _gh_calls(state_dir) if c["argv"][:2] == ["pr", "comment"])
    body = pr_comment["argv"][pr_comment["argv"].index("--body") + 1]
    first, second = body.split("\n\n---\n\n")
    assert first.startswith(
        "<!-- swe-workbench:review-findings -->\n\n<!-- swe-workbench:review-finding:1 -->\n"
        "**High** — first\n\n**Why it matters:**"
    )
    assert second.startswith(
        "<!-- swe-workbench:review-finding:2 -->\n**High** · `pkg.lock` — second\n\n**Why it matters:**"
    )


def test_pr_level_batch_preserves_original_ordinals_after_partition(tmp_path):
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\nindex e69de29..1234567 100644\n--- a/src.py\n+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            {"stdout": "", "exit": 0},  # pr-level batch
            _repo_view_response(True),
            _review_post_response(),
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(issue="inline", line=2),
        _row(issue="second", anchor="pr-level", path=None, line=None),
        _row(issue="third", anchor="pr-level", path=None, line=None),
    ])

    result = _run(
        _args(findings, **{"--head-sha": head}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )

    assert result.returncode == 0, result.stderr
    pr_comment = next(c for c in _gh_calls(state_dir) if c["argv"][:2] == ["pr", "comment"])
    body = pr_comment["argv"][pr_comment["argv"].index("--body") + 1]
    assert "<!-- swe-workbench:review-finding:2 -->" in body
    assert "<!-- swe-workbench:review-finding:3 -->" in body
    assert "<!-- swe-workbench:review-finding:1 -->" not in body


def test_row_demoted_by_failed_per_comment_fallback_renders_pr_level_with_location(tmp_path):
    """The model-A fallback demotes a row whose individual POST fails — it must land in the
    pr-level comment as a re-render (path:line in the headline), not as the inline body."""
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\nindex e69de29..1234567 100644\n--- a/src.py\n+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # first atomic POST 422s
            {"stdout": json.dumps({"headRefOid": head}), "exit": 0},  # re-fetch HEAD (unchanged)
            {"stdout": pr_diff, "exit": 0},  # re-fetch PR diff alongside HEAD
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # retry POST 422s again
            {"stdout": "", "stderr": "HTTP 500", "exit": 1},  # per-comment fallback POST fails
            {"stdout": "", "exit": 0},  # pr comment carrying the demoted row
            _review_post_response(),  # final plain review submit
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [_row(category="Correctness")])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_inline"] == 0
    assert _data(result)["posted_pr_level"] == 1
    pr_comment = next(c for c in _gh_calls(state_dir) if c["argv"][:2] == ["pr", "comment"])
    body = pr_comment["argv"][pr_comment["argv"].index("--body") + 1]
    assert body.startswith(
        "<!-- swe-workbench:review-findings -->\n\n<!-- swe-workbench:review-finding:1 -->\n"
        "**High** · Correctness · `src.py:2` — issue on line2\n\n"
    )


def test_fallback_demotes_one_of_two_findings_and_preserves_ordinals(tmp_path):
    """Ordinal stability through the per-comment fallback with a partial failure:
    the row whose individual POST fails demotes to pr-level keeping its original
    ID, while the row that landed inline keeps its own — no renumbering."""
    head = _init_repo(tmp_path)
    pr_diff = (
        "diff --git a/src.py b/src.py\nindex e69de29..1234567 100644\n--- a/src.py\n+++ b/src.py\n"
        "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3\n"
    )
    stub_dir, state_dir = _write_gh_stub(
        tmp_path,
        [
            _threads_response([]),
            {"stdout": pr_diff, "exit": 0},
            _repo_view_response(True),
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # first atomic POST 422s
            {"stdout": json.dumps({"headRefOid": head}), "exit": 0},  # re-fetch HEAD (unchanged)
            {"stdout": pr_diff, "exit": 0},  # re-fetch PR diff alongside HEAD
            {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # retry POST 422s again
            {"stdout": "", "exit": 0},  # per-comment fallback POST for finding 1 succeeds
            {"stdout": "", "stderr": "HTTP 500", "exit": 1},  # per-comment fallback POST for finding 2 fails
            {"stdout": "", "exit": 0},  # pr comment carrying the demoted row
            _review_post_response(),  # final plain review submit
        ],
    )
    responses_file = tmp_path / "gh_responses.json"
    findings = _write_findings(tmp_path, [
        _row(issue="issue on line2", line=2),
        _row(issue="issue on line3", line=3),
    ])
    result = _run(
        _args(findings, **{"--head-sha": head, "--current-user": "alice"}),
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir, responses_file=responses_file,
    )
    assert result.returncode == 0, result.stderr
    assert _data(result)["posted_inline"] == 1
    assert _data(result)["posted_pr_level"] == 1
    calls = _gh_calls(state_dir)
    per_comment_posts = [c for c in calls if "/comments" in json.dumps(c["argv"]) and c["argv"][0] == "api"]
    assert len(per_comment_posts) == 2
    landed = next(a for a in per_comment_posts[0]["argv"] if a.startswith("body="))
    assert landed.startswith("body=<!-- swe-workbench:review-finding:1 -->\n")
    pr_comment = next(c for c in calls if c["argv"][:2] == ["pr", "comment"])
    body = pr_comment["argv"][pr_comment["argv"].index("--body") + 1]
    assert body.startswith(
        "<!-- swe-workbench:review-findings -->\n\n<!-- swe-workbench:review-finding:2 -->\n"
        "**High** · `src.py:3` — issue on line3\n\n"
    )
    assert "review-finding:1" not in body


def test_render_puts_fence_led_fix_on_its_own_paragraph():
    """GitHub only opens a fence at the start of a line, so a ```suggestion block glued to the
    label would print as literal text and forfeit the one-click suggestion."""
    fix = "```suggestion\nx = 1\n```"
    out = prs.render_finding(_row(fix=fix), pr_level=False)
    assert out.endswith(f"**Suggested fix:**\n\n{fix}")
    why = "```text\nboom\n```"
    assert f"**Why it matters:**\n\n{why}\n\n**Suggested fix:**" in prs.render_finding(_row(why=why), pr_level=False)


def test_render_keeps_prose_led_fix_on_the_label_line():
    out = prs.render_finding(_row(fix="do it:\n```go\nx()\n```"), pr_level=False)
    assert "**Suggested fix:** do it:\n```go" in out


@pytest.mark.parametrize("severity", ["**High**", "*High*", " ** High ** "])
def test_render_normalizes_caller_bolded_severity(severity):
    assert prs.render_finding(_row(severity=severity), pr_level=False).startswith("**High** — ")


def test_bold_only_severity_is_rejected_as_empty():
    assert prs._finding_problem(_row(severity="****"))[0] == "severity"


@pytest.mark.parametrize("bad_path", ["a`b.py", "a\nb.py", "a\rb.py"])
@pytest.mark.parametrize("anchor", ["inline", "pr-level"])
def test_path_with_backtick_or_line_break_is_rejected_for_both_anchors(bad_path, anchor):
    """An inline row can be demoted to pr-level, where the path is rendered inside a code span."""
    problem = prs._finding_problem(_row(anchor=anchor, path=bad_path))
    assert problem is not None and problem[0] == "path"


def test_whitespace_only_path_is_rejected():
    assert prs._finding_problem(_row(path="   "))[0] == "path"
    assert prs._finding_problem(_row(anchor="pr-level", path="   ", line=None))[0] == "path"


def test_remark_embedded_in_path_is_rejected():
    problem = prs._finding_problem(_row(anchor="pr-level", path=f"x {prs.REMARK_TEXT}", line=None))
    assert problem is not None and problem[0] == "path" and "remark" in problem[1]


@pytest.mark.parametrize("field", ["severity", "issue", "category"])
def test_bare_carriage_return_in_headline_field_is_rejected(field):
    problem = prs._finding_problem(_row(**{field: "a\rb"}))
    assert problem is not None and problem[0] == field


def _rendered_thread_match(row_a: dict, row_b: dict) -> bool:
    thread = prs.Thread(
        id="T", path="src.py", line=10, is_resolved=False, head_comment_id="C",
        head_comment_body=prs.render_finding(row_b, False),
    )
    return prs.thread_matches("src.py", 12, prs.render_finding(row_a, False), thread)


def test_rendered_findings_match_at_exactly_the_0_4_threshold():
    # content tokens {alpha bravo charlie} vs {alpha bravo delta echo}: 2/5 = 0.4 — label and
    # headline tokens must not shift the ratio in either direction.
    a = _row(issue="alpha", why="bravo", fix="charlie", line=12)
    b = _row(issue="alpha", why="bravo", fix="delta echo")
    assert _rendered_thread_match(a, b) is True


def test_rendered_findings_do_not_match_just_below_the_0_4_threshold():
    # 3 shared / 8 total = 0.375
    a = _row(issue="alpha bravo", why="charlie", fix="delta echo", line=12)
    b = _row(issue="alpha bravo", why="charlie", fix="foxtrot golf hotel")
    assert _rendered_thread_match(a, b) is False
