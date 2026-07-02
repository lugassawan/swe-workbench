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
    TOTAL=0; PENDING=0; FAILED=0
    set +e
    CHECKS_JSON=$(gh pr checks "42" --json bucket 2>/dev/null)
    CHECKS_RC=$?
    set -e

    if [[ $CHECKS_RC -ne 0 && $CHECKS_RC -ne 8 ]]; then
      echo "transient: rc=${CHECKS_RC}" >&2
      exit 3
    fi

    if [[ $CHECKS_RC -eq 8 && -z "$CHECKS_JSON" ]]; then
      echo "transient: rc=8 no output" >&2
      exit 3
    fi

    TOTAL=$(printf '%s' "${CHECKS_JSON:-[]}" | jq 'length')
    PENDING=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.bucket == "pending")] | length')
    FAILED=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length')

    if [[ "$TOTAL" -eq 0 ]]; then
      exit 2
    elif [[ "$PENDING" -eq 0 ]]; then
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
            ln
            for ln in _script_lines()
            if re.search(r"\$\(gh pr checks\b|^\s*gh pr checks\b", ln)
            and not _is_comment(ln)
        ]
        assert len(calls) == 1, (
            f"Expected exactly 1 'gh pr checks' invocation, found {len(calls)}: {calls}"
        )

    def test_gh_pr_checks_json_fields_are_gh_recognised(self):
        """Every --json field passed to 'gh pr checks' must be in gh's documented whitelist.

        gh pr checks --json only accepts: bucket, completedAt, description, event,
        link, name, startedAt, state, workflow.  Passing an unrecognised field (e.g.
        'conclusion', which belongs to 'gh pr view --json statusCheckRollup') causes
        gh to exit rc=1, which the retry wrapper then launders as a transient error,
        looping until the 20-minute timeout.
        """
        _GH_PR_CHECKS_JSON_WHITELIST = {
            "bucket",
            "completedAt",
            "description",
            "event",
            "link",
            "name",
            "startedAt",
            "state",
            "workflow",
        }
        matched = False
        for line in _script_lines():
            if _is_comment(line):
                continue
            m = re.search(r'gh pr checks\b.*?--json\s+([^\s"\']+)', line)
            if not m:
                continue
            matched = True
            for field in m.group(1).split(","):
                field = field.strip()
                assert field in _GH_PR_CHECKS_JSON_WHITELIST, (
                    f"Invalid --json field {field!r} in 'gh pr checks' call.\n"
                    f"  Line: {line.strip()!r}\n"
                    f"  gh pr checks only accepts: {sorted(_GH_PR_CHECKS_JSON_WHITELIST)}"
                )
        assert matched, (
            "No 'gh pr checks --json <fields>' invocation found in release.sh; "
            "test_gh_pr_checks_called_exactly_once confirms a call exists — "
            "this regex must also match it (check for line-continuation refactors)"
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
        """rc=0, all pass buckets → exit 0 (proceed to merge)."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"bucket":"pass"}]\'; exit 0',
        )
        assert self._run(tmp_path).returncode == 0

    def test_rc0_pending_yields_pending_branch(self, tmp_path):
        """rc=0, pending bucket → exit 2 (still polling)."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"bucket":"pending"}]\'; exit 0',
        )
        assert self._run(tmp_path).returncode == 2

    def test_rc8_failed_checks_routed_to_failed_branch(self, tmp_path):
        """rc=8 (gh-documented 'at least one check failed') + fail bucket → exit 1, stderr."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"bucket":"fail"}]\'; exit 8',
        )
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "CI check(s) failed" in result.stderr

    def test_transient_then_recovers(self, tmp_path):
        """Call 1 rc=1 (transient) → exit 3; call 2 rc=0+pass bucket → exit 0."""
        count_file = tmp_path / "count"
        count_file.write_text("0")
        self._make_gh_stub(
            tmp_path,
            textwrap.dedent(f"""\
            COUNT=$(cat {count_file} 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {count_file}
            if [ "$COUNT" -eq 1 ]; then exit 1; fi
            printf '[{{"bucket":"pass"}}]'
            exit 0
        """),
        )
        r1 = self._run(tmp_path)
        assert r1.returncode == 3, (
            f"Expected 3 (transient) on call 1, got {r1.returncode}"
        )
        assert "transient" in r1.stderr
        r2 = self._run(tmp_path)
        assert r2.returncode == 0, (
            f"Expected 0 (recovered) on call 2, got {r2.returncode}"
        )

    def test_empty_checks_array_treated_as_pending(self, tmp_path):
        """rc=0, empty array [] → TOTAL=0 → exit 2 (still polling, not a green merge)."""
        self._make_gh_stub(tmp_path, 'printf "[]"; exit 0')
        assert self._run(tmp_path).returncode == 2

    def test_rc8_empty_output_treated_as_transient(self, tmp_path):
        """rc=8 with no stdout → treated as transient (exit 3), not silent-pending."""
        self._make_gh_stub(tmp_path, "exit 8")
        result = self._run(tmp_path)
        assert result.returncode == 3
        assert "transient" in result.stderr

    def test_bucket_fail_routes_to_failure(self, tmp_path):
        """rc=0 with bucket=fail → exit 1 (CI-failed branch, not transient)."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"bucket":"fail"}]\'; exit 0',
        )
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "CI check(s) failed" in result.stderr

    def test_bucket_pass_all_green_routes_to_merge(self, tmp_path):
        """rc=0 with two pass buckets → exit 0 (proceed to merge)."""
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"bucket":"pass"},{"bucket":"pass"}]\'; exit 0',
        )
        assert self._run(tmp_path).returncode == 0

    def test_bucket_cancel_routes_to_failure(self, tmp_path):
        """rc=0 with bucket=cancel → exit 1 (treated as failure, not transient).

        A manually cancelled check is treated conservatively as release-blocking,
        not as a retriable transient. This prevents silent green merges when a
        required check was cancelled mid-flight.
        """
        self._make_gh_stub(
            tmp_path,
            'printf \'[{"bucket":"cancel"}]\'; exit 0',
        )
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "CI check(s) failed" in result.stderr


# ─── Bug B: static tests ──────────────────────────────────────────────────────


class TestBugBStatic:
    """Static: mergeCommit retrieval is inside a bounded poll loop (while + sleep)."""

    def test_mergecommit_in_poll_loop(self):
        lines = _script_lines()

        # Find the POLL_ELAPSED while-loop boundaries — anchor on the last git pull
        # (the post-merge sync at ~line 280, not the initial sync at ~line 61).
        pull_idx = None
        for i, ln in enumerate(lines):
            if "git pull --ff-only" in ln:
                pull_idx = i
        assert pull_idx is not None, "git pull --ff-only not found in release.sh"

        while_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if i > pull_idx and re.search(r"while\s+\[\[.*POLL_ELAPSED", ln)
            ),
            None,
        )
        assert while_idx is not None, "POLL_ELAPSED while loop not found after git pull"

        done_idx = next(
            (i for i, ln in enumerate(lines) if i > while_idx and ln.strip() == "done"),
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
        pytest.fail(
            "No non-comment 'gh pr view ... mergeCommit' line found in release.sh"
        )


# ─── Bug B: dynamic tests ─────────────────────────────────────────────────────


class TestBugBDynamic:
    """Dynamic: bounded poll handles empty-then-populated and persistent-empty."""

    def _run_poll(
        self, stub_dir: Path, timeout: int = 9
    ) -> subprocess.CompletedProcess:
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
        gh.write_text(
            textwrap.dedent(f"""\
            #!/bin/sh
            COUNT=$(cat {count_file} 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {count_file}
            if [ "$COUNT" -ge 3 ]; then printf 'abc123'; fi
            exit 0
        """)
        )
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


# ─── Bug C: transient-cap tests ──────────────────────────────────────────────

# Loop snippet that mirrors the CI wait loop's transient-cap logic.
# EXIT codes: 0 = all green, 1 = CI-failed or transient-cap hit, 2 = timed out.
_TRANSIENT_LOOP_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    MAX_TRANSIENT=10
    TRANSIENT_COUNT=0
    TIMEOUT=3600
    ELAPSED=0

    while true; do
        if [[ $ELAPSED -ge $TIMEOUT ]]; then
            echo "Error: timed out" >&2
            exit 2
        fi

        set +e
        CHECKS_JSON=$(gh pr checks "42" --json bucket 2>/dev/null)
        CHECKS_RC=$?
        set -e

        if [[ $CHECKS_RC -ne 0 && $CHECKS_RC -ne 8 ]]; then
            TRANSIENT_COUNT=$((TRANSIENT_COUNT + 1))
            if [[ $TRANSIENT_COUNT -ge $MAX_TRANSIENT ]]; then
                echo "Error: too many transient gh failures (${TRANSIENT_COUNT})" >&2
                exit 1
            fi
            sleep 10; ELAPSED=$((ELAPSED + 10))
            continue
        fi

        if [[ $CHECKS_RC -eq 8 && -z "$CHECKS_JSON" ]]; then
            TRANSIENT_COUNT=$((TRANSIENT_COUNT + 1))
            if [[ $TRANSIENT_COUNT -ge $MAX_TRANSIENT ]]; then
                echo "Error: too many transient gh failures (${TRANSIENT_COUNT})" >&2
                exit 1
            fi
            sleep 10; ELAPSED=$((ELAPSED + 10))
            continue
        fi

        TRANSIENT_COUNT=0
        TOTAL=$(printf '%s' "${CHECKS_JSON:-[]}" | jq 'length')
        PENDING=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.bucket == "pending")] | length')
        FAILED=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length')

        if [[ "$TOTAL" -eq 0 ]]; then
            sleep 60; ELAPSED=$((ELAPSED + 60))
        elif [[ "$PENDING" -eq 0 ]]; then
            if [[ "$FAILED" -gt 0 ]]; then
                echo "CI check(s) failed" >&2; exit 1
            fi
            exit 0
        else
            sleep 60; ELAPSED=$((ELAPSED + 60))
        fi
    done
""")


class TestTransientCap:
    """Bug C: persistent transient gh failures must cap out, not spin to TIMEOUT."""

    def test_max_transient_defined_in_script(self):
        """release.sh must declare MAX_TRANSIENT before the CI wait loop."""
        lines = _script_lines()
        assert any(re.search(r"MAX_TRANSIENT=\d+", ln) for ln in lines if not _is_comment(ln)), (
            "MAX_TRANSIENT not found in release.sh"
        )

    def test_transient_cap_fires_before_timeout(self):
        """MAX_TRANSIENT * 10s must be strictly less than TIMEOUT.

        Ensures the transient cap always fires before the outer wall-clock
        timeout, regardless of future value changes to either constant.
        """
        lines = _script_lines()
        timeout_val = next(
            int(re.search(r"TIMEOUT=(\d+)", ln).group(1))
            for ln in lines
            if not _is_comment(ln) and re.search(r"\bTIMEOUT=\d+\b", ln)
        )
        max_transient_val = next(
            int(re.search(r"MAX_TRANSIENT=(\d+)", ln).group(1))
            for ln in lines
            if not _is_comment(ln) and re.search(r"MAX_TRANSIENT=\d+", ln)
        )
        assert max_transient_val * 10 < timeout_val, (
            f"MAX_TRANSIENT ({max_transient_val}) * 10s = {max_transient_val * 10}s "
            f">= TIMEOUT ({timeout_val}s) — cap would never fire before timeout"
        )

    def test_persistent_transient_exits_before_timeout(self, tmp_path):
        """A stubbed gh that always returns transient rc causes the loop to exit
        after MAX_TRANSIENT attempts (TIMEOUT=3600), not spin to timeout."""
        sleep_stub = tmp_path / "sleep"
        sleep_stub.write_text("#!/bin/sh\nexit 0\n")
        sleep_stub.chmod(0o755)
        gh_stub = tmp_path / "gh"
        gh_stub.write_text("#!/bin/sh\nexit 1\n")
        gh_stub.chmod(0o755)
        env = {**_CLEAN_ENV, "PATH": f"{tmp_path}:{_CLEAN_ENV.get('PATH', '')}"}
        result = subprocess.run(
            ["bash", "-c", _TRANSIENT_LOOP_SNIPPET],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,  # must complete well before the 3600s TIMEOUT
        )
        assert result.returncode == 1, (
            f"Expected exit 1 (transient cap); got {result.returncode}\nstderr: {result.stderr}"
        )
        assert "transient" in result.stderr.lower(), (
            f"Expected 'transient' in stderr: {result.stderr!r}"
        )

    def test_transient_count_resets_on_success(self, tmp_path):
        """A transient followed by a clean response resets the counter; N transients
        then a clean response must succeed, not trip the cap."""
        sleep_stub = tmp_path / "sleep"
        sleep_stub.write_text("#!/bin/sh\nexit 0\n")
        sleep_stub.chmod(0o755)
        count_file = tmp_path / "count"
        count_file.write_text("0")
        gh_stub = tmp_path / "gh"
        gh_stub.write_text(textwrap.dedent(f"""\
            #!/bin/sh
            COUNT=$(cat {count_file} 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {count_file}
            # First 5 calls: transient; call 6: clean pass
            if [ "$COUNT" -le 5 ]; then exit 1; fi
            printf '[{{"bucket":"pass"}}]'
            exit 0
        """))
        gh_stub.chmod(0o755)
        env = {**_CLEAN_ENV, "PATH": f"{tmp_path}:{_CLEAN_ENV.get('PATH', '')}"}
        result = subprocess.run(
            ["bash", "-c", _TRANSIENT_LOOP_SNIPPET],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (recovered after transients); got {result.returncode}\nstderr: {result.stderr}"
        )
