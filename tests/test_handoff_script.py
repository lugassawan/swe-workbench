"""Behavior tests for the cross-harness handoff runtime."""

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-handoff"


def _semantic_payload() -> dict[str, object]:
    return {
        "goal": "Finish handoff support",
        "constraints": ["No transcripts"],
        "decisions": ["Use XDG state"],
        "progress": {"done": ["Design"], "in_progress": ["Runtime"]},
        "changed_path_intents": {"src/example.py": "runtime behavior"},
        "verification": [],
        "blockers": [],
        "risks": [],
        "exact_next_action": "Implement lease acquisition",
    }


def _create_input(operation_id: str = "state-directory-test") -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "source_harness": "claude",
        "target_harness": "pi",
        "semantic": _semantic_payload(),
    }


def _run_handoff(*args: str, input_data: dict[str, object] | None = None, env=None, cwd=None):
    assert SCRIPT.is_file(), "bin/swe-workbench-handoff must exist"
    result = subprocess.run(
        [str(SCRIPT), *args],
        input=json.dumps(input_data) if input_data is not None else None,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV) if env is None else env,
        cwd=cwd,
    )
    return result


def _initialize_repo(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial"], check=True, env=dict(_CLEAN_ENV))


def test_handoff_script_exists_and_is_executable():
    assert SCRIPT.is_file(), "bin/swe-workbench-handoff must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-handoff must be executable"


def test_help_documents_every_subcommand():
    result = _run_handoff("--help")

    assert result.returncode == 0
    assert "swe-workbench-handoff" in result.stdout
    for subcommand in ("create", "show", "status-segment", "resume", "recover", "close", "guard"):
        assert subcommand in result.stdout


def test_create_honors_handoff_state_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    result = _run_handoff(
        "create",
        input_data=_create_input(),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode == 0, result.stderr
    assert len(list(state_dir.glob("workspaces/*/*/checkpoints/*.json"))) == 1


def test_create_defaults_to_xdg_handoff_state_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    xdg_state_home = tmp_path / "xdg-state"

    result = _run_handoff(
        "create",
        input_data=_create_input(),
        cwd=repo,
        env={**_CLEAN_ENV, "XDG_STATE_HOME": str(xdg_state_home)},
    )

    assert result.returncode == 0, result.stderr
    assert len(list(xdg_state_home.glob("swe-workbench/handoff/v1/workspaces/*/*/checkpoints/*.json"))) == 1


def _create_checkpoint(repo: Path, state_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    result = _run_handoff(
        "create",
        input_data=payload,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _checkpoint(state_dir: Path, checkpoint_id: str) -> dict[str, object]:
    path = next(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))
    return json.loads(path.read_text())


def test_create_returns_an_idempotent_checkpoint_envelope(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("repeatable-create")

    first = _create_checkpoint(repo, state_dir, payload)
    second = _create_checkpoint(repo, state_dir, payload)

    assert first["schema"] == "swb.handoff/1"
    assert first["status"] == "ok"
    assert first["warnings"] == []
    assert first["data"]["checkpoint_id"] == second["data"]["checkpoint_id"]
    assert len(list(state_dir.glob("workspaces/*/*/checkpoints/*.json"))) == 1


def test_create_persists_a_uuidv7_checkpoint_with_canonical_content_hash(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    result = _create_checkpoint(repo, state_dir, _create_input("uuidv7-checkpoint"))
    checkpoint = _checkpoint(state_dir, result["data"]["checkpoint_id"])

    assert checkpoint["schema_version"] == 1
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        checkpoint["checkpoint_id"],
    )
    content = {key: value for key, value in checkpoint.items() if key != "content_sha256"}
    expected_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert checkpoint["content_sha256"] == expected_hash


def test_create_uses_canonical_repository_and_worktree_keys(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    result = _create_checkpoint(repo, state_dir, _create_input("canonical-keys"))
    checkpoint = _checkpoint(state_dir, result["data"]["checkpoint_id"])

    expected_repo_key = hashlib.sha256(str((repo / ".git").resolve()).encode()).hexdigest()
    expected_worktree_key = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()
    assert checkpoint["repo_key"] == expected_repo_key
    assert checkpoint["worktree_key"] == expected_worktree_key
    assert checkpoint["worktree_root"] == str(repo.resolve())


def test_create_persists_only_changed_path_metadata_and_fingerprint_changes_with_content(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    tracked_file = repo / "tracked.txt"
    tracked_file.write_text("initial\n")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "add tracked file"],
        check=True,
        env=dict(_CLEAN_ENV),
    )
    state_dir = tmp_path / "state"
    semantic = _semantic_payload()
    semantic["changed_path_intents"] = {"tracked.txt": "runtime behavior"}

    tracked_file.write_text("first dirty version\n")
    first = _create_checkpoint(
        repo,
        state_dir,
        {"operation_id": "fingerprint-one", "source_harness": "claude", "target_harness": "pi", "semantic": semantic},
    )
    first_checkpoint = _checkpoint(state_dir, first["data"]["checkpoint_id"])

    tracked_file.write_text("second dirty version\n")
    second = _create_checkpoint(
        repo,
        state_dir,
        {"operation_id": "fingerprint-two", "source_harness": "claude", "target_harness": "pi", "semantic": semantic},
    )
    second_checkpoint = _checkpoint(state_dir, second["data"]["checkpoint_id"])

    assert first_checkpoint["dirty_fingerprint"] != second_checkpoint["dirty_fingerprint"]
    assert second_checkpoint["changed_paths"] == [
        {"intent": "runtime behavior", "path": "tracked.txt", "status": " M"}
    ]
    persisted = json.dumps(second_checkpoint, sort_keys=True)
    assert "second dirty version" not in persisted
    assert "patch" not in persisted


def test_create_makes_handoff_state_owner_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    result = _create_checkpoint(repo, state_dir, _create_input("owner-only"))
    checkpoint_id = result["data"]["checkpoint_id"]
    workspace_dir = next(state_dir.glob("workspaces/*/*"))
    checkpoint_path = workspace_dir / "checkpoints" / f"{checkpoint_id}.json"

    for directory in (state_dir, state_dir / "workspaces", workspace_dir.parent, workspace_dir, checkpoint_path.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(checkpoint_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((workspace_dir / "latest").stat().st_mode) == 0o600


def test_create_ignores_unknown_additive_semantic_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("unknown-additive")
    payload["semantic"]["future_field"] = "a future adapter field"

    result = _create_checkpoint(repo, state_dir, payload)
    checkpoint = _checkpoint(state_dir, result["data"]["checkpoint_id"])

    assert checkpoint["goal"] == "Finish handoff support"
    assert "future_field" not in checkpoint


def test_create_rejects_an_unknown_schema_major(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("unknown-schema")
    payload["schema_version"] = 2

    result = _run_handoff(
        "create",
        input_data=payload,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "schema version" in result.stderr


@pytest.mark.parametrize(
    "field, value",
    [
        ("goal", "Authorization: Bearer swb-test-token"),
        ("api_key", "swb-test-key"),
        ("messages", [{"role": "user", "content": "raw transcript excerpt"}]),
    ],
)
def test_create_rejects_secret_or_transcript_shaped_semantic_input(tmp_path, field, value):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input(f"rejected-{field}")
    payload["semantic"][field] = value

    result = _run_handoff(
        "create",
        input_data=payload,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode != 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "result",
    [
        "pytest output: 12 passed\ntraceback omitted",
        {"outcome": "passed", "stdout": "raw tool output"},
    ],
)
def test_create_rejects_unstructured_verification_result_bypasses(tmp_path, result):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("rejected-verification-result")
    payload["semantic"]["verification"] = [
        {
            "command": "python3 -m pytest",
            "label": "Focused test suite",
            "exit_status": 0,
            "timestamp": "2026-08-30T12:00:00Z",
            "result": result,
        }
    ]

    response = _run_handoff(
        "create",
        input_data=payload,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert response.returncode != 0
    assert response.stdout == ""
    assert not list(state_dir.glob("workspaces/*/*/checkpoints/*.json"))


def test_create_persists_bounded_verification_entries(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("bounded-verification")
    payload["semantic"]["verification"] = [
        {
            "command": "python3 -m pytest tests/",
            "label": "Focused suite",
            "exit_status": 0,
            "timestamp": "2026-08-30T12:00:00Z",
            "result": "passed",
        }
    ]

    result = _create_checkpoint(repo, state_dir, payload)
    checkpoint = _checkpoint(state_dir, result["data"]["checkpoint_id"])

    assert checkpoint["verification"] == [
        {
            "command": "python3 -m pytest tests/",
            "label": "Focused suite",
            "exit_status": 0,
            "timestamp": "2026-08-30T12:00:00Z",
            "result": "passed",
        }
    ]


@pytest.mark.parametrize(
    "field, value",
    [
        ("timestamp", "t" * 65),
        ("command", "c" * 513),
        ("label", "l" * 161),
        ("exit_status", 256),
    ],
)
def test_create_rejects_verification_entries_exceeding_field_bounds(tmp_path, field, value):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input(f"rejected-verification-{field}")
    payload["semantic"]["verification"] = [
        {
            "command": "python3 -m pytest",
            "label": "Focused suite",
            "exit_status": 0,
            "timestamp": "2026-08-30T12:00:00Z",
            "result": "passed",
            field: value,
        }
    ]

    response = _run_handoff(
        "create",
        input_data=payload,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert response.returncode != 0
    assert response.stdout == ""
    assert not list(state_dir.glob("workspaces/*/*/checkpoints/*.json"))


def test_show_returns_the_persisted_checkpoint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    created = _create_checkpoint(repo, state_dir, _create_input("show-checkpoint"))

    result = _run_handoff(
        "show",
        created["data"]["checkpoint_id"],
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["checkpoint"]["checkpoint_id"] == created["data"]["checkpoint_id"]


def test_concurrent_creates_for_one_operation_id_persist_a_single_checkpoint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    env = {**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)}
    _create_checkpoint(repo, state_dir, _create_input("warmup-operation"))

    worker_count = 2
    barrier = threading.Barrier(worker_count)
    outcomes: list = []

    def create_concurrently() -> None:
        barrier.wait()
        outcomes.append(_run_handoff("create", input_data=_create_input("raced-operation"), cwd=repo, env=env))

    threads = [threading.Thread(target=create_concurrently) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(outcome.returncode == 0 for outcome in outcomes), [outcome.stderr for outcome in outcomes]
    envelopes = [json.loads(outcome.stdout) for outcome in outcomes]
    assert {envelope["data"]["checkpoint_id"] for envelope in envelopes} == {
        envelopes[0]["data"]["checkpoint_id"]
    }
    checkpoints = list(state_dir.glob("workspaces/*/*/checkpoints/*.json"))
    assert len(checkpoints) == 2


def _rewrite_checkpoint_with_valid_hash(state_dir: Path, checkpoint_id: str, mutate) -> None:
    path = next(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))
    checkpoint = json.loads(path.read_text())
    mutate(checkpoint)
    content = {key: value for key, value in checkpoint.items() if key != "content_sha256"}
    checkpoint["content_sha256"] = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(checkpoint, sort_keys=True, separators=(",", ":")))


def test_show_rejects_a_hash_valid_checkpoint_with_an_unsupported_major_version(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    created = _create_checkpoint(repo, state_dir, _create_input("future-major"))
    checkpoint_id = created["data"]["checkpoint_id"]

    def bump_schema_version(checkpoint: dict) -> None:
        checkpoint["schema_version"] = 2

    _rewrite_checkpoint_with_valid_hash(state_dir, checkpoint_id, bump_schema_version)

    result = _run_handoff(
        "show",
        checkpoint_id,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "schema version" in result.stderr


def test_show_rejects_a_hash_valid_checkpoint_with_a_missing_required_field(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    created = _create_checkpoint(repo, state_dir, _create_input("missing-shape"))
    checkpoint_id = created["data"]["checkpoint_id"]

    _rewrite_checkpoint_with_valid_hash(state_dir, checkpoint_id, lambda checkpoint: checkpoint.pop("operation_id"))

    result = _run_handoff(
        "show",
        checkpoint_id,
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "operation_id" in result.stderr


def _claude_status(used_percentage: int | None, reset_window: str | None = None) -> dict[str, object]:
    rate_limit: dict[str, object] = {}
    if used_percentage is not None:
        rate_limit["used_percentage"] = used_percentage
    if reset_window is not None:
        rate_limit["resets_at"] = reset_window
    return {"rate_limits": {"five_hour": rate_limit}}


@pytest.mark.parametrize(
    ("used_percentage", "expected_text"),
    [
        (79, ""),
        (80, "handoff available"),
        (89, "handoff available"),
        (90, "handoff urgent: create a checkpoint now"),
    ],
)
def test_status_segment_uses_claude_quota_thresholds(tmp_path, used_percentage, expected_text):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)

    result = _run_handoff(
        "status-segment",
        input_data=_claude_status(used_percentage, "2026-08-30T12:00:00Z"),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(tmp_path / "state")},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected_text


def test_status_segment_ignores_absent_quota_and_context_usage(tmp_path):
    result = _run_handoff(
        "status-segment",
        input_data={"context_window": {"used_percentage": 99}},
        cwd=tmp_path,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(tmp_path / "state")},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_status_segment_replaces_the_urgent_notice_for_a_new_reset_window(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    first = _run_handoff(
        "status-segment",
        input_data=_claude_status(90, "2026-08-30T12:00:00Z"),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )
    first_notice = json.loads(next(state_dir.glob("workspaces/*/*/notices.json")).read_text())
    second = _run_handoff(
        "status-segment",
        input_data=_claude_status(90, "2026-08-30T12:00:00Z"),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )
    third = _run_handoff(
        "status-segment",
        input_data=_claude_status(90, "2026-08-30T17:00:00Z"),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )
    replaced_notice = json.loads(next(state_dir.glob("workspaces/*/*/notices.json")).read_text())

    assert first.stdout == second.stdout == third.stdout == "handoff urgent: create a checkpoint now\n"
    assert first_notice == {"provider_key": "claude.five_hour", "reset_window": "2026-08-30T12:00:00Z", "threshold": 90}
    assert replaced_notice == {"provider_key": "claude.five_hour", "reset_window": "2026-08-30T17:00:00Z", "threshold": 90}


@pytest.mark.parametrize("corrupt_state", ["not-json{", "[]"])
def test_status_segment_fails_on_a_corrupt_notices_state(tmp_path, corrupt_state):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _run_handoff(
        "status-segment",
        input_data=_claude_status(90, "2026-08-30T12:00:00Z"),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )
    next(state_dir.glob("workspaces/*/*/notices.json")).write_text(corrupt_state)

    result = _run_handoff(
        "status-segment",
        input_data=_claude_status(90, "2026-08-30T18:00:00Z"),
        cwd=repo,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "notices" in result.stderr


# ── Task 2: lease lifecycle and recovery ─────────────────────────────────────

MANDATORY_REVIEW_ACTION = (
    "Review the salvage manifest, reconcile it with the live worktree, "
    "and obtain user confirmation of intent before editing."
)


def _env_for(state_dir: Path) -> dict[str, str]:
    return {**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)}


def _lease(state_dir: Path) -> dict[str, object]:
    return json.loads(next(state_dir.glob("workspaces/*/*/lease.json")).read_text())


def _lease_for_checkpoint(state_dir: Path, checkpoint_id: str) -> dict[str, object]:
    checkpoint_path = next(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))
    return json.loads((checkpoint_path.parent.parent / "lease.json").read_text())


def _planned_checkpoint(repo: Path, state_dir: Path, operation_id: str = "planned") -> str:
    envelope = _create_checkpoint(repo, state_dir, _create_input(operation_id))
    return str(envelope["data"]["checkpoint_id"])


def _checkpoint_id(state_dir: Path, operation_id: str) -> str:
    for path in state_dir.glob("workspaces/*/*/checkpoints/*.json"):
        checkpoint = json.loads(path.read_text())
        if checkpoint["operation_id"] == operation_id:
            return str(checkpoint["checkpoint_id"])
    raise AssertionError(f"no checkpoint for operation {operation_id}")


def _resume(repo: Path, state_dir: Path, checkpoint_id: str, *extra: str):
    return _run_handoff("resume", checkpoint_id, *extra, cwd=repo, env=_env_for(state_dir))


def _backdate(state_dir: Path, checkpoint_id: str, field: str, **offset) -> None:
    def mutate(checkpoint: dict) -> None:
        checkpoint[field] = (
            (datetime.now(UTC) - timedelta(**offset)).isoformat().replace("+00:00", "Z")
        )

    _rewrite_checkpoint_with_valid_hash(state_dir, checkpoint_id, mutate)


def test_create_releases_the_source_lease_after_the_checkpoint_is_durable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    checkpoint_id = _planned_checkpoint(repo, state_dir, "release-lease")
    lease = _lease(state_dir)

    assert lease["owner_harness"] == "released"
    assert lease["epoch"] == 1
    assert lease["checkpoint_id"] == checkpoint_id
    assert lease["source_session_ref"] is None


@pytest.mark.parametrize(
    "session_args",
    [(), ("--receiver-session", "")],
    ids=["omitted", "empty"],
)
def test_resume_requires_a_nonempty_receiver_session(tmp_path, session_args):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "resume-session-required")

    result = _resume(repo, state_dir, checkpoint_id, "--as", "pi", *session_args)

    assert result.returncode != 0
    assert result.stdout == ""
    lease = _lease_for_checkpoint(state_dir, checkpoint_id)
    assert lease["owner_harness"] == "released"


def test_resume_rejects_a_stale_checkpoint_without_rebinding_the_latest_lease(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    stale_id = _planned_checkpoint(repo, state_dir, "resume-stale-first")
    latest_id = _planned_checkpoint(repo, state_dir, "resume-stale-latest")

    result = _resume(
        repo, state_dir, stale_id, "--as", "pi", "--receiver-session", "pi-receiver"
    )

    assert result.returncode != 0
    assert result.stdout == ""
    lease = _lease_for_checkpoint(state_dir, latest_id)
    assert lease["checkpoint_id"] == latest_id
    assert lease["owner_harness"] == "released"
    assert _checkpoint(state_dir, stale_id)["status"] == "open"


def test_resume_acquires_ownership_for_the_target_harness(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "resume-acquire")

    result = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["data"]["checkpoint_id"] == checkpoint_id
    assert envelope["data"]["exact_next_action"] == "Implement lease acquisition"
    assert "Do not import or reconstruct the source transcript" in envelope["data"]["instruction"]
    lease = _lease(state_dir)
    assert lease["owner_harness"] == "pi"
    assert lease["receiver_session_ref"] == "s1"
    assert lease["epoch"] == 2
    checkpoint = _checkpoint(state_dir, checkpoint_id)
    assert checkpoint["status"] == "consumed"
    assert checkpoint["consumed_at"]


def test_resume_is_idempotent_for_the_same_receiver_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "resume-idempotent")

    first = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    second = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert json.loads(first.stdout)["data"]["checkpoint_id"] == json.loads(second.stdout)["data"]["checkpoint_id"]
    assert _lease(state_dir)["epoch"] == 2


def test_resume_rejects_a_second_receiver_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "resume-second-session")

    first = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    second = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s2")

    assert first.returncode == 0, first.stderr
    assert second.returncode != 0
    assert second.stdout == ""
    assert _lease(state_dir)["receiver_session_ref"] == "s1"


def test_resume_rejects_a_harness_that_is_not_the_checkpoint_target(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "resume-wrong-harness")

    result = _resume(repo, state_dir, checkpoint_id, "--as", "claude", "--receiver-session", "s1")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "target" in result.stderr


def test_resume_fails_on_workspace_drift(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "resume-drift")
    (repo / "drift.txt").write_text("late mutation\n")

    result = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "drift" in result.stderr
    assert _lease(state_dir)["owner_harness"] == "released"


def test_create_refuses_when_a_foreign_harness_owns_the_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _planned_checkpoint(repo, state_dir, "foreign-owner-first")
    acquired = _resume(
        repo, state_dir, _checkpoint_id(state_dir, "foreign-owner-first"), "--as", "pi", "--receiver-session", "s1"
    )
    assert acquired.returncode == 0, acquired.stderr

    result = _run_handoff(
        "create",
        input_data=_create_input("foreign-owner-second"),
        cwd=repo,
        env=_env_for(state_dir),
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "lease" in result.stderr


def test_guard_allows_mutation_when_no_state_exists(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)

    result = _run_handoff("guard", "--as", "claude", cwd=repo, env=_env_for(tmp_path / "state"))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["decision"] == "allow"


def test_guard_allows_mutation_outside_a_git_workspace(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    result = _run_handoff("guard", "--as", "claude", cwd=plain, env=_env_for(tmp_path / "state"))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["decision"] == "allow"


def test_guard_denies_a_released_lease_for_both_harnesses(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "guard-released")

    for harness in ("claude", "pi"):
        result = _run_handoff("guard", "--as", harness, cwd=repo, env=_env_for(state_dir))
        assert result.returncode == 3, result.stderr
        envelope = json.loads(result.stdout)
        assert envelope["data"]["decision"] == "deny"
        assert envelope["data"]["checkpoint_id"] == checkpoint_id
        assert envelope["data"]["target_harness"] == "pi"
        assert envelope["data"]["instruction"] == f"/handoff resume {checkpoint_id}"


def test_guard_allows_only_the_bound_owner_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "guard-owner")
    acquired = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr

    allowed = _run_handoff("guard", "--as", "pi", "--session-ref", "s1", cwd=repo, env=_env_for(state_dir))
    wrong_session = _run_handoff("guard", "--as", "pi", "--session-ref", "s2", cwd=repo, env=_env_for(state_dir))
    missing_session = _run_handoff("guard", "--as", "pi", cwd=repo, env=_env_for(state_dir))
    foreign = _run_handoff("guard", "--as", "claude", cwd=repo, env=_env_for(state_dir))

    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout)["data"]["decision"] == "allow"
    assert wrong_session.returncode == 3
    assert json.loads(wrong_session.stdout)["data"]["decision"] == "deny"
    assert missing_session.returncode == 3
    assert json.loads(missing_session.stdout)["data"]["decision"] == "deny"
    assert foreign.returncode == 3
    assert json.loads(foreign.stdout)["data"]["decision"] == "deny"


def test_close_rejects_a_stale_checkpoint_without_releasing_the_current_lease(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    first_id = _planned_checkpoint(repo, state_dir, "close-stale-first")
    acquired_first = _resume(repo, state_dir, first_id, "--as", "pi", "--receiver-session", "pi-s1")
    assert acquired_first.returncode == 0, acquired_first.stderr
    closed_first = _run_handoff(
        "close", first_id, "--as", "pi", "--session-ref", "pi-s1",
        cwd=repo, env=_env_for(state_dir),
    )
    assert closed_first.returncode == 0, closed_first.stderr

    second_input = _create_input("close-stale-second")
    second_input["source_harness"] = "pi"
    second_input["target_harness"] = "claude"
    created_second = _run_handoff(
        "create", input_data=second_input, cwd=repo, env=_env_for(state_dir)
    )
    assert created_second.returncode == 0, created_second.stderr
    second_id = json.loads(created_second.stdout)["data"]["checkpoint_id"]
    acquired_second = _resume(
        repo, state_dir, second_id, "--as", "claude", "--receiver-session", "claude-s2"
    )
    assert acquired_second.returncode == 0, acquired_second.stderr

    stale_close = _run_handoff(
        "close", first_id, "--as", "claude", "--session-ref", "claude-s2",
        cwd=repo, env=_env_for(state_dir),
    )

    assert stale_close.returncode != 0
    lease = json.loads(next(state_dir.glob("workspaces/*/*/lease.json")).read_text())
    assert lease["checkpoint_id"] == second_id
    assert lease["owner_harness"] == "claude"


def test_close_rejects_wrong_harness_or_session_without_releasing_lease(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "close-authenticated")
    acquired = _resume(
        repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "pi-owner"
    )
    assert acquired.returncode == 0, acquired.stderr

    wrong_harness = _run_handoff(
        "close", checkpoint_id, "--as", "claude", "--session-ref", "pi-owner",
        cwd=repo, env=_env_for(state_dir),
    )
    wrong_session = _run_handoff(
        "close", checkpoint_id, "--as", "pi", "--session-ref", "other-session",
        cwd=repo, env=_env_for(state_dir),
    )

    assert wrong_harness.returncode != 0
    assert wrong_session.returncode != 0
    lease = _lease_for_checkpoint(state_dir, checkpoint_id)
    assert lease["owner_harness"] == "pi"
    assert lease["receiver_session_ref"] == "pi-owner"


def test_guard_rejects_an_unbound_active_lease_as_corrupt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "guard-unbound-active")
    acquired = _resume(
        repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "pi-owner"
    )
    assert acquired.returncode == 0, acquired.stderr
    lease_path = next(state_dir.glob("workspaces/*/*/lease.json"))
    lease = json.loads(lease_path.read_text())
    lease["receiver_session_ref"] = None
    lease_path.write_text(json.dumps(lease))

    result = _run_handoff(
        "guard", "--as", "pi", "--session-ref", "pi-owner",
        cwd=repo, env=_env_for(state_dir),
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "lease" in result.stderr.lower()


def test_close_returns_the_worktree_to_normal(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "close-checkpoint")
    acquired = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr

    closed = _run_handoff(
        "close", checkpoint_id, "--as", "pi", "--session-ref", "s1",
        cwd=repo, env=_env_for(state_dir),
    )

    assert closed.returncode == 0, closed.stderr
    assert not list(state_dir.glob("workspaces/*/*/lease.json"))
    guard = _run_handoff("guard", "--as", "pi", "--session-ref", "s1", cwd=repo, env=_env_for(state_dir))
    assert guard.returncode == 0, guard.stderr
    checkpoint = _checkpoint(state_dir, checkpoint_id)
    assert checkpoint["status"] == "closed"
    assert checkpoint["closed_at"]


def test_recover_requires_explicit_source_stopped(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _planned_checkpoint(repo, state_dir, "recover-gate")

    result = _run_handoff("recover", "--from", "claude", cwd=repo, env=_env_for(state_dir))

    assert result.returncode != 0
    assert result.stdout == ""
    assert "source-stopped" in result.stderr


def test_recover_builds_a_degraded_salvage_from_a_prior_semantic_checkpoint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _planned_checkpoint(repo, state_dir, "recover-prior")

    result = _run_handoff("recover", "--from", "claude", "--source-stopped", cwd=repo, env=_env_for(state_dir))

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "partial"
    assert any(warning["code"] == "degraded_recovery" for warning in envelope["warnings"])
    salvage_id = envelope["data"]["checkpoint_id"]
    salvage = _checkpoint(state_dir, salvage_id)
    assert salvage["mode"] == "salvage"
    assert salvage["recovery_quality"] == "degraded"
    assert salvage["status"] == "open"
    assert salvage["target_harness"] == "pi"
    assert salvage["goal"] == "Finish handoff support"
    assert salvage["exact_next_action"] == "Implement lease acquisition"
    assert salvage["evidence_sources"]
    lease = _lease(state_dir)
    assert lease["owner_harness"] == "released"
    assert lease["checkpoint_id"] == salvage_id


def test_recover_without_a_prior_checkpoint_omits_semantic_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    (repo / "uncommitted.txt").write_text("live work\n")
    state_dir = tmp_path / "state"

    result = _run_handoff("recover", "--from", "pi", "--source-stopped", cwd=repo, env=_env_for(state_dir))

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "partial"
    salvage = _checkpoint(state_dir, envelope["data"]["checkpoint_id"])
    assert salvage["exact_next_action"] == MANDATORY_REVIEW_ACTION
    assert "goal" in salvage["omissions"]
    assert salvage["target_harness"] == "claude"
    assert {entry["path"] for entry in salvage["changed_paths"]} == {"uncommitted.txt"}


def test_recover_rejects_a_prior_checkpoint_carrying_transcript_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "recover-transcript")

    def inject_transcript(checkpoint: dict) -> None:
        checkpoint["retainedTail"] = [{"role": "user", "content": "raw message"}]

    _rewrite_checkpoint_with_valid_hash(state_dir, checkpoint_id, inject_transcript)

    result = _run_handoff("recover", "--from", "claude", "--source-stopped", cwd=repo, env=_env_for(state_dir))

    assert result.returncode != 0
    assert result.stdout == ""
    assert "retainedTail" in result.stderr


def test_resume_requires_acknowledgement_for_degraded_checkpoints(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _planned_checkpoint(repo, state_dir, "acknowledge-prior")
    recovered = _run_handoff(
        "recover", "--from", "claude", "--source-stopped", cwd=repo, env=_env_for(state_dir)
    )
    assert recovered.returncode == 0, recovered.stderr
    salvage_id = json.loads(recovered.stdout)["data"]["checkpoint_id"]

    refused = _resume(repo, state_dir, salvage_id, "--as", "pi", "--receiver-session", "s1")
    acknowledged = _resume(
        repo, state_dir, salvage_id, "--as", "pi", "--receiver-session", "s1", "--acknowledge-degraded"
    )

    assert refused.returncode != 0
    assert refused.stdout == ""
    assert "acknowledge-degraded" in refused.stderr
    assert acknowledged.returncode == 0, acknowledged.stderr
    lease = _lease(state_dir)
    assert lease["acknowledged_at"]
    assert lease["acknowledged_by_harness"] == "pi"


def test_expired_open_checkpoints_are_cleaned_by_lifecycle_commands(tmp_path):
    stale_repo = tmp_path / "stale-repo"
    stale_repo.mkdir()
    _initialize_repo(stale_repo)
    live_repo = tmp_path / "live-repo"
    live_repo.mkdir()
    _initialize_repo(live_repo)
    state_dir = tmp_path / "state"
    stale_id = _planned_checkpoint(stale_repo, state_dir, "cleanup-expired")
    _backdate(state_dir, stale_id, "created_at", days=8)

    keep = _create_checkpoint(live_repo, state_dir, _create_input("cleanup-live"))

    assert not list(state_dir.glob(f"workspaces/*/*/checkpoints/{stale_id}.json"))
    assert list(state_dir.glob(f"workspaces/*/*/checkpoints/{keep['data']['checkpoint_id']}.json"))


def test_consumed_checkpoints_are_retained_then_cleaned(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _initialize_repo(other_repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "retention-consumed")
    acquired = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr
    closed = _run_handoff(
        "close", checkpoint_id, "--as", "pi", "--session-ref", "s1",
        cwd=repo, env=_env_for(state_dir),
    )
    assert closed.returncode == 0, closed.stderr
    assert list(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))

    _backdate(state_dir, checkpoint_id, "closed_at", hours=25)
    _create_checkpoint(other_repo, state_dir, _create_input("retention-trigger"))

    assert not list(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))


def test_cleanup_preserves_an_active_lease_checkpoint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _initialize_repo(other_repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "cleanup-active")
    acquired = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr
    _backdate(state_dir, checkpoint_id, "consumed_at", hours=25)

    _create_checkpoint(other_repo, state_dir, _create_input("cleanup-active-trigger"))

    assert list(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))
    assert _lease_for_checkpoint(state_dir, checkpoint_id)["owner_harness"] == "pi"


def test_verification_result_dict_rejection_is_a_clean_error_not_a_traceback(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("clean-rejection")
    payload["semantic"]["verification"] = [
        {
            "command": "python3 -m pytest",
            "label": "Focused suite",
            "exit_status": 0,
            "timestamp": "2026-08-30T12:00:00Z",
            "result": {"outcome": "passed"},
        }
    ]

    result = _run_handoff("create", input_data=payload, cwd=repo, env=_env_for(state_dir))

    assert result.returncode != 0
    assert result.stdout == ""
    assert "verification.result must be a bounded outcome" in result.stderr
    assert "Traceback" not in result.stderr


def test_recover_leaves_no_salvage_when_a_foreign_harness_holds_the_lease(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _planned_checkpoint(repo, state_dir, "recover-foreign-owner")
    acquired = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr

    result = _run_handoff("recover", "--from", "claude", "--source-stopped", cwd=repo, env=_env_for(state_dir))

    assert result.returncode != 0
    assert result.stdout == ""
    assert "lease" in result.stderr
    checkpoint_files = list(state_dir.glob("workspaces/*/*/checkpoints/*.json"))
    assert len(checkpoint_files) == 1
    assert _checkpoint(state_dir, checkpoint_id)["status"] == "consumed"
    assert _lease_for_checkpoint(state_dir, checkpoint_id)["owner_harness"] == "pi"


def test_end_to_end_claude_to_pi_planned_handoff_flow(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"

    created = _create_checkpoint(
        repo, state_dir, _create_input("e2e-claude-to-pi")
    )
    checkpoint_id = created["data"]["checkpoint_id"]

    resumed = _resume(repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "pi-e2e")
    assert resumed.returncode == 0, resumed.stderr
    allowed = _run_handoff(
        "guard", "--as", "pi", "--session-ref", "pi-e2e", cwd=repo, env=_env_for(state_dir)
    )
    denied = _run_handoff("guard", "--as", "claude", cwd=repo, env=_env_for(state_dir))
    assert json.loads(allowed.stdout)["data"]["decision"] == "allow"
    assert denied.returncode == 3

    closed = _run_handoff(
        "close", checkpoint_id, "--as", "pi", "--session-ref", "pi-e2e",
        cwd=repo, env=_env_for(state_dir),
    )
    assert closed.returncode == 0, closed.stderr
    assert not list(state_dir.glob("workspaces/*/*/lease.json"))

    stored = next(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json")).read_text()
    assert stored.count('"checkpoint_id"') >= 1
    for forbidden in ("diff --git", "GIT_AUTHOR", "$PATH", '"content"'):
        assert forbidden not in stored, f"checkpoint leaked {forbidden!r}"


def test_end_to_end_pi_to_claude_recovery_flow(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    payload = _create_input("e2e-pi-to-claude")
    payload["source_harness"] = "pi"
    payload["target_harness"] = "claude"
    created = _create_checkpoint(repo, state_dir, payload)
    checkpoint_id = created["data"]["checkpoint_id"]
    (repo / "dirty.txt").write_text("uncommitted work\n")

    recovered = _run_handoff(
        "recover", "--from", "pi", "--source-stopped", cwd=repo, env=_env_for(state_dir)
    )
    assert recovered.returncode == 0, recovered.stderr
    salvage = json.loads(recovered.stdout)
    assert salvage["status"] == "partial"
    salvage_id = salvage["data"]["checkpoint_id"]

    refused = _resume(
        repo, state_dir, salvage_id, "--as", "claude", "--receiver-session", "claude-e2e"
    )
    assert refused.returncode != 0

    acknowledged = _resume(
        repo, state_dir, salvage_id, "--as", "claude",
        "--receiver-session", "claude-e2e", "--acknowledge-degraded",
    )
    assert acknowledged.returncode == 0, acknowledged.stderr
    lease = _lease_for_checkpoint(state_dir, salvage_id)
    assert lease["acknowledged_by_harness"] == "claude"
    assert lease["owner_harness"] == "claude"

    closed = _run_handoff(
        "close", salvage_id, "--as", "claude", "--session-ref", "claude-e2e",
        cwd=repo, env=_env_for(state_dir),
    )
    assert closed.returncode == 0, closed.stderr
    stored = next(state_dir.glob(f"workspaces/*/*/checkpoints/{salvage_id}.json")).read_text()
    for forbidden in ("diff --git", "GIT_AUTHOR", "$PATH", '"content"'):
        assert forbidden not in stored, f"salvage checkpoint leaked {forbidden!r}"


def test_cleanup_reclaims_an_orphaned_workspace_after_expiry(tmp_path):
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _initialize_repo(other_repo)
    state_dir = tmp_path / "state"
    orphan_repo = tmp_path / "orphan-repo"
    orphan_repo.mkdir()
    _initialize_repo(orphan_repo)
    checkpoint_id = _planned_checkpoint(orphan_repo, state_dir, "cleanup-orphan")
    orphan_workspace = next(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json")).parent.parent
    acquired = _resume(orphan_repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr
    import shutil as _shutil
    _shutil.rmtree(orphan_repo)
    _backdate(state_dir, checkpoint_id, "consumed_at", hours=25)

    trigger = _create_checkpoint(other_repo, state_dir, _create_input("cleanup-orphan-trigger"))

    assert trigger["data"]["checkpoint_id"]
    assert not orphan_workspace.exists(), (
        "a workspace whose worktree root no longer exists must lose active-lease protection "
        "and be reclaimed once its retention window lapses"
    )
    assert not list(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))


def test_cleanup_retains_an_orphaned_workspace_before_expiry(tmp_path):
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    _initialize_repo(other_repo)
    state_dir = tmp_path / "state"
    orphan_repo = tmp_path / "orphan-repo"
    orphan_repo.mkdir()
    _initialize_repo(orphan_repo)
    checkpoint_id = _planned_checkpoint(orphan_repo, state_dir, "cleanup-orphan-fresh")
    acquired = _resume(orphan_repo, state_dir, checkpoint_id, "--as", "pi", "--receiver-session", "s1")
    assert acquired.returncode == 0, acquired.stderr
    import shutil as _shutil
    _shutil.rmtree(orphan_repo)

    trigger = _create_checkpoint(other_repo, state_dir, _create_input("cleanup-orphan-fresh-trigger"))

    assert trigger["data"]["checkpoint_id"]
    assert list(state_dir.glob("workspaces/*/*/lease.json")), (
        "an orphaned workspace within its normal retention window must stay reclaimable"
    )
    assert list(state_dir.glob(f"workspaces/*/*/checkpoints/{checkpoint_id}.json"))
