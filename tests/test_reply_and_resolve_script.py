"""Tests for runtime/reply-and-resolve.sh — PR thread reply + resolve dispatcher.

Each test invokes the script with a recording `gh` stub. The stub logs each
invocation to a temp file so tests can assert which gh sub-commands were called
and how many times, without needing a real GitHub token.

Behavioral paths under test:
  - DEFERRED (both REPLY_BODY and THREAD_ID empty): fast-exit 0, gh never called
  - ADDRESSED (both set): two gh calls — REST reply then GraphQL resolve
  - CLARIFIED (REPLY_BODY set, THREAD_ID empty): one gh call — REST reply only
  - Missing COMMENT_DATABASEID when REPLY_BODY set: exit 1, error on stderr, gh not called
"""

import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "runtime" / "reply-and-resolve.sh"
ROOT = Path(__file__).parent.parent


def _make_recording_gh_stub(stub_dir: Path, log_file: Path) -> None:
    """gh stub that appends one line per invocation to log_file and exits 0."""
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "gh"
    # Record "$1 $2" only: "api <url>" or "api graphql". The GraphQL query arg
    # spans multiple lines so recording $@ would produce extra log lines.
    stub.write_text(f'#!/bin/sh\nprintf \'%s %s\\n\' "$1" "$2" >> \'{log_file}\'\nexit 0\n')
    stub.chmod(0o755)


def _run(owner, repo, pr, comment_id, thread_id, reply_body, *, stub_dir: Path):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(SCRIPT), owner, repo, pr, comment_id, thread_id, reply_body],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )


def _gh_calls(log_file: Path) -> list[str]:
    """Return recorded gh invocation lines (empty list if log was never written)."""
    if not log_file.exists():
        return []
    return [ln for ln in log_file.read_text().splitlines() if ln.strip()]


# ── DEFERRED fast-exit ────────────────────────────────────────────────────────

def test_deferred_exits_zero_without_calling_gh(tmp_path):
    """DEFERRED (both args empty) exits 0 immediately; gh is never invoked."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run("owner", "repo", "123", "456", "", "", stub_dir=stub_dir)
    assert result.returncode == 0, (
        f"Expected exit 0 for DEFERRED\nstderr: {result.stderr!r}"
    )
    assert _gh_calls(log) == [], (
        "gh must NOT be called for DEFERRED (empty REPLY_BODY + empty THREAD_ID)"
    )


def test_deferred_skips_owner_repo_pr_validation(tmp_path):
    """DEFERRED fast-exit fires before the :? guards, so empty OWNER/REPO/PR is tolerated."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    # Pass empty strings for OWNER, REPO, PR — this would normally fail the :? guards.
    result = _run("", "", "", "", "", "", stub_dir=stub_dir)
    assert result.returncode == 0, (
        "DEFERRED must exit 0 even when OWNER/REPO/PR are empty — fast-exit fires first"
    )
    assert _gh_calls(log) == []


# ── ADDRESSED (reply + resolve) ───────────────────────────────────────────────

def test_addressed_calls_reply_then_resolve(tmp_path):
    """ADDRESSED path invokes gh twice: REST reply call first, then GraphQL resolve."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run(
        "owner", "repo", "123", "456", "THREAD_abc", "Addressed in abc123: fix typo.",
        stub_dir=stub_dir,
    )
    assert result.returncode == 0, f"Expected exit 0\nstderr: {result.stderr!r}"
    calls = _gh_calls(log)
    assert len(calls) == 2, f"Expected 2 gh calls for ADDRESSED, got {len(calls)}: {calls}"
    assert "comments/456/replies" in calls[0], (
        f"First call must be the REST reply; got: {calls[0]!r}"
    )
    assert "graphql" in calls[1], (
        f"Second call must be the GraphQL resolve; got: {calls[1]!r}"
    )


# ── CLARIFIED (reply only) ────────────────────────────────────────────────────

def test_clarified_calls_reply_only(tmp_path):
    """CLARIFIED path (REPLY_BODY set, THREAD_ID empty) calls gh once — REST reply only."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run(
        "owner", "repo", "123", "456", "", "Thanks, will address later.",
        stub_dir=stub_dir,
    )
    assert result.returncode == 0, f"Expected exit 0\nstderr: {result.stderr!r}"
    calls = _gh_calls(log)
    assert len(calls) == 1, f"Expected 1 gh call for CLARIFIED, got {len(calls)}: {calls}"
    assert "comments/456/replies" in calls[0], (
        f"CLARIFIED must make only the REST reply call; got: {calls[0]!r}"
    )


def test_clarified_does_not_call_graphql(tmp_path):
    """CLARIFIED must not trigger the GraphQL resolveReviewThread mutation."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    _run("owner", "repo", "123", "456", "", "Noted.", stub_dir=stub_dir)
    calls = _gh_calls(log)
    assert all("graphql" not in c for c in calls), (
        f"CLARIFIED must not call graphql; calls: {calls}"
    )


# ── Missing COMMENT_DATABASEID ────────────────────────────────────────────────

def test_reply_without_comment_id_exits_nonzero(tmp_path):
    """REPLY_BODY set but COMMENT_DATABASEID empty → exit 1, error on stderr, gh not called."""
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "gh.log"
    _make_recording_gh_stub(stub_dir, log)
    result = _run("owner", "repo", "123", "", "", "A reply without an ID.", stub_dir=stub_dir)
    assert result.returncode != 0, (
        "Expected non-zero when REPLY_BODY is set but COMMENT_DATABASEID is empty"
    )
    assert "COMMENT_DATABASEID" in result.stderr, (
        f"Expected COMMENT_DATABASEID error on stderr; got: {result.stderr!r}"
    )
    assert _gh_calls(log) == [], "gh must NOT be called when COMMENT_DATABASEID is missing"
