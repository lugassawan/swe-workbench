"""Tests for runtime/fetch-pr.sh — PR metadata fetcher with error handling.

Each test invokes the script as a subprocess with a fake `gh` stub prepended
to PATH, mirroring the test_clean_ephemeral.py / test_clean_state_files.py pattern.

Behavioral paths under test:
  - Happy path: gh exits 0 and writes JSON → exit 0, file present and non-empty
  - gh failure: gh exits non-zero → exit 1, "not found or not accessible" on stderr
  - Empty JSON: gh exits 0 but writes nothing → exit 1, "empty JSON" on stderr
  - Missing args: no positional args → exit non-zero (:? bash guard)
"""

import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "runtime" / "fetch-pr.sh"
ROOT = Path(__file__).parent.parent


def _make_gh_stub(stub_dir: Path, *, exit_code: int, output: str) -> None:
    """Write a fake gh binary that emits `output` to stdout and exits with `exit_code`."""
    stub_dir.mkdir(exist_ok=True)
    output_file = stub_dir / "_gh_output"
    output_file.write_text(output)
    stub = stub_dir / "gh"
    stub.write_text(f"#!/bin/sh\ncat '{output_file}'\nexit {exit_code}\n")
    stub.chmod(0o755)


def _run(pr: str, out_path: Path, fields: str, *, stub_dir: Path):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(SCRIPT), pr, str(out_path), fields],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )


# ── Happy path ────────────────────────────────────────────────────────────────

def test_happy_path_exits_zero_and_writes_file(tmp_path):
    """gh exits 0 and outputs JSON → script exits 0 and the output file is non-empty."""
    stub_dir = tmp_path / "stubs"
    out = tmp_path / "subdir" / "pr.json"
    _make_gh_stub(stub_dir, exit_code=0, output='{"number":1,"title":"Test PR"}')
    result = _run("1", out, "number,title", stub_dir=stub_dir)
    assert result.returncode == 0, f"Expected exit 0\nstderr: {result.stderr!r}"
    assert out.exists(), "Output file must be created on success"
    assert '"number"' in out.read_text(), "Output file must contain the JSON"


def test_happy_path_creates_parent_dir(tmp_path):
    """The script creates the parent directory of the output path if it does not exist."""
    stub_dir = tmp_path / "stubs"
    nested_out = tmp_path / "a" / "b" / "c" / "pr.json"
    _make_gh_stub(stub_dir, exit_code=0, output='{"number":2}')
    result = _run("2", nested_out, "number", stub_dir=stub_dir)
    assert result.returncode == 0
    assert nested_out.exists()


# ── gh failure ────────────────────────────────────────────────────────────────

def test_gh_failure_exits_nonzero_with_stderr(tmp_path):
    """gh exits non-zero → script exits 1 and emits 'not found or not accessible' on stderr."""
    stub_dir = tmp_path / "stubs"
    out = tmp_path / "pr.json"
    _make_gh_stub(stub_dir, exit_code=1, output="")
    result = _run("999", out, "number", stub_dir=stub_dir)
    assert result.returncode != 0, "Expected non-zero exit when gh fails"
    assert "not found or not accessible" in result.stderr, (
        f"Expected 'not found or not accessible' on stderr; got: {result.stderr!r}"
    )


def test_gh_failure_error_goes_to_stderr_not_stdout(tmp_path):
    """Error message must be on stderr so callers capturing stdout for JSON don't swallow it."""
    stub_dir = tmp_path / "stubs"
    out = tmp_path / "pr.json"
    _make_gh_stub(stub_dir, exit_code=1, output="")
    result = _run("999", out, "number", stub_dir=stub_dir)
    assert result.returncode != 0
    assert "not found" not in result.stdout, (
        "Error message must not appear on stdout — callers capture stdout for JSON"
    )


# ── Empty JSON ────────────────────────────────────────────────────────────────

def test_empty_json_exits_nonzero_with_stderr(tmp_path):
    """gh exits 0 but writes empty output → script exits 1 with 'empty JSON' on stderr."""
    stub_dir = tmp_path / "stubs"
    out = tmp_path / "pr.json"
    _make_gh_stub(stub_dir, exit_code=0, output="")
    result = _run("42", out, "number", stub_dir=stub_dir)
    assert result.returncode != 0, "Expected non-zero exit for empty JSON output"
    assert "empty JSON" in result.stderr, (
        f"Expected 'empty JSON' on stderr; got: {result.stderr!r}"
    )


# ── Missing args ──────────────────────────────────────────────────────────────

def test_missing_all_args_exits_nonzero(tmp_path):
    """Invoking with no arguments exits non-zero (bash :? positional guard)."""
    env = dict(_CLEAN_ENV)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )
    assert result.returncode != 0, "Expected non-zero exit when all args are missing"
