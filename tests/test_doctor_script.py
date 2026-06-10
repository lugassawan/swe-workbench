"""End-to-end tests for runtime/doctor.sh (closes #238)."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCTOR_SH = ROOT / "runtime" / "doctor.sh"

from conftest import _CLEAN_ENV


def _make_mock_tools(tmp_path: Path, omit: set | None = None) -> Path:
    """Create mock tool binaries in tmp_path/bin; return the bin directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    omit = omit or set()

    tools = {
        "gh": textwrap.dedent("""\
            #!/usr/bin/env bash
            if [[ "$1" == "--version" ]]; then
              echo "gh version 2.45.0 (2024-01-01)"
            elif [[ "$1" == "auth" && "$2" == "status" ]]; then
              echo "Logged in to github.com account mockuser (keyring)" >&2
            fi
        """),
        "git": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "git version 2.44.0"
        """),
        "jq": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "jq-1.7.1"
        """),
        "rimba": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "rimba 0.5.0"
        """),
        "claude": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "Claude Code 1.2.3"
        """),
    }

    for name, body in tools.items():
        if name in omit:
            continue
        script = bin_dir / name
        script.write_text(body)
        script.chmod(0o755)

    return bin_dir


def _run_doctor(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR_SH)],
        capture_output=True,
        text=True,
        env=env,
    )


def test_script_exists_and_executable():
    """runtime/doctor.sh must exist and be executable."""
    assert DOCTOR_SH.exists(), "runtime/doctor.sh must exist"
    assert os.access(DOCTOR_SH, os.X_OK), "runtime/doctor.sh must be executable (chmod +x)"


def test_exit_code_zero_when_all_present(tmp_path):
    """Doctor exits 0 when all tools are present; output has header + rows + summary."""
    bin_dir = _make_mock_tools(tmp_path)
    env = {**_CLEAN_ENV, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = _run_doctor(env)
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "✓" in result.stdout, "Output must contain ✓ for present tools"
    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    # header + separator + 5 tool lines + separator + summary = at least 9 non-empty lines
    assert len(lines) >= 9, f"Expected at least 9 non-empty output lines, got {len(lines)}: {lines}"
    assert "All dependencies present." in result.stdout, (
        "Summary line must say 'All dependencies present.' when all tools found"
    )


def test_missing_tool_prints_install_hint(tmp_path):
    """Missing-tool row must contain ✗, 'not found', and an install hint; exit still 0."""
    bin_dir = _make_mock_tools(tmp_path, omit={"rimba"})
    env = {**_CLEAN_ENV, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = _run_doctor(env)
    assert result.returncode == 0, (
        f"Exit code must be 0 even when tools are missing, got {result.returncode}"
    )
    assert "✗" in result.stdout, "Output must contain ✗ for missing tool"
    assert "not found" in result.stdout, "Missing-tool row must say 'not found'"
    assert "install" in result.stdout.lower(), "Missing-tool row must include an install hint"
    assert "missing" in result.stdout.lower(), "Summary must mention missing dependencies"


def test_gh_auth_status_surfaced(tmp_path):
    """Doctor output must include gh auth status annotation on the gh row."""
    bin_dir = _make_mock_tools(tmp_path)
    env = {**_CLEAN_ENV, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = _run_doctor(env)
    assert result.returncode == 0
    assert "gh auth" in result.stdout, (
        "Output must include 'gh auth' annotation on the gh row"
    )
    assert "logged in as mockuser" in result.stdout, (
        "gh row must display the authenticated username"
    )


def test_gh_auth_not_logged_in(tmp_path):
    """When gh auth status returns no session, gh row must say 'gh auth: not logged in'."""
    bin_dir = _make_mock_tools(tmp_path)
    gh_script = bin_dir / "gh"
    gh_script.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        if [[ "$1" == "--version" ]]; then
          echo "gh version 2.45.0 (2024-01-01)"
        elif [[ "$1" == "auth" && "$2" == "status" ]]; then
          echo "You are not logged into any GitHub hosts. Run gh auth login to authenticate." >&2
          exit 1
        fi
    """))
    gh_script.chmod(0o755)
    env = {**_CLEAN_ENV, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    result = _run_doctor(env)
    assert result.returncode == 0
    assert "gh auth: not logged in" in result.stdout, (
        "gh row must say 'gh auth: not logged in' when auth status returns no session"
    )


def test_script_writes_no_files(tmp_path):
    """Doctor must not create or modify any files or directories on disk."""
    bin_dir = _make_mock_tools(tmp_path)
    env = {**_CLEAN_ENV, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    before = set(tmp_path.rglob("*"))
    _run_doctor(env)
    after = set(tmp_path.rglob("*"))
    new_paths = after - before
    assert not new_paths, f"Doctor script created unexpected paths: {new_paths}"
