"""
Regression tests for resume of merged-but-untagged releases (issue #695).

A release stranded between PR merge and tag publication must be finished by
a re-run; transient git/gh transport failures must retry boundedly instead
of aborting the release mid-flight.
"""

import re
import subprocess
import textwrap
from pathlib import Path

from conftest import _CLEAN_ENV

RELEASE_SH = Path(__file__).parent.parent / "scripts" / "release.sh"


def _script_lines() -> list[str]:
    return RELEASE_SH.read_text().splitlines()


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _write_stub(stub_dir: Path, name: str, body: str) -> None:
    stub = stub_dir / name
    stub.write_text(f"#!/bin/sh\n{body}\n")
    stub.chmod(0o755)


def _run_snippet(
    snippet: str, stub_dir: Path, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    env = {**_CLEAN_ENV, "PATH": f"{stub_dir}:{_CLEAN_ENV.get('PATH', '')}"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", snippet], capture_output=True, text=True, env=env, timeout=30
    )


_RETRY_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    retry_transport() {
      local max_attempts=$1 desc=$2
      shift 2
      local attempt=0
      while true; do
        if "$@"; then
          return 0
        fi
        attempt=$((attempt + 1))
        if [[ "$attempt" -ge "$max_attempts" ]]; then
          echo "Error: ${desc} failed after ${attempt} attempts (transient failure cap reached)." >&2
          echo "  Re-run this script — it resumes the unfinished release." >&2
          return 1
        fi
        echo "[$(date '+%H:%M:%S')] ${desc} transient failure (attempt ${attempt}/${max_attempts}); retrying in 10s..." >&2
        sleep 10
      done
    }
    retry_transport 3 "git fetch" git fetch origin
""")


class TestRetryTransportStatic:
    def test_retry_transport_defined(self):
        assert any(
            ln.startswith("retry_transport()")
            for ln in _script_lines()
            if not _is_comment(ln)
        ), "retry_transport() function definition not found"

    def test_transport_ops_are_wrapped(self):
        """fetch, both pulls, and the tag push must run via retry_transport."""
        lines = [ln for ln in _script_lines() if not _is_comment(ln)]
        for pattern in (
            r"retry_transport\s+\d+\s+\"git fetch[^\"]*\"\s+git fetch\b",
            r"retry_transport\s+\d+\s+\"git pull[^\"]*\"\s+git pull --ff-only\b",
            r"retry_transport\s+\d+\s+\"branch push[^\"]*\"\s+git push\b",
            r"retry_transport\s+\d+\s+\"tag push[^\"]*\"\s+git push\b",
        ):
            assert any(re.search(pattern, ln) for ln in lines), (
                f"No line matches required wrapper pattern: {pattern}"
            )

    def test_git_pull_always_wrapped(self):
        """Every executable 'git pull --ff-only' runs via retry_transport.

        Echo'd guidance strings may mention git pull — they are recipes the
        operator runs by hand, not transport ops this script executes. Task 4
        replaces that guidance with --resume and guards it separately.
        """
        for ln in _script_lines():
            if _is_comment(ln) or "git pull --ff-only" not in ln:
                continue
            if "echo " in ln:
                continue
            assert re.search(
                r"retry_transport\s+\d+\s+\"git pull[^\"]*\"\s+git pull --ff-only", ln
            ), f"Bare 'git pull --ff-only' outside retry_transport: {ln.strip()!r}"


class TestRetryTransportDynamic:
    def test_transient_then_success(self, tmp_path):
        """git fails twice then succeeds → exit 0, three attempts recorded."""
        _write_stub(
            tmp_path,
            "git",
            textwrap.dedent(f"""\
            COUNT=$(cat {tmp_path}/count 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {tmp_path}/count
            [ "$COUNT" -ge 3 ] && exit 0
            exit 128
        """),
        )
        _write_stub(tmp_path, "sleep", "exit 0")
        result = _run_snippet(_RETRY_SNIPPET, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert (tmp_path / "count").read_text().strip() == "3"

    def test_persistent_failure_caps_out(self, tmp_path):
        _write_stub(tmp_path, "git", "exit 128")
        _write_stub(
            tmp_path,
            "sleep",
            textwrap.dedent(f"""\
            COUNT=$(cat {tmp_path}/sleeps 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {tmp_path}/sleeps
            exit 0
        """),
        )
        result = _run_snippet(_RETRY_SNIPPET, tmp_path)
        assert result.returncode == 1
        assert "transient failure cap reached" in result.stderr
        assert (tmp_path / "sleeps").read_text().strip() == "2", (
            "cap(3) allows 2 sleeps, then the 3rd failure aborts"
        )
