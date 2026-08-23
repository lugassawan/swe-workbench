"""Guards the raw-body discipline of bin/swe-workbench-pr-review-submit's two
comment-posting call sites against injection/@-expansion hazards (issue #494,
moved from bash+jq prose into the script by #550).

A reviewer finding body is free-form text that can legitimately start with
`@author...` or contain `"`/`\\` characters. Two distinct hazards apply
depending on the call site:

1. `gh api -F body=` treats an @-prefixed value as a file path to read, so
   posting such a finding with `-F` would silently read (or fail to read) a
   bogus file instead of posting the literal text. `-f body=` forces a raw
   string — the model-A per-comment fallback call site uses it (see
   test_reply_and_resolve_script.py::test_body_flag_is_lowercase_f_not_uppercase_f
   for the sibling script this mirrors).
2. Building the atomic `comments[]` payload by string-concatenating a
   free-form body into a JSON literal would let a body containing `"` or `\\`
   break the JSON or inject fields. The script builds it as a real Python
   dict and serializes once with json.dumps, which has the same raw-string
   safety `jq --arg` gave the old bash version (see shared/docs/gh-api-field-flags.md).

These are behavioral properties of the running script, not its source text —
each test below drives the script through a stubbed `gh` and inspects the
actual argv/payload the stub received, the same approach
tests/test_pr_review_submit_script.py uses.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).resolve().parents[1]
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
resp = responses[i] if i < len(responses) else {"stdout": "", "stderr": f"no response for call {i}", "exit": 99}
sys.stdout.write(resp.get("stdout", ""))
sys.stderr.write(resp.get("stderr", ""))
sys.exit(resp.get("exit", 0))
'''

HAZARDOUS_BODY = '@author said "this" is \\wrong\\'


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


def _run(args, *, cwd, stub_dir, state_dir, stdin=None):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    env["GH_STUB_STATE"] = str(state_dir)
    env["GH_STUB_RESPONSES"] = str(cwd / "gh_responses.json")
    return subprocess.run([str(SCRIPT), *args], input=stdin, capture_output=True, text=True, cwd=str(cwd), env=env)


def _threads_response():
    body = {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"endCursor": None, "hasNextPage": False}, "nodes": [],
    }}}}}
    return {"stdout": json.dumps(body), "exit": 0}


def _repo_view_response():
    return {"stdout": json.dumps({"isPrivate": True}), "exit": 0}


def _review_post_response():
    return {"stdout": json.dumps({"html_url": "https://github.com/o/r/pull/1#pullrequestreview-1"}), "exit": 0}


def _base_args(findings_path):
    return [
        "--repo", "o/r", "--pr", "1", "--head-sha", "a" * 40, "--base", "main",
        "--decision", "COMMENT", "--byline", "_Reviewed by `bot`_", "--caller-tag", "general",
        "--findings-json", str(findings_path),
    ]


def _init_repo(tmp_path: Path) -> str:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    (tmp_path / "src.py").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "add", "src.py"], cwd=str(tmp_path), capture_output=True, text=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(tmp_path), capture_output=True, text=True, env=dict(_CLEAN_ENV))
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(tmp_path), capture_output=True, text=True, env=dict(_CLEAN_ENV))
    return result.stdout.strip()


_PR_DIFF = (
    "diff --git a/src.py b/src.py\n"
    "index e69de29..1234567 100644\n"
    "--- a/src.py\n"
    "+++ b/src.py\n"
    "@@ -0,0 +1,3 @@\n"
    "+line1\n"
    "+line2\n"
    "+line3\n"
)


def test_source_never_builds_comments_via_bracket_indexed_field_flags():
    """gh api -f "comments[0][path]=..." builds a stringified-key JSON object, not an array —
    GitHub's Reviews API rejects it outright. The script must never reintroduce that call shape
    as actual argv construction (the module docstring's rationale prose names the anti-pattern
    to explain why it's avoided, so this is scoped to the code after the docstring, not the text
    as a whole)."""
    text = SCRIPT.read_text()
    code = text.split('"""', 2)[-1]  # everything after the module docstring's closing '"""'
    assert "comments[$i][" not in code and "comments[0][" not in code


def test_atomic_comments_body_survives_byte_identical_via_json_payload(tmp_path):
    head = _init_repo(tmp_path)
    stub_dir, state_dir = _write_gh_stub(tmp_path, [
        _threads_response(), {"stdout": _PR_DIFF, "exit": 0}, _repo_view_response(), _review_post_response(),
    ])
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps([
        {"severity": "High", "body": HAZARDOUS_BODY, "anchor": "inline", "path": "src.py", "line": 2},
    ]))
    result = _run(_base_args(findings) + ["--head-sha", head], cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir)
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "--input" in c["argv"] and "/reviews" in json.dumps(c["argv"]))
    payload = json.loads(post_call["stdin"])
    assert payload["comments"][0]["body"] == HAZARDOUS_BODY, (
        "a body containing '\"'/'\\\\'/a leading '@' must survive byte-identical into the JSON payload"
    )


def test_atomic_reviews_post_uses_input_flag_not_f_F_for_body(tmp_path):
    head = _init_repo(tmp_path)
    stub_dir, state_dir = _write_gh_stub(tmp_path, [
        _threads_response(), {"stdout": _PR_DIFF, "exit": 0}, _repo_view_response(), _review_post_response(),
    ])
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps([
        {"severity": "High", "body": "a finding", "anchor": "inline", "path": "src.py", "line": 2},
    ]))
    result = _run(_base_args(findings) + ["--head-sha", head], cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir)
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    post_call = next(c for c in calls if "--input" in c["argv"] and "/reviews" in json.dumps(c["argv"]))
    assert "--input" in post_call["argv"] and "-" in post_call["argv"]
    assert not any(a.startswith("body=") for a in post_call["argv"]), (
        "the atomic comments[] POST must submit the payload via --input -, not -f/-F body="
    )


def test_fallback_per_comment_post_uses_lowercase_f_not_uppercase_f_for_body(tmp_path):
    """Drives the model-A fallback (double-422) and inspects the per-comment REST call's argv."""
    head = _init_repo(tmp_path)
    stub_dir, state_dir = _write_gh_stub(tmp_path, [
        _threads_response(),
        {"stdout": _PR_DIFF, "exit": 0},
        _repo_view_response(),
        {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # first atomic POST 422s
        {"stdout": json.dumps({"headRefOid": head}), "exit": 0},  # re-fetch HEAD (unchanged)
        {"stdout": _PR_DIFF, "exit": 0},  # re-fetch PR diff alongside HEAD
        {"stdout": "", "stderr": "HTTP 422", "exit": 1},  # retry POST 422s again
        {"stdout": "[]", "exit": 0},  # read-your-write: nothing landed
        {"stdout": "", "exit": 0},  # per-comment fallback POST succeeds
        _review_post_response(),
    ])
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps([
        {"severity": "High", "body": HAZARDOUS_BODY, "anchor": "inline", "path": "src.py", "line": 2},
    ]))
    result = _run(
        _base_args(findings) + ["--head-sha", head, "--current-user", "alice"],
        cwd=tmp_path, stub_dir=stub_dir, state_dir=state_dir,
    )
    assert result.returncode == 0, result.stderr
    calls = _gh_calls(state_dir)
    fallback_call = next(c for c in calls if c["argv"][0] == "api" and "/comments" in json.dumps(c["argv"]))
    assert f"body={HAZARDOUS_BODY}" in fallback_call["argv"], (
        f"expected -f body=<raw> in the fallback per-comment POST argv, got: {fallback_call['argv']}"
    )
    idx = fallback_call["argv"].index(f"body={HAZARDOUS_BODY}")
    assert fallback_call["argv"][idx - 1] == "-f", (
        "the fallback per-comment POST must use -f (raw string) for body, not -F "
        "(which @-expands a value starting with '@')"
    )
