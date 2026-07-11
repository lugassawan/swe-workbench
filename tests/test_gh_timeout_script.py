"""Tests for runtime/gh-timeout.sh — per-call timeout wrapper for `gh` (issue #504).

Each test invokes the script as a subprocess with fake `timeout`/`gtimeout`/`gh`
stubs prepended to a PATH that is tightly scoped per test, mirroring the
test_doctor_script.py / test_reply_and_resolve_script.py stub conventions.

Stubs record their full argv NUL-delimited to a log file so assertions can
recover exact argument boundaries even when an argument (e.g. a GraphQL query)
contains spaces or newlines.

Behavioral paths under test:
  - Applies the deadline: `timeout -k 5 <secs> gh <args...>`, args forwarded verbatim
  - GH_TIMEOUT_SECS override changes the deadline
  - Invalid GH_TIMEOUT_SECS falls back to the 60s default
  - No timeout/gtimeout on PATH: degrades to calling `gh` directly
  - gtimeout is used when `timeout` is absent but `gtimeout` is present (macOS/coreutils)
  - A 124 exit from the timeout binary propagates and prints a stderr diagnostic
  - Multi-arg calls (e.g. `gh api graphql -F ... -f query=...`) forward every arg intact
"""

import subprocess
from pathlib import Path
from shutil import which

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "runtime" / "gh-timeout.sh"
ROOT = Path(__file__).parent.parent

BASH_BIN = which("bash") or "/bin/bash"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _recording_stub(log: Path, *, exit_code: int = 0) -> str:
    """Stub body that NUL-delimits its full argv to `log`, then exits `exit_code`."""
    return f"#!/bin/sh\nprintf '%s\\0' \"$@\" > '{log}'\nexit {exit_code}\n"


def _fixed_exit_stub(exit_code: int) -> str:
    """Stub body that ignores its args and exits `exit_code` unconditionally."""
    return f"#!/bin/sh\nexit {exit_code}\n"


def _read_argv(log: Path) -> list[str]:
    """Decode a NUL-delimited argv log back into a list of strings."""
    if not log.exists():
        return []
    raw = log.read_bytes()
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    return [p.decode() for p in parts]


def _run(args: list[str], *, bin_dir: Path, extra_env: dict | None = None):
    env = dict(_CLEAN_ENV)
    env["PATH"] = str(bin_dir)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [BASH_BIN, str(SCRIPT), *args],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )


# ── Existence ────────────────────────────────────────────────────────────────

def test_script_exists_and_executable():
    """runtime/gh-timeout.sh must exist and be executable."""
    import os
    assert SCRIPT.exists(), "runtime/gh-timeout.sh must exist"
    assert os.access(SCRIPT, os.X_OK), "runtime/gh-timeout.sh must be executable (chmod +x)"


# ── Applies the deadline (default 60s), forwards args verbatim ────────────────

def test_applies_default_deadline_and_forwards_args(tmp_path):
    """With a `timeout` stub present, deadline defaults to 60s and gh args are forwarded verbatim."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "timeout.log"
    _write_stub(bin_dir / "timeout", _recording_stub(log))
    result = _run(["pr", "view", "42", "--json", "state"], bin_dir=bin_dir)
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    argv = _read_argv(log)
    assert argv[:3] == ["-k", "5", "60"], f"expected '-k 5 60' prefix, got: {argv}"
    assert argv[3:] == ["gh", "pr", "view", "42", "--json", "state"], (
        f"expected forwarded gh call verbatim, got: {argv}"
    )


# ── GH_TIMEOUT_SECS override ───────────────────────────────────────────────────

def test_env_override_changes_deadline(tmp_path):
    """GH_TIMEOUT_SECS=15 → the timeout binary is invoked with a 15s deadline."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "timeout.log"
    _write_stub(bin_dir / "timeout", _recording_stub(log))
    result = _run(["api", "rate_limit"], bin_dir=bin_dir, extra_env={"GH_TIMEOUT_SECS": "15"})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    argv = _read_argv(log)
    assert argv[:3] == ["-k", "5", "15"], f"expected '-k 5 15' prefix, got: {argv}"


# ── Invalid GH_TIMEOUT_SECS falls back to 60 ───────────────────────────────────

def test_invalid_override_falls_back_to_60(tmp_path):
    """A malformed GH_TIMEOUT_SECS (non-numeric) falls back to the 60s default without failing hard."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "timeout.log"
    _write_stub(bin_dir / "timeout", _recording_stub(log))
    result = _run(["api", "rate_limit"], bin_dir=bin_dir, extra_env={"GH_TIMEOUT_SECS": "abc"})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    argv = _read_argv(log)
    assert argv[:3] == ["-k", "5", "60"], f"expected fallback to 60s, got: {argv}"


def test_zero_override_falls_back_to_60(tmp_path):
    """GH_TIMEOUT_SECS=0 must NOT be forwarded as-is: GNU timeout/gtimeout treat a 0 duration as
    'disable the timer', so passing 0 through would silently re-introduce an unbounded gh call —
    the exact hang this wrapper exists to prevent. It must fall back to the 60s default instead."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "timeout.log"
    _write_stub(bin_dir / "timeout", _recording_stub(log))
    result = _run(["api", "rate_limit"], bin_dir=bin_dir, extra_env={"GH_TIMEOUT_SECS": "0"})
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    argv = _read_argv(log)
    assert argv[:3] == ["-k", "5", "60"], f"expected fallback to 60s (not 0/unbounded), got: {argv}"


# ── Degrades gracefully when no timeout binary is present ─────────────────────

def test_degrades_to_plain_gh_when_no_timeout_binary(tmp_path):
    """Neither timeout nor gtimeout on PATH → gh is called directly, exit 0."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    _write_stub(bin_dir / "gh", _recording_stub(log))
    result = _run(["pr", "view", "42"], bin_dir=bin_dir)
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert _read_argv(log) == ["pr", "view", "42"], (
        "gh must be called directly with args forwarded verbatim when no timeout binary exists"
    )


def test_uses_gtimeout_when_timeout_absent(tmp_path):
    """`gtimeout` (macOS/coreutils) is used when `timeout` is absent but `gtimeout` is present."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gtimeout.log"
    _write_stub(bin_dir / "gtimeout", _recording_stub(log))
    result = _run(["pr", "view", "42"], bin_dir=bin_dir)
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    argv = _read_argv(log)
    assert argv[:3] == ["-k", "5", "60"], f"expected '-k 5 60' prefix, got: {argv}"
    assert argv[3:] == ["gh", "pr", "view", "42"], f"expected forwarded gh call, got: {argv}"


# ── Timeout exit (124) propagates with a stderr diagnostic ────────────────────

def test_timeout_exit_propagates_and_prints_diagnostic(tmp_path):
    """A 124 exit from the timeout binary propagates as-is, with a clear stderr diagnostic."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "timeout", _fixed_exit_stub(124))
    result = _run(["pr", "view", "42"], bin_dir=bin_dir)
    assert result.returncode == 124, f"expected exit 124, got {result.returncode}: {result.stderr!r}"
    assert "gh-timeout" in result.stderr, f"expected a gh-timeout diagnostic on stderr: {result.stderr!r}"
    assert "gh pr view 42" in result.stderr, (
        f"diagnostic must name the timed-out gh call: {result.stderr!r}"
    )
    assert "60s deadline" in result.stderr, f"diagnostic must name the deadline: {result.stderr!r}"
    assert "GH_TIMEOUT_SECS" in result.stderr, (
        f"diagnostic must name the override env var: {result.stderr!r}"
    )


def test_non_timeout_failure_propagates_without_diagnostic(tmp_path):
    """A non-124 gh failure (e.g. a real error) propagates its exit code without the timeout diagnostic."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "timeout", _fixed_exit_stub(1))
    result = _run(["pr", "view", "999"], bin_dir=bin_dir)
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}"
    assert "gh-timeout" not in result.stderr, (
        f"non-timeout failures must not print the timeout diagnostic: {result.stderr!r}"
    )


# ── Multi-arg forwarding (guards the reply-and-resolve GraphQL call) ──────────

def test_multi_arg_graphql_call_forwarded_intact(tmp_path):
    """A `gh api graphql -F ... -f query=...` style call forwards every argv element intact."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "timeout.log"
    _write_stub(bin_dir / "timeout", _recording_stub(log))
    query = (
        "mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) "
        "{ thread { id isResolved } } }"
    )
    args = ["api", "graphql", "-F", "threadId=THREAD_abc123", "-f", f"query={query}"]
    result = _run(args, bin_dir=bin_dir)
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    argv = _read_argv(log)
    assert argv[:3] == ["-k", "5", "60"]
    assert argv[3:] == ["gh", *args], f"expected every argv element forwarded intact, got: {argv}"
