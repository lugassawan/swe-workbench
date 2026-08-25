"""Tests for bin/swe-workbench-preflight-commit (issue #660).

Replaces the two shell pipelines workflow-commit-and-pr/SKILL.md previously asked the
agent to transcribe and run at runtime: the suspicious-filename secret scan and the
docs-only `[no ci]` classification. One snapshot of the staged set covers both, avoiding
a TOCTOU window between two separate `git diff --staged` calls.

Unit tests import the pure functions directly (SourceFileLoader, mirroring
test_pr_review_submit_script.py's `_load_module()` precedent) — they are the port's
oracle against the old regex-in-Markdown behavior. Behavioral tests drive the script as
a subprocess against a real throwaway git repo (test_diff_line_lookup_script.py's
`_init_repo` precedent).

The original 3-field object was later wrapped under the standard envelope's `data` key
(schema `swb.preflight-commit/1`, see shared/docs/runtime-result-contract.md) — no
external consumer existed for the old flat shape, so this was a same-PR retrofit, not a
breaking migration.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-preflight-commit"


def _load_module():
    loader = SourceFileLoader("preflight_commit", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("preflight_commit", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["preflight_commit"] = module
    spec.loader.exec_module(module)
    return module


pc = _load_module()


# ── Behavioral test harness ─────────────────────────────────────────────────


def _git(args, *, cwd: Path):
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(cwd), env=dict(_CLEAN_ENV))
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(tmp_path: Path) -> Path:
    _git(["init", "-b", "main", str(tmp_path)], cwd=tmp_path)
    return tmp_path


def _run(args=(), *, cwd: Path, stdin: str | None = None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True, text=True,
        cwd=str(cwd),
        env=dict(_CLEAN_ENV),
    )


# ── Existence ────────────────────────────────────────────────────────────────


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-preflight-commit must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-preflight-commit must be executable (chmod +x)"


# ── Unit: pure-function port fidelity — positive/negative matrix migrated from
#    tests/test_workflow_commit_and_pr_secret_scan.py's old regex-in-Markdown test ──


POSITIVE_FILENAMES = [
    ".env",
    ".env.local",
    ".env.production",
    "prod.env",
    "path/to/.env",
    "private.pem",
    "tls.key",
    "credentials.json",
    "secrets.yaml",
    "secrets.json",
    "secret.yml",
    "Secrets.yaml",
    "config/credentials.json",
    "certs/private.pem",
    "path/to/secrets.yaml",
    "my.sample.pem",
]

NEGATIVE_FILENAMES = [
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    ".env.EXAMPLE",
    ".env.Sample",
    "secrets.example.yaml",
    "secrets.sample.json",
    "README.md",
    "src/main.py",
    "package.json",
    "Cargo.lock",
    "Makefile",
]


def test_positive_matrix_flagged():
    for fname in POSITIVE_FILENAMES:
        assert pc.is_suspicious(fname), f"expected {fname!r} to be flagged suspicious"


def test_negative_matrix_not_flagged():
    for fname in NEGATIVE_FILENAMES:
        assert not pc.is_suspicious(fname), f"expected {fname!r} NOT to be flagged suspicious"


def test_filenames_with_spaces():
    # Verified against real grep: the positive pattern is anchored on (^|/), so a
    # bare "secrets.*" only matches at the very start of the path or right after a
    # "/" — "my secrets.yaml" has neither, so it is NOT flagged (port-verified, not
    # a bug in this port). "path with space/.env" and "a b.pem" both have a
    # qualifying anchor and are flagged.
    for fname in ["path with space/.env", "a b.pem"]:
        assert pc.is_suspicious(fname), f"expected {fname!r} to be flagged suspicious"
    assert not pc.is_suspicious("my secrets.yaml")
    assert not pc.is_suspicious("docs/my notes.md")


def test_port_fidelity_non_ascii_quote_and_newline():
    """Regression lock for the -z decode fix: a plain grep|grep pipeline over
    core.quotePath-quoted paths misses all three of these — verified against real git."""
    assert pc.is_suspicious("Ünïcödé.env")
    assert pc.is_suspicious('weird"quote.pem')
    assert pc.is_suspicious("a.pem\nb")


def test_exclusion_is_ascii_exact_not_unicode_folding():
    """"secrets.ſample" (long s, U+017F) is positively matched by the detector — [a-z]
    under re.IGNORECASE folds ſ to s, which is the deliberate widening. But the
    exclusion pass is a literal str.lower().endswith() check, and str.lower() does
    NOT fold ſ to s, so the file is correctly NOT excluded — still flagged. A
    regex-based exclusion with re.IGNORECASE would have folded it and wrongly
    suppressed a real positive (the fail-open regression this design avoids)."""
    assert pc.is_suspicious("secrets.ſample")
    assert not pc.is_suspicious("secrets.sample")


# ── Unit: docs-only truth table ─────────────────────────────────────────────


def test_docs_only_truth_table():
    truthy = [
        "README.md",
        "docs/a.png",
        "docs/guide.md",
        ".github/CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/bug.md",  # pins preserved (not prose-described) behavior
    ]
    falsy = [
        ".github/CODEOWNERS",  # proves the .github/ alternative isn't a blanket
        "skills/x/SKILL.md",
        "commands/y.md",
        "agents/z.md",
        "src/main.py",
    ]
    for path in truthy:
        assert pc.is_docs(path), f"expected {path!r} to be docs"
    for path in falsy:
        assert not pc.is_docs(path), f"expected {path!r} NOT to be docs"
    assert not pc.is_docs("a.md\nb")  # control-char path is never docs


def test_is_docs_only_empty_set_is_false():
    assert pc.is_docs_only([]) is False


def test_is_docs_only_all_docs_true():
    assert pc.is_docs_only(["README.md", "docs/guide.md"]) is True


def test_is_docs_only_mixed_false():
    assert pc.is_docs_only(["README.md", "src/main.py"]) is False


# ── Behavioral: real git repo ────────────────────────────────────────────────


def test_suspicious_file_reported_and_template_spared(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / ".env").write_text("SECRET=1\n")
    (repo / ".env.example").write_text("SECRET=\n")
    _git(["add", ".env", ".env.example"], cwd=repo)

    result = _run(cwd=repo)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["suspicious"] == [".env"]
    assert set(payload["data"]["staged"]) == {".env", ".env.example"}


def test_quoted_path_fidelity_round_trips_through_json(tmp_path):
    """Regression lock: real git quotes these under default core.quotePath. -z must
    yield them raw, and they must appear verbatim in both staged and suspicious."""
    repo = _init_repo(tmp_path)
    names = ['weird"quote.pem', "back\\slash.key", "Ünïcödé.env"]
    for name in names:
        (repo / name).write_bytes(b"x")
        _git(["add", "--", name], cwd=repo)

    result = _run(cwd=repo)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload["data"]["staged"]) == set(names)
    assert set(payload["data"]["suspicious"]) == set(names)


def test_spaces_round_trip_verbatim(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "my secrets.yaml").write_text("x")
    _git(["add", "my secrets.yaml"], cwd=repo)

    result = _run(cwd=repo)
    payload = json.loads(result.stdout)
    assert payload["data"]["staged"] == ["my secrets.yaml"]


def test_mixed_set_and_runtime_markdown_not_docs_only(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("x")
    (repo / "main.py").write_text("x")
    _git(["add", "README.md", "main.py"], cwd=repo)
    result = _run(cwd=repo)
    assert json.loads(result.stdout)["data"]["docs_only"] is False

    repo3_dir = tmp_path / "repo3"
    repo3_dir.mkdir()
    repo3 = _init_repo(repo3_dir)
    (repo3 / "skills").mkdir()
    (repo3 / "skills" / "x.md").write_text("x")
    _git(["add", "skills/x.md"], cwd=repo3)
    result3 = _run(cwd=repo3)
    assert json.loads(result3.stdout)["data"]["docs_only"] is False


def test_unborn_head_no_commits_yet(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.txt").write_text("x")
    _git(["add", "a.txt"], cwd=repo)

    result = _run(cwd=repo)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["staged"] == ["a.txt"]


def test_index_not_mutated(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.txt").write_text("x")
    _git(["add", "a.txt"], cwd=repo)

    before_status = _git(["status", "--porcelain"], cwd=repo).stdout
    before_staged = _git(["diff", "--staged", "--name-only"], cwd=repo).stdout

    _run(cwd=repo)

    after_status = _git(["status", "--porcelain"], cwd=repo).stdout
    after_staged = _git(["diff", "--staged", "--name-only"], cwd=repo).stdout
    assert before_status == after_status
    assert before_staged == after_staged


def test_fails_closed_outside_git_repo(tmp_path):
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    result = _run(cwd=non_repo)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() != ""


def test_fails_closed_on_missing_git_binary(monkeypatch, capsys):
    """OSError (e.g. FileNotFoundError from a missing git on PATH), not just a non-zero
    git exit, must produce the module's own clean stderr message and exit 1 — not an
    uncaught traceback."""
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(pc.subprocess, "run", _raise)
    assert pc.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "swe-workbench-preflight-commit:" in captured.err


def test_bogus_flag_exits_2(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(["--bogus"], cwd=repo)
    assert result.returncode == 2
    assert result.stdout == ""


def test_stray_positional_exits_2(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(["extra"], cwd=repo)
    assert result.returncode == 2


def test_help_exits_0_and_states_caveat(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(["--help"], cwd=repo)
    assert result.returncode == 0
    assert "no obvious filename red flags" in result.stdout


def test_stdout_is_exactly_one_envelope_with_data_holding_three_keys(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("x")
    _git(["add", "README.md"], cwd=repo)

    result = _run(cwd=repo)
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"schema", "status", "data", "warnings"}
    assert payload["schema"] == "swb.preflight-commit/1"
    assert payload["status"] == "ok"
    assert payload["warnings"] == []
    assert set(payload["data"].keys()) == {"staged", "suspicious", "docs_only"}


def test_envelope_round_trips_through_result_check(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("x")
    _git(["add", "README.md"], cwd=repo)

    preflight = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=str(repo), env=dict(_CLEAN_ENV),
    )
    checker = ROOT / "bin" / "swe-workbench-result-check"
    checked = subprocess.run(
        [sys.executable, str(checker), "swb.preflight-commit/1"],
        input=preflight.stdout, capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == json.loads(preflight.stdout)
