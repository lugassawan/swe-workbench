"""End-to-end tests for bin/swe-workbench-doctor (closes #238)."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCTOR_SH = ROOT / "bin" / "swe-workbench-doctor"

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
            case "$1" in
              --version) echo "git version 2.44.0" ;;
              rev-parse) exit 128 ;;
              *)         exit 1 ;;
            esac
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
        "python3": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "Python 3.11.0"
        """),
    }

    for name, body in tools.items():
        if name in omit:
            continue
        script = bin_dir / name
        script.write_text(body)
        script.chmod(0o755)

    return bin_dir


def _run_doctor(env: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _hygiene_env(tmp_path: Path) -> dict:
    """PATH with mocked non-git tools in front, real git resolved from the
    inherited system PATH — the hygiene checks need a real `git check-ignore`/
    `ls-files`, which the dispatch-on-$1 mock (landmine 4) does not implement."""
    bin_dir = _make_mock_tools(tmp_path, omit={"git"})
    return {
        **_CLEAN_ENV,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
    }


def _init_repo(repo_dir: Path, env: dict) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, env=env, check=True)


def test_script_exists_and_executable():
    """bin/swe-workbench-doctor must exist and be executable."""
    assert DOCTOR_SH.exists(), "bin/swe-workbench-doctor must exist"
    assert os.access(DOCTOR_SH, os.X_OK), "bin/swe-workbench-doctor must be executable (chmod +x)"


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
    # header + separator + 6 tool lines + separator + summary = at least 10 non-empty lines
    assert len(lines) >= 10, f"Expected at least 10 non-empty output lines, got {len(lines)}: {lines}"
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


# ── Repo hygiene section ──────────────────────────────────────────────────────


def test_hygiene_warns_when_not_ignored(tmp_path):
    """A repo with no .gitignore entry for .claude/cache/ must get a warning
    naming both sidecar writers, with the .claude/cache/ remediation hint."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "Repo hygiene" in result.stdout
    assert "not gitignored" in result.stdout
    assert ".claude/cache/" in result.stdout
    assert "1 warning" in result.stdout


def test_hygiene_clean_when_ignored(tmp_path):
    """A repo with .gitignore = .claude/cache/ must show a clean row and no warning."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    (repo / ".gitignore").write_text(".claude/cache/\n")
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "Repo hygiene" in result.stdout
    assert "not gitignored" not in result.stdout
    hygiene_section = result.stdout.split("Repo hygiene", 1)[1]
    assert "✓" in hygiene_section


def test_hygiene_accepts_broader_pattern(tmp_path):
    """A broader ignore pattern like .claude/** must satisfy the pattern check (AC#2)."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    (repo / ".gitignore").write_text(".claude/**\n")
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "not gitignored" not in result.stdout
    hygiene_section = result.stdout.split("Repo hygiene", 1)[1]
    assert "✓" in hygiene_section


def test_hygiene_warns_on_asymmetric_subdirectory_coverage(tmp_path):
    """A .gitignore that only covers one sidecar subdirectory (skill-usage/) but not
    the other (workflow-state/) must still warn — this is the actual value of probing
    3 separate paths instead of just the .claude/cache/ parent: a single top-level
    probe would miss this partial-coverage gap entirely."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    (repo / ".gitignore").write_text(".claude/cache/skill-usage/\n")
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "not gitignored" in result.stdout


def test_hygiene_accepts_git_info_exclude(tmp_path):
    """A pattern living only in .git/info/exclude (never committed) must also satisfy
    the pattern check — git check-ignore consults it, unlike .gitignore text-parsing."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    exclude_file = repo / ".git" / "info" / "exclude"
    with exclude_file.open("a") as f:
        f.write(".claude/cache/\n")
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "not gitignored" not in result.stdout
    hygiene_section = result.stdout.split("Repo hygiene", 1)[1]
    assert "✓" in hygiene_section


def test_hygiene_warns_when_already_tracked(tmp_path):
    """A file already committed under .claude/cache/ must trigger the tracked-file
    warning even though the pattern is present — regression guard for landmine 1
    (check-ignore without --no-index would false-negative the pattern check here)."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    cache_dir = repo / ".claude" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "tracked.json").write_text("{}\n")
    subprocess.run(["git", "add", "-f", ".claude/cache/tracked.json"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, env=env, check=True)
    (repo / ".gitignore").write_text(".claude/cache/\n")
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "1 file already tracked under .claude/cache/." in result.stdout
    assert "git rm -r --cached .claude/cache/" in result.stdout
    # pattern check must stay clean — the tracked-file warning is independent
    assert "not gitignored" not in result.stdout


def test_hygiene_skipped_outside_git_repo(tmp_path):
    """Outside a git repo the hygiene section must be entirely absent, no false warning."""
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    env = _hygiene_env(tmp_path)
    result = _run_doctor(env, cwd=non_repo)
    assert result.returncode == 0
    assert "Repo hygiene" not in result.stdout


def test_hygiene_does_not_inflate_dependency_summary(tmp_path):
    """A hygiene warning must not affect the dependency section's own summary line
    or counter — they are independent, per commands/doctor.md's exit-0 contract."""
    repo = tmp_path / "repo"
    env = _hygiene_env(tmp_path)
    _init_repo(repo, env)
    result = _run_doctor(env, cwd=repo)
    assert result.returncode == 0
    assert "All dependencies present." in result.stdout
    assert "Repo hygiene" in result.stdout
    assert "not gitignored" in result.stdout
