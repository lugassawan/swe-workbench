"""Tests for bin/swe-workbench-repo-scope — owner-repo slug resolution.

Tier S bare-scalar contract (shared/docs/runtime-result-contract.md): the slug
on stdout and nothing else; exit 1 with empty stdout when unresolvable —
callers treat that as "legacy un-scoped naming", never a failure
of their own flow.
"""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "bin" / "swe-workbench-repo-scope"


def run_script(*args: str, cwd=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
        cwd=str(cwd) if cwd else None,
    )


def test_explicit_repo_prints_slug():
    r = run_script("--repo", "octocat/widgets")
    assert r.returncode == 0
    assert r.stdout == "7-octocat-widgets\n"


def test_explicit_repo_length_prefixes_owner():
    # Real-world case: "swe-workbench" itself has a hyphen in the repo name.
    # len("lugassawan") == 10.
    r = run_script("--repo", "lugassawan/swe-workbench")
    assert r.returncode == 0
    assert r.stdout == "10-lugassawan-swe-workbench\n"


@pytest.mark.parametrize(
    "pair_a,pair_b",
    [
        ("acme-app/foo", "acme/app-foo"),
        ("a-b-c/d", "a/b-c-d"),
    ],
)
def test_hyphen_split_pairs_never_collide(pair_a, pair_b):
    # Plain tr '/' '-' collapses both "acme-app/foo" and "acme/app-foo" to
    # "acme-app-foo" — exactly the collision that breaks the "never remove
    # artifacts belonging to a different repository" guarantee this scoping
    # scheme exists to provide. A hyphen-doubling escape is ALSO not
    # injective (see test_leading_hyphen_split_collides_under_doubling_scheme
    # below) — only the length-prefix scheme this script now uses avoids
    # both collision classes.
    slug_a = run_script("--repo", pair_a).stdout
    slug_b = run_script("--repo", pair_b).stdout
    assert slug_a != slug_b
    assert slug_a != "" and slug_b != ""


def test_leading_hyphen_split_collides_under_doubling_scheme():
    # A hyphen-doubling escape (owner.replace('-','--') + '-' + repo.replace('-','--'))
    # was tried first and is NOT actually injective: owner='a-'/repo='b' and
    # owner='a'/repo='-b' both produce 'a---b' under that scheme, since doubling
    # can't distinguish "this hyphen is escaped" from "this hyphen starts the
    # separator run". The length-prefix scheme this script actually uses must
    # still distinguish this exact pair.
    slug_a = run_script("--repo", "a-/b").stdout
    slug_b = run_script("--repo", "a/-b").stdout
    assert slug_a != slug_b
    assert slug_a != "" and slug_b != ""


@pytest.mark.parametrize("bad", ["nodoublecolon", "a/b/c", "../evil", "a b/c", "a/"])
def test_explicit_repo_rejects_malformed(bad):
    r = run_script("--repo", bad)
    assert r.returncode == 1
    assert r.stdout == ""


@pytest.mark.parametrize("mode", ["explicit", "pr_json", "origin"])
def test_dot_github_repo_accepted_consistently(mode, tmp_path):
    # GitHub's special ".github" repo starts with '.', not alphanumeric —
    # resolve_explicit used to reject it while resolve_pr_json/resolve_origin
    # accepted it (inconsistent shape validation across the three paths).
    if mode == "explicit":
        r = run_script("--repo", "octocat/.github")
    elif mode == "pr_json":
        f = tmp_path / "1.json"
        f.write_text(json.dumps({"url": "https://github.com/octocat/.github/pull/1"}))
        r = run_script("--pr-json", str(f))
    else:
        repo = _init_repo_with_origin(tmp_path, "https://github.com/octocat/.github.git")
        r = run_script(cwd=repo)
    assert r.returncode == 0, f"stderr/stdout: {r.stderr!r} {r.stdout!r}"
    assert r.stdout == "7-octocat-.github\n"


def test_pr_json_url_resolution(tmp_path):
    f = tmp_path / "42.json"
    f.write_text(json.dumps({"url": "https://github.com/foo/bar/pull/42"}))
    r = run_script("--pr-json", str(f))
    assert r.returncode == 0
    assert r.stdout == "3-foo-bar\n"


def test_pr_json_without_url_fails(tmp_path):
    f = tmp_path / "42.json"
    f.write_text(json.dumps({"state": "OPEN"}))
    r = run_script("--pr-json", str(f))
    assert r.returncode == 1
    assert r.stdout == ""


def test_pr_json_missing_file_fails(tmp_path):
    r = run_script("--pr-json", str(tmp_path / "nope.json"))
    assert r.returncode == 1
    assert r.stdout == ""


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   env=dict(_CLEAN_ENV), capture_output=True)


def _init_repo_with_origin(tmp_path: Path, url: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True,
                   env=dict(_CLEAN_ENV), capture_output=True)
    _git("remote", "add", "origin", url, cwd=repo)
    return repo


def test_origin_remote_resolution(tmp_path):
    repo = _init_repo_with_origin(tmp_path, "https://github.com/octocat/widgets.git")
    r = run_script(cwd=repo)
    assert r.returncode == 0
    assert r.stdout == "7-octocat-widgets\n"


def test_origin_https_remote_without_dot_git_suffix(tmp_path):
    repo = _init_repo_with_origin(tmp_path, "https://github.com/octocat/widgets")
    r = run_script(cwd=repo)
    assert r.returncode == 0
    assert r.stdout == "7-octocat-widgets\n"


def test_origin_ssh_remote_resolution(tmp_path):
    repo = _init_repo_with_origin(tmp_path, "git@github.com:octocat/widgets.git")
    r = run_script(cwd=repo)
    assert r.returncode == 0
    assert r.stdout == "7-octocat-widgets\n"


def test_no_origin_fails(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    r = run_script(cwd=d)
    assert r.returncode == 1
    assert r.stdout == ""


def test_unrecognized_flag_fails():
    r = run_script("--bogus", "x")
    assert r.returncode == 1
    assert r.stdout == ""


def test_extra_arguments_rejected():
    r = run_script("--repo", "octocat/widgets", "junk")
    assert r.returncode == 1
    assert r.stdout == ""
