"""Behavior tests for the prepared merged-cleanup runtime."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-cleanup-merged"


def _initialize_repo(path: Path) -> None:
    remote = path.parent / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial"], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", str(remote)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "checkout", "-qb", "feature/cleanup"], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "feature/cleanup"], check=True, env=dict(_CLEAN_ENV))


def _fake_gh(directory: Path, response: dict[str, object]) -> dict[str, str]:
    directory.mkdir()
    gh = directory / "gh"
    gh.write_text("#!/usr/bin/env python3\nimport os\nprint(os.environ['FAKE_GH_RESPONSE'])\n")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    return {"PATH": f"{directory}{os.pathsep}{_CLEAN_ENV['PATH']}", "FAKE_GH_RESPONSE": json.dumps(response)}


def _merged_response(head_sha: str) -> dict[str, object]:
    return {
        "state": "MERGED",
        "mergedAt": "2026-10-11T00:00:00Z",
        "url": "https://github.com/example/repository/pull/12",
        "headRefName": "feature/cleanup",
        "headRefOid": head_sha,
        "baseRefName": "main",
        "body": "",
    }


def _prepare(repo: Path, state_dir: Path, fake_bin: Path, response: dict[str, object]):
    return subprocess.run(
        [
            str(SCRIPT),
            "prepare",
            "--pr",
            "12",
            "--repo",
            "example/repository",
            "--as",
            "claude",
            "--session-ref-env",
            "CLAUDE_CODE_SESSION_ID",
            "--deferred-follow-up",
            "not_required",
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        env={
            **_CLEAN_ENV,
            **_fake_gh(fake_bin, response),
            "CLAUDE_CODE_SESSION_ID": "cleanup-test-session",
            "SWE_WORKBENCH_CLEANUP_STATE_DIR": str(state_dir),
        },
    )


def test_prepare_seals_merged_current_worktree_request(tmp_path: Path) -> None:
    assert SCRIPT.is_file(), "bin/swe-workbench-cleanup-merged must exist"
    repo = tmp_path / "repo"
    _initialize_repo(repo)

    head_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    ).stdout.strip()
    result = _prepare(repo, tmp_path / "state", tmp_path / "bin", _merged_response(head_sha))

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["schema"] == "swb.cleanup-merged/1"
    assert envelope["status"] == "ok"
    assert envelope["data"]["phase"] == "prepared"
    assert envelope["data"]["completed"] is False
    request_id = envelope["data"]["request_id"]
    request_path = tmp_path / "state" / "requests" / f"{request_id}.json"
    request = json.loads(request_path.read_text())
    assert request["session_sha256"] != "cleanup-test-session"
    assert request["worktree_root"] == str(repo.resolve())
    assert request_path.stat().st_mode & 0o777 == 0o600
    assert envelope["data"]["request_id"]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({**_merged_response("a" * 40), "state": "OPEN"}, "not merged"),
        ({**_merged_response("a" * 40), "mergedAt": None}, "not merged"),
        ({**_merged_response("a" * 40), "url": "https://github.com/other/repo/pull/12"}, "URL"),
    ],
)
def test_prepare_rejects_non_merged_or_mismatched_pull_request(
    tmp_path: Path, response: dict[str, object], expected: str
) -> None:
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    result = _prepare(repo, tmp_path / "state", tmp_path / "bin", response)

    assert result.returncode != 0
    assert expected.lower() in result.stderr.lower()


def test_prepare_requires_the_current_pr_head_and_fixed_session_environment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    head_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    ).stdout.strip()
    response = {**_merged_response(head_sha), "headRefName": "other-branch"}

    result = _prepare(repo, tmp_path / "state", tmp_path / "bin", response)
    assert result.returncode != 0
    assert "current worktree" in result.stderr

    wrong_env = subprocess.run(
        [
            str(SCRIPT),
            "prepare",
            "--pr", "12",
            "--repo", "example/repository",
            "--as", "claude",
            "--session-ref-env", "PI_SESSION_ID",
            "--deferred-follow-up", "not_required",
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        env={**_CLEAN_ENV, **_fake_gh(tmp_path / "other-bin", _merged_response(head_sha)), "PI_SESSION_ID": "wrong"},
    )
    assert wrong_env.returncode != 0
    assert "session-ref-env" in wrong_env.stderr
