"""
Regression tests for gh pr checks reliability in scripts/release.sh.

Bug A: The dual gh pr checks calls with || echo "0" collapse three distinct signals
       (rc=0 clean, rc=8 checks-failed-but-JSON-valid, transient auth/network) into
       a single "0 pending" value — masking failures and causing false green merges.

Bug B: GitHub's GraphQL mergeCommit.oid is eventually consistent after a squash merge.
       The original single-shot read can return null, making MERGE_SHA="" and triggering
       a false "tamper" abort — PR merged, version bumped, no tag pushed.
"""
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

RELEASE_SH = Path(__file__).parent.parent / "scripts" / "release.sh"


def _script_lines() -> list[str]:
    return RELEASE_SH.read_text().splitlines()


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


# ─── Bug A: guard-body snippet ───────────────────────────────────────────────
#
# Self-contained single-iteration extract of the CI-wait loop's check logic.
# Maps routing outcomes to distinct exit codes so tests can assert the branch:
#   0 = all green  (caller proceeds to merge)
#   1 = CI failed  (caller aborts with error)
#   2 = pending    (caller continues polling)
#   3 = transient  (caller sleeps + retries — rc was not 0 or 8)
#
_GUARD_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    set +e
    CHECKS_JSON=$(gh pr checks "42" --json state,conclusion 2>/dev/null)
    CHECKS_RC=$?
    set -e

    if [[ $CHECKS_RC -ne 0 && $CHECKS_RC -ne 8 ]]; then
      echo "transient: rc=${CHECKS_RC}" >&2
      exit 3
    fi

    PENDING=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.state == "PENDING" or .state == "IN_PROGRESS" or .state == "QUEUED" or .state == "WAITING")] | length')
    FAILED=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.conclusion == "FAILURE" or .conclusion == "CANCELLED" or .conclusion == "TIMED_OUT")] | length')

    if [[ "$PENDING" -eq 0 ]]; then
      if [[ "$FAILED" -gt 0 ]]; then
        echo "CI check(s) failed" >&2
        exit 1
      fi
      exit 0
    fi
    exit 2
""")

# ─── Bug B: poll-body snippet ─────────────────────────────────────────────────
#
# POLL_TIMEOUT injected via env so tests use a short window; sleep is stubbed.
# Matches the bounded-poll structure introduced in the fix.
#
_POLL_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    MERGE_SHA=""
    POLL_TIMEOUT=${POLL_TIMEOUT:-60}
    POLL_ELAPSED=0
    while [[ $POLL_ELAPSED -lt $POLL_TIMEOUT ]]; do
      MERGE_SHA=$(gh pr view "42" --json mergeCommit -q '.mergeCommit.oid' 2>/dev/null || true)
      [[ -n "$MERGE_SHA" ]] && break
      sleep 3
      POLL_ELAPSED=$((POLL_ELAPSED + 3))
    done

    if [[ -z "$MERGE_SHA" ]]; then
      echo "Error: GitHub did not return mergeCommit.oid for PR #42 within ${POLL_TIMEOUT}s." >&2
      echo "PR is merged; tagging skipped. Re-run this script — it is safe and idempotent." >&2
      exit 1
    fi

    printf '%s\\n' "$MERGE_SHA"
""")


# ─── Bug A: static tests ──────────────────────────────────────────────────────


class TestBugAStatic:
    """Static: the dual-call + || echo "0" fallback pattern must be gone."""

    def test_no_fallback_echo_zero(self):
        for line in _script_lines():
            if _is_comment(line):
                continue
            assert not re.search(r'gh pr checks.*\|\|.*echo.*"0"', line), (
                f"Forbidden fallback still present: {line.strip()!r}"
            )

    def test_gh_pr_checks_called_exactly_once(self):
        # Match lines where `gh pr checks` is part of a command substitution or
        # direct invocation — not a string literal in an echo/log statement.
        calls = [
            ln for ln in _script_lines()
            if re.search(r'\$\(gh pr checks\b|^\s*gh pr checks\b', ln)
            and not _is_comment(ln)
        ]
        assert len(calls) == 1, (
            f"Expected exactly 1 'gh pr checks' invocation, found {len(calls)}: {calls}"
        )


# ─── Bug A: dynamic tests ─────────────────────────────────────────────────────


class TestBugADynamic:
    """Dynamic: guard body correctly routes all four rc/JSON combinations."""

    def _run(self, stub_dir: Path) -> subprocess.CompletedProcess:
        env = {**_CLEAN_ENV, "PATH": f"{stub_dir}:{_CLEAN_ENV.get('PATH', '')}"}
        return subprocess.run(
            ["bash", "-c", _GUARD_SNIPPET], capture_output=True, text=True, env=env
        )

    def _make_gh_stub(self, stub_dir: Path, body: str) -> None:
        gh = stub_dir / "gh"
        gh.write_text(f"#!/bin/sh\n{body}\n")
        gh.chmod(0o755)

    def test_happy_path_clean(self, tmp_path):
        """rc=0, all SUCCESS → exit 0 (proceed to merge)."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"state":"COMPLETED","conclusion":"SUCCESS"}]\'; exit 0',
        )
        assert self._run(tmp_path).returncode == 0

    def test_rc0_pending_yields_pending_branch(self, tmp_path):
        """rc=0, IN_PROGRESS check → exit 2 (still polling)."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"state":"IN_PROGRESS","conclusion":null}]\'; exit 0',
        )
        assert self._run(tmp_path).returncode == 2

    def test_rc8_failed_checks_routed_to_failed_branch(self, tmp_path):
        """rc=8 (gh-documented 'at least one check failed') → exit 1, stderr."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"state":"COMPLETED","conclusion":"FAILURE"}]\'; exit 8',
        )
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "CI check(s) failed" in result.stderr

    def test_transient_then_recovers(self, tmp_path):
        """Call 1 rc=1 (transient) → exit 3; call 2 rc=0+SUCCESS → exit 0."""
        count_file = tmp_path / "count"
        count_file.write_text("0")
        self._make_gh_stub(tmp_path, textwrap.dedent(f"""\
            COUNT=$(cat {count_file} 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {count_file}
            if [ "$COUNT" -eq 1 ]; then exit 1; fi
            printf '[{{"state":"COMPLETED","conclusion":"SUCCESS"}}]'
            exit 0
        """))
        r1 = self._run(tmp_path)
        assert r1.returncode == 3, f"Expected 3 (transient) on call 1, got {r1.returncode}"
        assert "transient" in r1.stderr
        r2 = self._run(tmp_path)
        assert r2.returncode == 0, f"Expected 0 (recovered) on call 2, got {r2.returncode}"


# ─── Bug B: static tests ──────────────────────────────────────────────────────


class TestBugBStatic:
    """Static: mergeCommit retrieval is inside a bounded poll loop (while + sleep)."""

    def test_mergecommit_in_poll_loop(self):
        lines = _script_lines()

        # Find the POLL_ELAPSED while-loop boundaries (the first one after git pull)
        pull_idx = next(
            (i for i, ln in enumerate(lines) if "git pull --ff-only" in ln), None
        )
        assert pull_idx is not None, "git pull --ff-only not found in release.sh"

        while_idx = next(
            (i for i, ln in enumerate(lines)
             if i > pull_idx and re.search(r'while\s+\[\[.*POLL_ELAPSED', ln)),
            None,
        )
        assert while_idx is not None, "POLL_ELAPSED while loop not found after git pull"

        done_idx = next(
            (i for i, ln in enumerate(lines)
             if i > while_idx and ln.strip() == "done"),
            None,
        )
        assert done_idx is not None, "Closing 'done' for POLL_ELAPSED loop not found"

        # Assert the mergeCommit retrieval falls inside the loop boundaries
        for i, line in enumerate(lines):
            if "mergeCommit" in line and "gh pr view" in line and not _is_comment(line):
                assert while_idx < i < done_idx, (
                    f"mergeCommit query at line {i + 1} is outside the POLL_ELAPSED "
                    f"loop (while={while_idx + 1}, done={done_idx + 1})"
                )
                return
        pytest.fail("No non-comment 'gh pr view ... mergeCommit' line found in release.sh")


# ─── Bug B: dynamic tests ─────────────────────────────────────────────────────


class TestBugBDynamic:
    """Dynamic: bounded poll handles empty-then-populated and persistent-empty."""

    def _run_poll(self, stub_dir: Path, timeout: int = 9) -> subprocess.CompletedProcess:
        # timeout=9: 3 ticks × 3 s/tick — enough for call-3-succeeds tests, fast with stubbed sleep
        sleep_stub = stub_dir / "sleep"
        sleep_stub.write_text("#!/bin/sh\nexit 0\n")
        sleep_stub.chmod(0o755)
        env = {
            **_CLEAN_ENV,
            "PATH": f"{stub_dir}:{_CLEAN_ENV.get('PATH', '')}",
            "POLL_TIMEOUT": str(timeout),
        }
        return subprocess.run(
            ["bash", "-c", _POLL_SNIPPET], capture_output=True, text=True, env=env
        )

    def test_mergecommit_empty_then_populated(self, tmp_path):
        """gh returns empty on calls 1–2, 'abc123' on call 3 → exit 0, SHA printed."""
        count_file = tmp_path / "count"
        count_file.write_text("0")
        gh = tmp_path / "gh"
        gh.write_text(textwrap.dedent(f"""\
            #!/bin/sh
            COUNT=$(cat {count_file} 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {count_file}
            if [ "$COUNT" -ge 3 ]; then printf 'abc123'; fi
            exit 0
        """))
        gh.chmod(0o755)
        result = self._run_poll(tmp_path, timeout=9)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert result.stdout.strip() == "abc123"

    def test_mergecommit_persists_empty_60s(self, tmp_path):
        """gh always returns empty → timeout → exit 1, idempotent-rerun message."""
        gh = tmp_path / "gh"
        gh.write_text("#!/bin/sh\nexit 0\n")
        gh.chmod(0o755)
        result = self._run_poll(tmp_path, timeout=9)
        assert result.returncode == 1
        assert "Re-run this script" in result.stderr
