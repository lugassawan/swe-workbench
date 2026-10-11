"""Behavior tests for the prepared merged-cleanup runtime."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-cleanup-merged"
sys.path.insert(0, str(ROOT / "bin"))

from swe_workbench_runtime import handoff_state


def _initialize_repo(path: Path) -> None:
    remote = path.parent / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial"], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", str(remote)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "checkout", "-qb", "feature/cleanup"], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "feature/cleanup"], check=True, env=dict(_CLEAN_ENV))


def _fake_gh(directory: Path, response: dict[str, object]) -> dict[str, str]:
    directory.mkdir(exist_ok=True)
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


def _session_environment(harness: str) -> str:
    return {"claude": "CLAUDE_CODE_SESSION_ID", "pi": "PI_SESSION_ID"}[harness]


def _prepare(
    repo: Path,
    state_dir: Path,
    fake_bin: Path,
    response: dict[str, object],
    handoff_dir: Path | None = None,
    harness: str = "claude",
) -> subprocess.CompletedProcess[str]:
    session_env = _session_environment(harness)
    return subprocess.run(
        [
            str(SCRIPT),
            "prepare",
            "--pr",
            "12",
            "--repo",
            "example/repository",
            "--as",
            harness,
            "--session-ref-env",
            session_env,
            "--deferred-follow-up",
            "not_required",
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        env={
            **_CLEAN_ENV,
            **_fake_gh(fake_bin, response),
            session_env: "cleanup-test-session",
            "SWE_WORKBENCH_CLEANUP_STATE_DIR": str(state_dir),
            **({"SWE_WORKBENCH_HANDOFF_STATE_DIR": str(handoff_dir)} if handoff_dir else {}),
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


def _run_git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=check,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    )


def _initialize_linked_repo(path: Path) -> tuple[Path, Path, Path]:
    """Create primary and target worktrees that share a real bare remote."""

    primary = path / "primary"
    target = path / "target"
    remote = path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "init", "--quiet", str(primary)], check=True, env=dict(_CLEAN_ENV))
    (primary / "README.md").write_text("primary\n")
    _run_git(primary, "add", "README.md")
    _run_git(primary, "commit", "-m", "initial")
    _run_git(primary, "branch", "-M", "main")
    _run_git(primary, "remote", "add", "origin", str(remote))
    _run_git(primary, "push", "-u", "origin", "main")
    _run_git(primary, "checkout", "-b", "feature/cleanup")
    (primary / "feature.txt").write_text("merged change\n")
    _run_git(primary, "add", "feature.txt")
    _run_git(primary, "commit", "-m", "feature")
    _run_git(primary, "push", "-u", "origin", "feature/cleanup")
    _run_git(primary, "checkout", "main")
    _run_git(primary, "worktree", "add", str(target), "feature/cleanup")
    return primary, target, remote


def _request_path(state_dir: Path, request_id: str) -> Path:
    return state_dir / "requests" / f"{request_id}.json"


def _write_lease(root: Path, handoff_dir: Path, session: str, owner_harness: str = "claude") -> Path:
    repo_key, worktree_key = handoff_state.worktree_identity(root)
    workspace = handoff_state.StatePaths(handoff_dir).workspace_directory(repo_key, worktree_key)
    handoff_state.ensure_owner_directory(workspace)
    lease_path = workspace / "lease.json"
    handoff_state.write_atomic(
        lease_path,
        json.dumps(
            {
                "schema_version": 1,
                "owner_harness": owner_harness,
                "epoch": 1,
                "checkpoint_id": "checkpoint",
                "receiver_session_ref": session,
            }
        ),
    )
    return lease_path


def _cleanup_execute_pipeline(request_id: str, harness: str) -> str:
    return (
        f'swe-workbench-cleanup-merged execute --request "{request_id}" --as {harness} '
        f'--session-ref-env {_session_environment(harness)} '
        "| swe-workbench-result-check swb.cleanup-merged/1"
    )


def _execute(
    primary: Path,
    state_dir: Path,
    handoff_dir: Path,
    fake_bin: Path,
    response: dict[str, object],
    request_id: str,
    environment: dict[str, str] | None = None,
    harness: str = "claude",
) -> subprocess.CompletedProcess[str]:
    session_env = _session_environment(harness)
    return subprocess.run(
        [
            str(SCRIPT),
            "execute",
            "--request",
            request_id,
            "--as",
            harness,
            "--session-ref-env",
            session_env,
        ],
        cwd=primary,
        capture_output=True,
        text=True,
        env={
            **_CLEAN_ENV,
            **_fake_gh(fake_bin, response),
            session_env: "cleanup-test-session",
            "SWE_WORKBENCH_CLEANUP_STATE_DIR": str(state_dir),
            "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(handoff_dir),
            **(environment or {}),
        },
    )


def _execute_pipeline(
    primary: Path,
    state_dir: Path,
    handoff_dir: Path,
    fake_bin: Path,
    response: dict[str, object],
    request_id: str,
    harness: str,
) -> subprocess.CompletedProcess[str]:
    session_env = _session_environment(harness)
    environment = {
        **_CLEAN_ENV,
        **_fake_gh(fake_bin, response),
        session_env: "cleanup-test-session",
        "SWE_WORKBENCH_CLEANUP_STATE_DIR": str(state_dir),
        "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(handoff_dir),
    }
    environment["PATH"] = f"{ROOT / 'bin'}{os.pathsep}{environment['PATH']}"
    return subprocess.run(
        ["bash", "-o", "pipefail", "-c", _cleanup_execute_pipeline(request_id, harness)],
        cwd=primary,
        capture_output=True,
        text=True,
        env=environment,
    )


def _prepare_linked_request(
    tmp_path: Path, harness: str = "claude"
) -> tuple[Path, Path, Path, Path, Path, dict[str, object], str]:
    primary, target, remote = _initialize_linked_repo(tmp_path)
    head_sha = _run_git(target, "rev-parse", "HEAD").stdout.strip()
    state_dir = tmp_path / "cleanup-state"
    handoff_dir = tmp_path / "handoff-state"
    response = _merged_response(head_sha)
    prepared = _prepare(target, state_dir, tmp_path / "fake-bin", response, handoff_dir, harness)
    assert prepared.returncode == 0, prepared.stderr
    return primary, target, remote, state_dir, handoff_dir, response, json.loads(prepared.stdout)["data"]["request_id"]


def _branch_exists(repo: Path, branch: str) -> bool:
    return _run_git(repo, "rev-parse", "--verify", f"refs/heads/{branch}", check=False).returncode == 0


def _remote_branch_exists(remote: Path, branch: str) -> bool:
    return subprocess.run(
        ["git", "--git-dir", str(remote), "show-ref", "--verify", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    ).returncode == 0


@pytest.mark.parametrize("harness", ["claude", "pi"])
def test_execute_completes_with_foreign_primary_lease_and_no_helper_worktree(
    tmp_path: Path, harness: str
) -> None:
    primary, target, remote, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path, harness)
    _write_lease(primary, handoff_dir, "foreign-session", harness)

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id, harness=harness)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["completed"] is True
    assert payload["data"]["main_sync_skipped"] is True
    assert not target.exists()
    assert not _branch_exists(primary, "feature/cleanup")
    assert not _remote_branch_exists(remote, "feature/cleanup")
    assert [line for line in _run_git(primary, "worktree", "list", "--porcelain").stdout.splitlines() if line.startswith("worktree ")] == [
        f"worktree {primary.resolve()}"
    ]


@pytest.mark.parametrize("mutation", ["tampered", "expired", "wrong_repo", "harness", "session"])
def test_execute_rejects_tampered_expired_wrong_repo_harness_or_session_request(
    tmp_path: Path, mutation: str
) -> None:
    primary, target, _, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    path = _request_path(state_dir, request_id)
    request = json.loads(path.read_text())
    if mutation == "tampered":
        request["head_ref"] = "other"
    elif mutation == "expired":
        request["expires_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "wrong_repo":
        request["repo_key"] = "wrong-repository"
    elif mutation == "harness":
        request["harness"] = "pi"
    else:
        request["session_sha256"] = "0" * 64
    handoff_state.write_atomic(path, json.dumps(request))

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert result.returncode != 0
    assert target.exists()


@pytest.mark.parametrize("condition", ["dirty", "head", "unpushed", "unregistered"])
def test_execute_revalidates_merged_head_clean_pushed_and_registered_target(
    tmp_path: Path, condition: str
) -> None:
    primary, target, _, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    if condition == "dirty":
        (target / "dirty.txt").write_text("uncommitted\n")
    elif condition in {"head", "unpushed"}:
        _run_git(target, "commit", "--allow-empty", "-m", condition)
    else:
        _run_git(primary, "worktree", "remove", "--force", str(target))

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert result.returncode != 0


def test_execute_refuses_target_lease_appearing_after_prepare(tmp_path: Path) -> None:
    primary, target, _, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    _write_lease(target, handoff_dir, "new-target-owner")

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert result.returncode != 0
    assert target.exists()
    assert _branch_exists(primary, "feature/cleanup")


def test_execute_leaves_primary_head_files_and_foreign_lease_bytes_unchanged(tmp_path: Path) -> None:
    primary, _, _, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    lease_path = _write_lease(primary, handoff_dir, "foreign-session")
    primary_head = _run_git(primary, "rev-parse", "HEAD").stdout
    primary_files = (primary / "README.md").read_bytes()
    lease_bytes = lease_path.read_bytes()

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert result.returncode == 0, result.stderr
    assert _run_git(primary, "rev-parse", "HEAD").stdout == primary_head
    assert (primary / "README.md").read_bytes() == primary_files
    assert lease_path.read_bytes() == lease_bytes


def test_execute_never_deletes_branches_when_worktree_removal_fails(tmp_path: Path) -> None:
    primary, target, remote, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    real_git = shutil.which("git")
    assert real_git
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "if '--force' in sys.argv:\n"
        "    print('unexpected forced worktree removal', file=sys.stderr)\n"
        "    raise SystemExit(99)\n"
        "if sys.argv[1:3] == ['worktree', 'remove']:\n"
        "    print('simulated worktree failure', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *sys.argv[1:]])\n"
    )
    git.chmod(git.stat().st_mode | stat.S_IXUSR)

    result = _execute(
        primary,
        state_dir,
        handoff_dir,
        fake_bin,
        response,
        request_id,
        {"PATH": f"{fake_bin}{os.pathsep}{_CLEAN_ENV['PATH']}", "REAL_GIT": real_git},
    )

    assert result.returncode != 0
    assert "simulated worktree failure" in result.stderr
    assert target.exists()
    assert _branch_exists(primary, "feature/cleanup")
    assert _remote_branch_exists(remote, "feature/cleanup")


def test_execute_validates_request_uuid_before_accessing_state_directory(tmp_path: Path) -> None:
    primary, _, _, state_dir, handoff_dir, response, _ = _prepare_linked_request(tmp_path)

    result = _execute(primary, state_dir / "missing", handoff_dir, tmp_path / "fake-bin", response, "not-a-uuid")

    assert result.returncode != 0
    assert "canonical UUID" in result.stderr


@pytest.mark.parametrize("boundary", ["worktree", "local_branch", "remote_branch"])
def test_execute_resumes_after_each_journaled_crash_boundary(tmp_path: Path, boundary: str) -> None:
    primary, target, remote, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    _run_git(primary, "worktree", "remove", "--force", str(target))
    if boundary in {"local_branch", "remote_branch"}:
        _run_git(primary, "branch", "-D", "feature/cleanup")
    if boundary == "remote_branch":
        _run_git(primary, "push", "origin", "--delete", "feature/cleanup")
    path = _request_path(state_dir, request_id)
    request = json.loads(path.read_text())
    request["status"] = "running"
    request["progress"] = {key: False for key in request["progress"]}
    handoff_state.write_atomic(path, json.dumps(request))

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["completed"] is True
    assert not _branch_exists(primary, "feature/cleanup")
    assert not _remote_branch_exists(remote, "feature/cleanup")


def test_execute_replays_completed_result_idempotently(tmp_path: Path) -> None:
    primary, _, _, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)

    first = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)
    second = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert first.returncode == second.returncode == 0
    assert json.loads(second.stdout) == json.loads(first.stdout)


def test_execute_handles_already_absent_remote_branch_as_success(tmp_path: Path) -> None:
    primary, _, remote, state_dir, handoff_dir, response, request_id = _prepare_linked_request(tmp_path)
    subprocess.run(
        ["git", "--git-dir", str(remote), "branch", "-D", "feature/cleanup"],
        check=True,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    )

    result = _execute(primary, state_dir, handoff_dir, tmp_path / "fake-bin", response, request_id)

    assert result.returncode == 0, result.stderr
    assert not _remote_branch_exists(remote, "feature/cleanup")
