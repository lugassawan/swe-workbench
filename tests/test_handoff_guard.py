"""Behavior tests for the Claude PreToolUse handoff guard (hooks/handoff_guard.py)."""

import json
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "hooks" / "handoff_guard.py"
RUNTIME = ROOT / "bin" / "swe-workbench-handoff"


def _initialize_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, env=dict(_CLEAN_ENV))
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial"],
        check=True,
        env=dict(_CLEAN_ENV),
    )


def _run_hook(payload: dict, *, state_dir: Path, plugin_root: Path = ROOT) -> subprocess.CompletedProcess:
    env = {
        **_CLEAN_ENV,
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir),
    }
    return subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=payload.get("cwd") or None,
    )


def _payload(repo: Path, tool_name: str, session_id: str = "sess-1") -> dict:
    tool_input = {"command": "true"} if tool_name == "Bash" else {"file_path": str(repo / "file.txt")}
    return {
        "session_id": session_id,
        "cwd": str(repo),
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def _runtime(*args: str, cwd: Path, state_dir: Path, input_data: dict | None = None):
    return subprocess.run(
        [str(RUNTIME), *args],
        input=json.dumps(input_data) if input_data is not None else None,
        capture_output=True,
        text=True,
        env={**_CLEAN_ENV, "SWE_WORKBENCH_HANDOFF_STATE_DIR": str(state_dir)},
        cwd=cwd,
    )


SEMANTIC = {
    "goal": "Finish handoff support",
    "constraints": [],
    "decisions": [],
    "progress": {"done": [], "in_progress": []},
    "changed_path_intents": {},
    "verification": [],
    "blockers": [],
    "risks": [],
    "exact_next_action": "Continue implementation",
}


def _create(repo: Path, state_dir: Path, target: str = "pi", source: str = "claude") -> str:
    result = _runtime(
        "create",
        cwd=repo,
        state_dir=state_dir,
        input_data={
            "operation_id": "guard-setup",
            "source_harness": source,
            "target_harness": target,
            "semantic": SEMANTIC,
        },
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]["checkpoint_id"]


def test_hook_script_exists():
    assert SCRIPT.is_file(), "hooks/handoff_guard.py must exist"


def test_allows_all_tools_when_no_handoff_state_exists(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)

    for tool_name in ("Bash", "Edit", "Write"):
        result = _run_hook(_payload(repo, tool_name), state_dir=tmp_path / "state")
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""


def test_blocks_mutating_tools_under_a_released_lease(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _create(repo, state_dir, target="pi")

    for tool_name in ("Bash", "Edit", "Write"):
        result = _run_hook(_payload(repo, tool_name), state_dir=state_dir)
        assert result.returncode == 2, f"{tool_name}: {result.stderr}"
        assert "BLOCKED:" in result.stderr
        assert "resume" in result.stderr.lower()


def test_allows_read_tools_under_a_released_lease(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _create(repo, state_dir, target="pi")

    result = _run_hook(_payload(repo, "Read"), state_dir=state_dir)

    assert result.returncode == 0, result.stderr


def test_allows_the_bound_owner_session_and_blocks_other_sessions(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _create(repo, state_dir, target="claude")
    acquired = _runtime(
        "resume",
        checkpoint_id,
        "--as",
        "claude",
        "--receiver-session",
        "sess-1",
        cwd=repo,
        state_dir=state_dir,
    )
    assert acquired.returncode == 0, acquired.stderr

    bound = _run_hook(_payload(repo, "Bash", session_id="sess-1"), state_dir=state_dir)
    other = _run_hook(_payload(repo, "Bash", session_id="sess-2"), state_dir=state_dir)

    assert bound.returncode == 0, bound.stderr
    assert other.returncode == 2
    assert "BLOCKED:" in other.stderr


def test_blocks_when_the_other_harness_owns_the_lease(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    checkpoint_id = _create(repo, state_dir, target="pi", source="claude")
    acquired = _runtime(
        "resume",
        checkpoint_id,
        "--as",
        "pi",
        "--receiver-session",
        "pi-sess-1",
        cwd=repo,
        state_dir=state_dir,
    )
    assert acquired.returncode == 0, acquired.stderr

    result = _run_hook(_payload(repo, "Bash", session_id="claude-sess-1"), state_dir=state_dir)

    assert result.returncode == 2
    assert "BLOCKED:" in result.stderr
    assert "pi" in result.stderr


def test_fails_closed_on_a_malformed_lease_without_granting_mutation(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _create(repo, state_dir, target="pi")
    lease_path = next(state_dir.glob("workspaces/*/*/lease.json"))
    lease_path.write_text("not-json{")

    result = _run_hook(_payload(repo, "Bash"), state_dir=state_dir)

    assert result.returncode == 2
    assert "BLOCKED:" in result.stderr


def test_fails_open_when_the_runtime_is_unreachable(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    empty_root = tmp_path / "empty-plugin-root"
    empty_root.mkdir()

    result = _run_hook(_payload(repo, "Bash"), state_dir=tmp_path / "state", plugin_root=empty_root)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_no_secrets_in_blocking_output(tmp_path):
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    state_dir = tmp_path / "state"
    _create(repo, state_dir, target="pi")

    result = _run_hook(_payload(repo, "Bash"), state_dir=state_dir)

    for marker in ("authorization", "token", "password"):
        assert marker not in result.stderr.lower()
