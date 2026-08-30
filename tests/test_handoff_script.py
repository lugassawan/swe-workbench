"""Behavior tests for the cross-harness handoff runtime."""

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
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
    for subcommand in ("create", "show", "status-segment"):
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
