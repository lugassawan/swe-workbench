"""Tests for runtime/sync-pr-metadata.sh — PR metadata drift sync helper.

Each test invokes the script with a recording `gh` stub. The stub logs each
invocation to a temp file so tests can assert which gh sub-commands were called
and how many times, without needing a real GitHub token.

Behavioral paths under test:
  - title + body: one gh pr edit call carrying --title and --body-file
  - empty title: only --body-file (no --title flag)
  - missing body file: exit 1, gh never called
  - no title and no body: exit 1 (nothing to update)
"""

import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "runtime" / "sync-pr-metadata.sh"
ROOT = Path(__file__).parent.parent


def _make_recording_gh_stub(stub_dir: Path, log_file: Path) -> None:
    """gh stub that appends all positional args as one line per invocation."""
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "gh"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{log_file}'\nexit 0\n")
    stub.chmod(0o755)


def _run(pr, new_title, body_file, *, stub_dir: Path):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(SCRIPT), pr, new_title, body_file],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )


def _gh_calls(log_file: Path) -> list[str]:
    if not log_file.exists():
        return []
    return [ln for ln in log_file.read_text().splitlines() if ln.strip()]


# ── title + body ──────────────────────────────────────────────────────────────

def test_title_and_body_calls_gh_pr_edit(tmp_path):
    """title + body → one 'gh pr edit' call carrying --title and --body-file."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    body = tmp_path / "body.md"
    body.write_text("## Summary\nFix stuff.")
    result = _run("99", "feat: new title", str(body), stub_dir=stub_dir)
    assert result.returncode == 0, f"Expected exit 0\nstderr: {result.stderr!r}"
    calls = _gh_calls(log)
    assert len(calls) == 1, f"Expected 1 gh call, got {len(calls)}: {calls}"
    assert "--title" in calls[0], f"Call must include --title: {calls[0]!r}"
    assert "--body-file" in calls[0], f"Call must include --body-file: {calls[0]!r}"


# ── body-only (empty title) ───────────────────────────────────────────────────

def test_body_only_omits_title_flag(tmp_path):
    """Empty title → gh pr edit with only --body-file (no --title flag)."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    body = tmp_path / "body.md"
    body.write_text("## Summary\nUpdated summary.")
    result = _run("99", "", str(body), stub_dir=stub_dir)
    assert result.returncode == 0, f"Expected exit 0\nstderr: {result.stderr!r}"
    calls = _gh_calls(log)
    assert len(calls) == 1, f"Expected 1 gh call, got {len(calls)}: {calls}"
    assert "--body-file" in calls[0], f"Call must include --body-file: {calls[0]!r}"
    assert "--title" not in calls[0], (
        f"Call must NOT include --title when title is empty: {calls[0]!r}"
    )


# ── missing body file ─────────────────────────────────────────────────────────

def test_missing_body_file_exits_nonzero(tmp_path):
    """Body file path given but file does not exist → exit 1, gh never called."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run("99", "", str(tmp_path / "nonexistent.md"), stub_dir=stub_dir)
    assert result.returncode != 0, (
        f"Expected non-zero when body file does not exist\nstdout: {result.stdout!r}"
    )
    assert _gh_calls(log) == [], "gh must NOT be called when body file is missing"


# ── title-only (empty body file) ─────────────────────────────────────────────

def test_title_only_omits_body_flag(tmp_path):
    """Non-empty title, empty body → gh pr edit with only --title (no --body-file flag)."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run("99", "feat: updated title", "", stub_dir=stub_dir)
    assert result.returncode == 0, f"Expected exit 0\nstderr: {result.stderr!r}"
    calls = _gh_calls(log)
    assert len(calls) == 1, f"Expected 1 gh call, got {len(calls)}: {calls}"
    assert "--title" in calls[0], f"Call must include --title: {calls[0]!r}"
    assert "--body-file" not in calls[0], (
        f"Call must NOT include --body-file when body is empty: {calls[0]!r}"
    )


# ── no args (nothing to update) ───────────────────────────────────────────────

def test_no_title_no_body_exits_nonzero(tmp_path):
    """Neither title nor body file → exit 1 (nothing to update)."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run("99", "", "", stub_dir=stub_dir)
    assert result.returncode != 0, (
        f"Expected non-zero when both title and body are empty\nstdout: {result.stdout!r}"
    )
    assert _gh_calls(log) == [], "gh must NOT be called when both title and body are empty"


# ── PR number required guard ({1:?}) ─────────────────────────────────────────

def test_pr_number_required_guard(tmp_path):
    """Omitting PR number entirely → exit non-zero with error on stderr."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )
    assert result.returncode != 0, "Expected non-zero when PR number is omitted"
    assert "PR number required" in result.stderr or result.stderr, (
        f"Expected error on stderr when PR is omitted; got: {result.stderr!r}"
    )
    assert _gh_calls(log) == [], "gh must NOT be called when PR is omitted"
