"""Tests for shared handoff lease-state primitives."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bin"))

from swe_workbench_runtime import handoff_state


def _initialize_repo(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial"],
        check=True,
        env=dict(_CLEAN_ENV),
    )


def test_shared_handoff_state_uses_existing_repo_and_worktree_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    linked = tmp_path / "linked tree"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(linked)],
        check=True,
        env=dict(_CLEAN_ENV),
    )

    repo_key, main_key = handoff_state.worktree_identity(repo)
    linked_repo_key, linked_key = handoff_state.worktree_identity(linked)

    assert repo_key == linked_repo_key == hashlib.sha256(str((repo / ".git").resolve()).encode()).hexdigest()
    assert main_key == hashlib.sha256(str(repo.resolve()).encode()).hexdigest()
    assert linked_key == hashlib.sha256(str(linked.resolve()).encode()).hexdigest()
    assert linked_key != main_key


def test_shared_load_lease_rejects_malformed_or_unreadable_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lease = workspace / "lease.json"
    lease.write_text(json.dumps({"schema_version": 1, "owner_harness": "claude"}))
    lease.chmod(0o600)

    with pytest.raises(handoff_state.HandoffStateError, match="malformed"):
        handoff_state.load_lease(workspace)

    lease.write_text("not json")
    with pytest.raises(handoff_state.HandoffStateError, match="could not read"):
        handoff_state.load_lease(workspace)


@pytest.mark.parametrize("kind", ["symlink", "directory", "unsafe_mode"])
def test_shared_load_lease_fails_closed_for_nonregular_or_unsafe_evidence(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lease = workspace / "lease.json"
    if kind == "symlink":
        lease.symlink_to(workspace / "missing-lease")
    elif kind == "directory":
        lease.mkdir()
    else:
        lease.write_text(json.dumps({"schema_version": 1, "owner_harness": "claude", "epoch": 1, "checkpoint_id": "id", "receiver_session_ref": "session"}))
        lease.chmod(0o644)

    with pytest.raises(handoff_state.HandoffStateError):
        handoff_state.load_lease(workspace)


def test_shared_workspace_lock_serializes_processes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    handoff_state.ensure_owner_directory(workspace)
    with handoff_state.workspace_flock(workspace, "lease.lock"):
        descriptor = os.open(workspace / "lease.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


def test_require_registered_worktree_rejects_removed_linked_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(linked)],
        check=True,
        env=dict(_CLEAN_ENV),
    )
    repo_key, _ = handoff_state.worktree_identity(repo)

    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(linked)], check=True, env=dict(_CLEAN_ENV))

    with pytest.raises(handoff_state.HandoffStateError, match="registered"):
        handoff_state.require_registered_worktree(linked, repo_key)
