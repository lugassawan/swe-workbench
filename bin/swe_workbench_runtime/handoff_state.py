"""Persist and synchronize the handoff lease state shared by runtime commands."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

HARNESSES = frozenset({"claude", "pi"})
LEASE_SCHEMA_VERSION = 1
STATE_DIRECTORY_NAME = Path("swe-workbench") / "handoff" / "v1"


class HandoffStateError(Exception):
    """Raise when the handoff lease state cannot be safely used."""


@dataclass(frozen=True)
class StatePaths:
    """Locate persisted handoff state for a repository worktree."""

    root: Path

    @classmethod
    def from_environment(cls) -> StatePaths:
        override = os.environ.get("SWE_WORKBENCH_HANDOFF_STATE_DIR")
        if override:
            return cls(Path(override).expanduser())
        xdg_state_home = os.environ.get("XDG_STATE_HOME")
        state_home = Path(xdg_state_home).expanduser() if xdg_state_home else Path.home() / ".local" / "state"
        return cls(state_home / STATE_DIRECTORY_NAME)

    def workspace_directory(self, repo_key: str | object, worktree_key: str | None = None) -> Path:
        """Return a workspace directory from keys or a compatible workspace object."""

        if worktree_key is None:
            worktree_key = getattr(repo_key, "worktree_key", None)
            repo_key = getattr(repo_key, "repo_key", None)
        if not isinstance(repo_key, str) or not isinstance(worktree_key, str):
            raise HandoffStateError("workspace identity must include repository and worktree keys")
        return self.root / "workspaces" / repo_key / worktree_key


def sha256_text(value: str) -> str:
    """Return the stable SHA-256 key for a canonical identity string."""

    return hashlib.sha256(value.encode()).hexdigest()


def clean_git_environment() -> dict[str, str]:
    """Return environment without inherited Git working-directory overrides."""

    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def git_text(arguments: list[str], cwd: Path) -> str:
    """Run Git and return its decoded stdout or raise a state error."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            cwd=cwd,
            env=clean_git_environment(),
            check=False,
        )
    except OSError as error:
        raise HandoffStateError(f"could not execute git: {error}") from error
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise HandoffStateError(message or f"git {' '.join(arguments)} failed")
    return result.stdout.decode("utf-8", errors="surrogateescape").strip()


def worktree_identity(root: Path) -> tuple[str, str]:
    """Return canonical repository and worktree keys for a live Git worktree."""

    resolved_root = root.resolve()
    common_directory = Path(git_text(["rev-parse", "--git-common-dir"], resolved_root))
    if not common_directory.is_absolute():
        common_directory = resolved_root / common_directory
    return sha256_text(str(common_directory.resolve())), sha256_text(str(resolved_root))


def registered_worktree_roots(root: Path, repo_key: str) -> set[Path]:
    """Return the live registered worktrees that belong to the supplied repository."""

    records = git_text(["worktree", "list", "--porcelain", "-z"], root).encode("utf-8", errors="surrogateescape").split(b"\0")
    roots: set[Path] = set()
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if not record.startswith(b"worktree "):
            raise HandoffStateError("git worktree list returned an invalid porcelain record")
        candidate = Path(record[9:].decode("utf-8", errors="surrogateescape")).resolve()
        prunable = False
        while index < len(records) and records[index]:
            if records[index].startswith(b"prunable"):
                prunable = True
            index += 1
        if prunable or not candidate.is_dir():
            continue
        candidate_repo_key, _ = worktree_identity(candidate)
        if candidate_repo_key == repo_key:
            roots.add(candidate)
    return roots


def require_registered_worktree(root: Path, repo_key: str) -> None:
    """Reject a target that is no longer a live registered worktree."""

    resolved_root = root.resolve()
    if resolved_root not in registered_worktree_roots(resolved_root, repo_key):
        raise HandoffStateError("worktree is not a registered live worktree")


def ensure_owner_directory(path: Path) -> None:
    """Create an owner-only state directory."""

    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def fsync_directory(path: Path) -> None:
    """Sync a directory after an atomic state transition."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        raise HandoffStateError(f"could not open state directory for sync: {error}") from error
    try:
        os.fsync(descriptor)
    except OSError as error:
        raise HandoffStateError(f"could not sync state directory: {error}") from error
    finally:
        os.close(descriptor)


def write_atomic(path: Path, content: str) -> None:
    """Write owner-only state atomically and durably."""

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except OSError as error:
        raise HandoffStateError(f"could not write checkpoint state: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@contextmanager
def workspace_flock(workspace_directory: Path, lock_name: str) -> Iterator[None]:
    """Serialize a critical section across processes with an exclusive lock."""

    try:
        descriptor = os.open(workspace_directory / lock_name, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as error:
        raise HandoffStateError(f"could not open the workspace {lock_name}: {error}") from error
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as error:
        raise HandoffStateError(f"could not lock the workspace ({lock_name}): {error}") from error
    finally:
        os.close(descriptor)


def valid_session_ref(value: object) -> bool:
    """Return whether a session reference is safe to persist in lease state."""

    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 256
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def load_lease(workspace_directory: Path) -> dict[str, object] | None:
    """Load and validate a worktree lease, if one exists."""

    lease_path = workspace_directory / "lease.json"
    try:
        metadata = lease_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise HandoffStateError(f"could not inspect the handoff lease: {error}") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise HandoffStateError("handoff lease is not an owner-only regular file")
    try:
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HandoffStateError(f"could not read the handoff lease: {error}") from error
    if not isinstance(lease, dict):
        raise HandoffStateError("handoff lease is malformed")
    schema_version = lease.get("schema_version")
    owner = lease.get("owner_harness")
    epoch = lease.get("epoch")
    checkpoint_id = lease.get("checkpoint_id")
    receiver_session_ref = lease.get("receiver_session_ref")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != LEASE_SCHEMA_VERSION
        or not isinstance(owner, str)
        or owner not in {*HARNESSES, "released"}
        or not isinstance(epoch, int)
        or isinstance(epoch, bool)
        or not isinstance(checkpoint_id, str)
        or not checkpoint_id
        or (owner in HARNESSES and not valid_session_ref(receiver_session_ref))
        or (owner == "released" and receiver_session_ref is not None)
    ):
        raise HandoffStateError("handoff lease is malformed")
    return lease
