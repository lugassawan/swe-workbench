"""Tests for bin/swe-workbench-plan-evidence.

Behavioral tests drive the script as a subprocess against a throwaway bare
origin plus clone under tmp_path — no network, no real paths. The default
`_CLEAN_ENV` already strips GIT_* and CLAUDE_CODE_SESSION_ID and sets
GIT_TERMINAL_PROMPT=0, so a misconfigured remote fails fast instead of
prompting.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-plan-evidence"
RESULT_CHECK = ROOT / "bin" / "swe-workbench-result-check"


# ── Harness ─────────────────────────────────────────────────────────────────


def _git(args, *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(cwd), env=dict(_CLEAN_ENV)
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def _configure(repo: Path) -> None:
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test Fixture"], cwd=repo)


def _commit(repo: Path, rel: str, content: str, msg: str = "change") -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(["add", rel], cwd=repo)
    _git(["commit", "-m", msg], cwd=repo)
    return _git(["rev-parse", "HEAD"], cwd=repo)


def _make_origin_and_clone(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (origin_bare, clone, pusher) with one shared initial commit."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", "-b", "main", str(origin)], cwd=tmp_path)
    pusher = tmp_path / "pusher"
    _git(["clone", str(origin), str(pusher)], cwd=tmp_path)
    _configure(pusher)
    _git(["checkout", "-b", "main"], cwd=pusher)
    _commit(pusher, "README.md", "hello\n", "initial")
    _commit(pusher, "skills/a.md", "a\n", "add a")
    _git(["push", "-u", "origin", "main"], cwd=pusher)
    clone = tmp_path / "clone"
    _git(["clone", str(origin), str(clone)], cwd=tmp_path)
    _configure(clone)
    return origin, clone, pusher


def _run(args, *, cwd: Path, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=dict(env if env is not None else _CLEAN_ENV),
    )


def _evidence(args, *, cwd: Path) -> dict:
    result = _run(args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    checked = subprocess.run(
        [sys.executable, str(RESULT_CHECK), "swb.plan-evidence/1"],
        input=result.stdout,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    )
    assert checked.returncode == 0, checked.stderr
    return envelope


# ── Drift classification ────────────────────────────────────────────────────


def test_up_to_date_clone_reports_no_drift(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    env = _evidence(["--cited-file", "README.md"], cwd=clone)
    assert env["schema"] == "swb.plan-evidence/1"
    assert env["status"] == "ok"
    assert env["warnings"] == []
    data = env["data"]
    assert data["drift"] == "none"
    assert data["target"] == "main"
    assert data["head"] == _git(["rev-parse", "HEAD"], cwd=clone)
    assert data["remote_target_sha"] == data["local_target_sha"] == data["head"]
    assert data["changed_paths"] == []
    assert data["overlapping_paths"] == []
    assert data["dirty"] is False


def test_fetched_upstream_change_to_cited_file_is_overlap(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    _commit(pusher, "skills/a.md", "a2\n", "touch a")
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["fetch", "origin"], cwd=clone)
    data = _evidence(["--cited-file", "skills/a.md", "--cited-file", "README.md"], cwd=clone)["data"]
    assert data["drift"] == "overlap"
    assert data["changed_paths"] == ["skills/a.md"]
    assert data["overlapping_paths"] == ["skills/a.md"]


def test_fetched_upstream_change_to_uncited_file_is_changed(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    _commit(pusher, "docs/other.md", "x\n", "touch other")
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["fetch", "origin"], cwd=clone)
    data = _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert data["drift"] == "changed"
    assert data["changed_paths"] == ["docs/other.md"]
    assert data["overlapping_paths"] == []


def test_unfetched_upstream_advance_is_unknown_and_partial(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    new_sha = _commit(pusher, "skills/a.md", "a2\n", "touch a")
    _git(["push", "origin", "main"], cwd=pusher)
    env = _evidence(["--cited-file", "skills/a.md"], cwd=clone)
    assert env["status"] == "partial"
    assert [w["code"] for w in env["warnings"]] == ["target-not-fetched"]
    assert env["data"]["drift"] == "unknown"
    assert env["data"]["remote_target_sha"] == new_sha
    assert env["data"]["local_target_sha"] != new_sha


def test_no_origin_remote_degrades_to_unknown(tmp_path):
    repo = tmp_path / "solo"
    _git(["init", "-b", "main", str(repo)], cwd=tmp_path)
    _configure(repo)
    _commit(repo, "README.md", "hello\n", "initial")
    env = _evidence(["--cited-file", "README.md"], cwd=repo)
    assert env["status"] == "partial"
    assert [w["code"] for w in env["warnings"]] == ["ls-remote-failed"]
    assert env["data"]["drift"] == "unknown"
    assert env["data"]["remote_target_sha"] == ""


def test_since_overrides_the_merge_base(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    first = _git(["rev-parse", "HEAD"], cwd=clone)
    _commit(pusher, "skills/a.md", "a2\n", "touch a")
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["pull", "--ff-only", "origin", "main"], cwd=clone)
    # HEAD now equals the target, so the merge-base shows no drift...
    assert _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]["drift"] == "none"
    # ...but rechecking from the revision the plan was written against does.
    data = _evidence(["--since", first, "--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert data["base"] == first
    assert data["drift"] == "overlap"
    assert data["overlapping_paths"] == ["skills/a.md"]


def test_dirty_tree_sets_dirty_flag(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    (clone / "scratch.txt").write_text("wip\n")
    assert _evidence([], cwd=clone)["data"]["dirty"] is True


def test_cited_file_given_absolute_or_dot_slash_still_matches(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    _commit(pusher, "skills/a.md", "a2\n", "touch a")
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["fetch", "origin"], cwd=clone)
    for spelling in ("./skills/a.md", str(clone / "skills" / "a.md")):
        data = _evidence(["--cited-file", spelling], cwd=clone)["data"]
        assert data["overlapping_paths"] == ["skills/a.md"], spelling


# ── Worktree inventory ──────────────────────────────────────────────────────


def test_other_worktree_touching_cited_file_is_listed_with_overlap(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    other = tmp_path / "other-wt"
    _git(["worktree", "add", "-b", "feature/x", str(other)], cwd=clone)
    _configure(other)
    _commit(other, "skills/a.md", "from-wt\n", "wt change")
    _commit(other, "unrelated.txt", "u\n", "wt other")
    data = _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]
    entries = {os.path.realpath(w["path"]): w for w in data["worktrees"]}
    assert os.path.realpath(str(clone)) not in entries  # current worktree excluded
    wt = entries[os.path.realpath(str(other))]
    assert wt["branch"] == "feature/x"
    assert wt["head"] == _git(["rev-parse", "HEAD"], cwd=other)
    assert wt["overlapping_paths"] == ["skills/a.md"]


def test_other_worktree_without_overlap_has_empty_overlap(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    other = tmp_path / "other-wt"
    _git(["worktree", "add", "-b", "feature/y", str(other)], cwd=clone)
    _configure(other)
    _commit(other, "unrelated.txt", "u\n", "wt other")
    data = _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert [w["overlapping_paths"] for w in data["worktrees"]] == [[]]


# ── --fetch is opt-in ───────────────────────────────────────────────────────


def test_fetch_is_opt_in_and_advances_tracking_ref(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    new_sha = _commit(pusher, "skills/a.md", "a2\n", "touch a")
    _git(["push", "origin", "main"], cwd=pusher)
    before = _git(["rev-parse", "refs/remotes/origin/main"], cwd=clone)

    _evidence(["--cited-file", "skills/a.md"], cwd=clone)
    assert _git(["rev-parse", "refs/remotes/origin/main"], cwd=clone) == before

    data = _evidence(["--fetch", "--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert _git(["rev-parse", "refs/remotes/origin/main"], cwd=clone) == new_sha
    assert data["drift"] == "overlap"


def test_fetch_failure_is_a_hard_error(tmp_path):
    repo = tmp_path / "solo"
    _git(["init", "-b", "main", str(repo)], cwd=tmp_path)
    _configure(repo)
    _commit(repo, "README.md", "hello\n", "initial")
    result = _run(["--fetch"], cwd=repo)
    assert result.returncode != 0
    assert result.stdout == ""


# ── Failure modes and CLI ───────────────────────────────────────────────────


def test_outside_a_git_repo_fails_closed(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = _run([], cwd=plain)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "git" in result.stderr.lower()


def test_help_documents_flags(tmp_path):
    result = _run(["--help"], cwd=tmp_path)
    assert result.returncode == 0
    for flag in ("--target", "--cited-file", "--since", "--fetch"):
        assert flag in result.stdout


def _load_module():
    loader = importlib.machinery.SourceFileLoader("plan_evidence_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("plan_evidence_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_git_env_disables_prompts_and_optional_locks():
    env = _load_module().git_env()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]


def test_user_supplied_ssh_command_is_respected(monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /nonexistent")
    assert _load_module().git_env()["GIT_SSH_COMMAND"] == "ssh -i /nonexistent"


# ── Review-found edge cases ─────────────────────────────────────────────────


@pytest.mark.parametrize("since", ["deadbeef" * 5, "not-a-rev"])
def test_unreachable_since_is_unknown_not_none(tmp_path, since):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    env = _evidence(["--since", since, "--cited-file", "README.md"], cwd=clone)
    assert env["status"] == "partial"
    assert env["data"]["drift"] == "unknown"
    assert "since-unreachable" in [w["code"] for w in env["warnings"]]


def test_since_value_is_never_parsed_as_a_git_option(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    marker = tmp_path / "injected.txt"
    result = _run([f"--since=--output={marker}", "--cited-file", "README.md"], cwd=clone)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_since_on_unmerged_branch_does_not_report_its_own_commits_as_drift(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    _git(["checkout", "-b", "feat"], cwd=clone)
    feat_head = _commit(clone, "skills/a.md", "feat edit\n", "feat")
    data = _evidence(["--since", feat_head, "--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert data["drift"] == "none"
    assert data["overlapping_paths"] == []


def test_renamed_cited_file_on_target_is_overlap(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    _git(["mv", "skills/a.md", "skills/b.md"], cwd=pusher)
    _git(["commit", "-m", "rename"], cwd=pusher)
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["fetch", "origin"], cwd=clone)
    data = _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert data["drift"] == "overlap"
    assert data["overlapping_paths"] == ["skills/a.md"]


def test_non_ascii_cited_file_is_matched(tmp_path):
    _, clone, pusher = _make_origin_and_clone(tmp_path)
    _commit(pusher, "docs/caf\u00e9.md", "v1\n", "add cafe")
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["pull", "--ff-only", "origin", "main"], cwd=clone)
    _commit(pusher, "docs/caf\u00e9.md", "v2\n", "edit cafe")
    _git(["push", "origin", "main"], cwd=pusher)
    _git(["fetch", "origin"], cwd=clone)
    data = _evidence(["--cited-file", "docs/caf\u00e9.md"], cwd=clone)["data"]
    assert data["overlapping_paths"] == ["docs/caf\u00e9.md"]


def test_unrelated_history_has_no_merge_base_and_warns(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    _git(["checkout", "--orphan", "solo"], cwd=clone)
    _commit(clone, "only.txt", "x\n", "orphan")
    env = _evidence(["--cited-file", "only.txt"], cwd=clone)
    assert env["status"] == "partial"
    assert env["data"]["drift"] == "unknown"
    assert "merge-base-unavailable" in [w["code"] for w in env["warnings"]]


def test_target_missing_on_origin_gets_its_own_warning_code(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    env = _evidence(["--target", "no-such-branch"], cwd=clone)
    assert env["status"] == "partial"
    assert env["data"]["drift"] == "unknown"
    assert [w["code"] for w in env["warnings"]] == ["target-missing-on-origin"]


def test_uncommitted_edit_in_sibling_worktree_counts_as_overlap(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    other = tmp_path / "other-wt"
    _git(["worktree", "add", "-b", "feature/z", str(other)], cwd=clone)
    (other / "skills" / "a.md").write_text("uncommitted\n")
    data = _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert [w["overlapping_paths"] for w in data["worktrees"]] == [["skills/a.md"]]


def test_prunable_worktree_is_not_listed(tmp_path):
    _, clone, _ = _make_origin_and_clone(tmp_path)
    gone = tmp_path / "gone-wt"
    _git(["worktree", "add", "-b", "feature/gone", str(gone)], cwd=clone)
    gone.rename(tmp_path / "moved-away")
    data = _evidence(["--cited-file", "skills/a.md"], cwd=clone)["data"]
    assert data["worktrees"] == []


def test_network_call_that_hangs_degrades_to_a_warning(tmp_path, monkeypatch):
    repo = tmp_path / "hung"
    _git(["init", "-b", "main", str(repo)], cwd=tmp_path)
    _configure(repo)
    _commit(repo, "README.md", "hello\n", "initial")
    _git(["remote", "add", "origin", "ssh://hung.invalid/repo.git"], cwd=repo)
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_SSH_COMMAND", "sleep 5")
    mod = _load_module()
    mod.NETWORK_TIMEOUT_S = 0.5
    monkeypatch.chdir(repo)
    args = mod.argparse.Namespace(target=None, cited_file=[], since=None, fetch=False)
    started = time.monotonic()
    envelope = mod.collect(args)
    assert time.monotonic() - started < 4
    assert envelope["status"] == "partial"
    assert envelope["data"]["drift"] == "unknown"
    assert "ls-remote-failed" in [w["code"] for w in envelope["warnings"]]
