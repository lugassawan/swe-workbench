from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV, _clean_environment

BIN = Path(__file__).parent.parent / "bin"
CLAUDE_ADAPTER = BIN / "swe-workbench-session-scratch-adapter-claude"
PI_ADAPTER = BIN / "swe-workbench-session-scratch-adapter-pi"
CLAUDE_REAPER = BIN / "swe-workbench-reap-session-scratch"
CLAUDE_ROOT = Path(f"/tmp/claude-{os.getuid()}")
CLAUDE_SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PROJECT = "pytest-session-scratch-adapter"
SECOND_PROJECT = "pytest-session-scratch-adapter-second"
LINE_BREAKING_PROJECT = "pytest-session-scratch-adapter\nline-break"


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_id: str
    root: Path
    candidates: tuple[Path, ...]


def run_adapter(
    adapter: Path, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(_CLEAN_ENV)
    env.update(env_overrides or {})
    return subprocess.run(
        [str(adapter)],
        capture_output=True,
        text=True,
        cwd=adapter.parent,
        env=env,
    )


def parse_descriptor(stdout: str) -> AdapterDescriptor:
    records = stdout.splitlines()
    assert records[0] == "SWB_SESSION_SCRATCH_V1"
    candidate_count = int(records[3])
    assert len(records) == candidate_count + 4
    return AdapterDescriptor(
        adapter_id=records[1],
        root=Path(records[2]),
        candidates=tuple(Path(record) for record in records[4:]),
    )


def make_claude_scratchpad(*, project: str = PROJECT, leaf: str = "scratchpad") -> Path:
    target = CLAUDE_ROOT / project / CLAUDE_SESSION_ID / leaf
    target.mkdir(parents=True)
    return target


@pytest.fixture(autouse=True)
def clean_claude_scratchpad_projects() -> None:
    for project in (PROJECT, SECOND_PROJECT, LINE_BREAKING_PROJECT):
        shutil.rmtree(CLAUDE_ROOT / project, ignore_errors=True)
    yield
    for project in (PROJECT, SECOND_PROJECT, LINE_BREAKING_PROJECT):
        shutil.rmtree(CLAUDE_ROOT / project, ignore_errors=True)


def test_claude_adapter_is_inactive_without_session_id() -> None:
    result = run_adapter(CLAUDE_ADAPTER)

    assert result.returncode == 3
    assert result.stdout == ""


def test_pi_adapter_is_inactive_without_session_id() -> None:
    result = run_adapter(PI_ADAPTER)

    assert result.returncode == 3
    assert result.stdout == ""


def test_pi_adapter_is_active_but_unsupported() -> None:
    result = run_adapter(PI_ADAPTER, {"PI_SESSION_ID": "0198f6b8-example"})

    assert result.returncode == 4
    assert result.stdout == ""
    assert "no sanctioned session scratch path" in result.stderr


@pytest.mark.parametrize("session_id", ["session\ridentifier", "session\nidentifier"])
def test_pi_adapter_rejects_line_breaking_session_id(session_id: str) -> None:
    result = run_adapter(PI_ADAPTER, {"PI_SESSION_ID": session_id})

    assert result.returncode == 4
    assert result.stdout == ""
    assert "PI_SESSION_ID contains control characters" in result.stderr


def test_pi_adapter_rejects_leading_control_byte_before_large_payload(
    tmp_path: Path,
) -> None:
    grep = tmp_path / "grep"
    grep.write_text("#!/usr/bin/env bash\nIFS= read -r -n 1 _\n")
    grep.chmod(0o755)
    session_id = "\x1f" + "payload" * 16_384

    result = run_adapter(
        PI_ADAPTER,
        {
            "PATH": f"{tmp_path}:{_CLEAN_ENV['PATH']}",
            "PI_SESSION_ID": session_id,
        },
    )

    assert result.returncode == 4
    assert result.stdout == ""
    assert "PI_SESSION_ID contains control characters" in result.stderr


def test_pi_session_file_cannot_authorize_scratch(tmp_path: Path) -> None:
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}\n")
    scratch = tmp_path / "scratchpad"
    scratch.mkdir()
    (scratch / "keep.txt").write_text("x")

    result = run_adapter(
        PI_ADAPTER,
        {"PI_SESSION_ID": "0198f6b8-example", "PI_SESSION_FILE": str(session_file)},
    )

    assert result.returncode == 4
    assert result.stdout == ""
    assert (scratch / "keep.txt").exists()


def test_clean_environment_strips_native_session_markers() -> None:
    clean_environment = _clean_environment(
        {
            "CLAUDE_CODE_SESSION_ID": "claude-session",
            "PI_SESSION_ID": "pi-session",
            "PRESERVED": "value",
        }
    )

    assert clean_environment == {"PRESERVED": "value"}


@pytest.mark.parametrize(
    "session_id",
    ["not-a-session-id", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee\nextra"],
)
def test_claude_adapter_rejects_malformed_session_id(session_id: str) -> None:
    result = run_adapter(CLAUDE_ADAPTER, {"CLAUDE_CODE_SESSION_ID": session_id})

    assert result.returncode == 4
    assert result.stdout == ""


def test_claude_adapter_rejects_zero_scratchpad_candidates() -> None:
    result = run_adapter(CLAUDE_ADAPTER, {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION_ID})

    assert result.returncode == 4
    assert result.stdout == ""


def test_claude_adapter_rejects_multiple_project_candidates() -> None:
    make_claude_scratchpad()
    make_claude_scratchpad(project=SECOND_PROJECT)

    result = run_adapter(CLAUDE_ADAPTER, {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION_ID})

    assert result.returncode == 4
    assert result.stdout == ""


def test_claude_adapter_rejects_line_breaking_relative_candidate() -> None:
    make_claude_scratchpad(project=LINE_BREAKING_PROJECT)

    result = run_adapter(CLAUDE_ADAPTER, {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION_ID})

    assert result.returncode == 4
    assert result.stdout == ""


def test_claude_adapter_rejects_differently_named_leaf() -> None:
    make_claude_scratchpad(leaf="not-scratchpad")

    result = run_adapter(CLAUDE_ADAPTER, {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION_ID})

    assert result.returncode == 4
    assert result.stdout == ""


def test_claude_adapter_emits_relative_native_candidate() -> None:
    target = make_claude_scratchpad()

    result = run_adapter(CLAUDE_ADAPTER, {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION_ID})

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "SWB_SESSION_SCRATCH_V1",
        "claude",
        str(CLAUDE_ROOT),
        "1",
        f"{PROJECT}/{CLAUDE_SESSION_ID}/scratchpad",
    ]
    assert parse_descriptor(result.stdout) == AdapterDescriptor(
        adapter_id="claude",
        root=CLAUDE_ROOT,
        candidates=(Path(f"{PROJECT}/{CLAUDE_SESSION_ID}/scratchpad"),),
    )
    assert target.exists()


def test_reaper_clears_current_claude_scratchpad_contents() -> None:
    target = make_claude_scratchpad()
    (target / "leftover.txt").write_text("x")

    result = run_adapter(CLAUDE_REAPER, {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION_ID})

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["SWEPT_SESSION_FILES=1"]
    assert target.is_dir()
    assert list(target.iterdir()) == []
