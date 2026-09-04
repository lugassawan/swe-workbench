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
    assert r.stdout == "octocat-widgets\n"


def test_explicit_repo_doubles_internal_hyphens():
    # Real-world case: "swe-workbench" itself has a hyphen in the repo name.
    r = run_script("--repo", "lugassawan/swe-workbench")
    assert r.returncode == 0
    assert r.stdout == "lugassawan-swe--workbench\n"


@pytest.mark.parametrize(
    "pair_a,pair_b",
    [
        ("acme-app/foo", "acme/app-foo"),
        ("a-b-c/d", "a/b-c-d"),
    ],
)
def test_hyphen_split_pairs_never_collide(pair_a, pair_b):
    # Without doubling, "acme-app/foo" and "acme/app-foo" both collapse to
    # "acme-app-foo" under a plain tr '/' '-' — exactly the collision that
    # breaks the "never remove artifacts belonging to a different
    # repository" guarantee this scoping scheme exists to provide.
    slug_a = run_script("--repo", pair_a).stdout
    slug_b = run_script("--repo", pair_b).stdout
    assert slug_a != slug_b
    assert slug_a != "" and slug_b != ""


@pytest.mark.parametrize("bad", ["nodoublecolon", "a/b/c", "../evil", "a b/c", "a/"])
def test_explicit_repo_rejects_malformed(bad):
    r = run_script("--repo", bad)
    assert r.returncode == 1
    assert r.stdout == ""


def test_pr_json_url_resolution(tmp_path):
    f = tmp_path / "42.json"
    f.write_text(json.dumps({"url": "https://github.com/foo/bar/pull/42"}))
    r = run_script("--pr-json", str(f))
    assert r.returncode == 0
    assert r.stdout == "foo-bar\n"


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
    assert r.stdout == "octocat-widgets\n"


def test_origin_https_remote_without_dot_git_suffix(tmp_path):
    repo = _init_repo_with_origin(tmp_path, "https://github.com/octocat/widgets")
    r = run_script(cwd=repo)
    assert r.returncode == 0
    assert r.stdout == "octocat-widgets\n"


def test_origin_ssh_remote_resolution(tmp_path):
    repo = _init_repo_with_origin(tmp_path, "git@github.com:octocat/widgets.git")
    r = run_script(cwd=repo)
    assert r.returncode == 0
    assert r.stdout == "octocat-widgets\n"


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
