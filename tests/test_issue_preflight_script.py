"""Behavioural tests for bin/swe-workbench-issue-preflight.

The script classifies the gh auth + repo-access preflight that /swe-workbench:report-issue
runs before filing, so the command prose never has to interpret free-form gh stderr. It
drives gh only through the sibling swe-workbench-gh-timeout, so every case here puts a
dispatch stub named `gh` first on PATH. The stub logs its argv, which lets the tests pin
the exact command shapes: `auth status` is host-scoped and takes no repo, and
`repo view` takes the repo positionally.

Real-gh flag acceptance (the stub cannot prove gh parses a flag) is covered separately by
tests/test_report_issue_gh_compat.py.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-issue-preflight"
RESULT_CHECK = ROOT / "bin" / "swe-workbench-result-check"
SCHEMA = "swb.issue-preflight/1"
REPO = "lugassawan/swe-workbench"

VERSION_OK = "gh version 2.62.0 (2025-01-15)\nhttps://github.com/cli/cli/releases/tag/v2.62.0\n"

# Both real-world `gh auth status` shapes: older gh single-quotes every scope, newer gh
# prints them bare. Neither shape includes a scopes line for a fine-grained token.
AUTH_QUOTED = (
    "github.com\n"
    "  ✓ Logged in to github.com account someone (keyring)\n"
    "  - Active account: true\n"
    "  - Git operations protocol: https\n"
    "  - Token: gho_************************************\n"
    "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'\n"
)
AUTH_BARE = AUTH_QUOTED.replace("'gist', 'read:org', 'repo', 'workflow'", "gist, read:org, repo, workflow")
AUTH_PUBLIC_REPO = AUTH_QUOTED.replace("'gist', 'read:org', 'repo', 'workflow'", "'gist', 'public_repo'")
AUTH_NO_REPO_SCOPE = AUTH_QUOTED.replace("'gist', 'read:org', 'repo', 'workflow'", "'gist', 'read:org'")
# `admin:repo_hook` contains the substring "repo" but is not the repo scope.
AUTH_REPO_SUBSTRING = AUTH_QUOTED.replace("'gist', 'read:org', 'repo', 'workflow'", "'admin:repo_hook', 'gist'")
AUTH_NO_SCOPES_LINE = (
    "github.com\n"
    "  ✓ Logged in to github.com account someone (GH_TOKEN)\n"
    "  - Active account: true\n"
    "  - Git operations protocol: https\n"
)
AUTH_LOGGED_OUT = (
    "You are not logged into any GitHub hosts. To log in, run: gh auth login\n"
)


def _make_gh_stub(
    stub_dir: Path,
    *,
    version: str = VERSION_OK,
    version_rc: int = 0,
    auth: str = AUTH_QUOTED,
    auth_rc: int = 0,
    auth_stream: str = "stdout",
    repo: str = REPO + "\n",
    repo_rc: int = 0,
) -> Path:
    """Write a fake gh that dispatches on argv and logs every call. Returns the log path.

    - `--version`   -> `version`, exit `version_rc`
    - `auth status` -> `auth` on `auth_stream`, exit `auth_rc`
    - `repo view …` -> `repo` (stdout when rc 0, stderr otherwise, like real gh), exit `repo_rc`
    """
    stub_dir.mkdir(exist_ok=True)
    log = stub_dir / "_argv.log"
    log.write_text("")
    for name, body in (("_version", version), ("_auth", auth), ("_repo", repo)):
        (stub_dir / name).write_text(body)
    auth_redirect = ">&2" if auth_stream == "stderr" else ""
    repo_redirect = ">&2" if repo_rc != 0 else ""
    stub = stub_dir / "gh"
    stub.write_text(f"""#!/bin/sh
printf '%s\\n' "$*" >> '{log}'
case "$1" in
  --version)
    cat '{stub_dir / "_version"}'
    exit {version_rc}
    ;;
  auth)
    if [ "$2" = "status" ]; then
      cat '{stub_dir / "_auth"}' {auth_redirect}
      exit {auth_rc}
    fi
    exit 1
    ;;
  repo)
    if [ "$2" = "view" ]; then
      cat '{stub_dir / "_repo"}' {repo_redirect}
      exit {repo_rc}
    fi
    exit 1
    ;;
esac
exit 1
""")
    stub.chmod(0o755)
    return log


def _run(args, *, stub_dir=None, path=None):
    """Run the script. `stub_dir` is prepended to the real PATH; `path` replaces it outright."""
    env = dict(_CLEAN_ENV)
    if path is not None:
        env["PATH"] = str(path)
    elif stub_dir is not None:
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )


def _envelope(result):
    assert result.returncode == 0, f"expected exit 0, got {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)


def _preflight(tmp_path, **stub_kwargs):
    stub_dir = tmp_path / "stub"
    log = _make_gh_stub(stub_dir, **stub_kwargs)
    result = _run([REPO], stub_dir=stub_dir)
    return _envelope(result), log


def _warning_codes(envelope):
    return [w["code"] for w in envelope["warnings"]]


# ── ok paths ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("auth", [AUTH_QUOTED, AUTH_BARE, AUTH_PUBLIC_REPO], ids=["quoted", "bare", "public_repo"])
def test_repo_or_public_repo_scope_is_ok(tmp_path, auth):
    envelope, _ = _preflight(tmp_path, auth=auth)
    assert envelope["schema"] == SCHEMA
    assert envelope["status"] == "ok"
    data = envelope["data"]
    assert data["repo"] == REPO
    assert data["name_with_owner"] == REPO
    assert data["failure_kind"] == ""
    assert data["scope_status"] == "ok"
    assert data["gh_version"] == "2.62.0"
    assert envelope["warnings"] == []


def test_auth_status_read_from_stderr(tmp_path):
    """Older gh prints `auth status` on stderr; the scopes line must still be found."""
    envelope, _ = _preflight(tmp_path, auth=AUTH_QUOTED, auth_stream="stderr")
    assert envelope["status"] == "ok"
    assert envelope["data"]["scope_status"] == "ok"


# ── scope: warning, never a failure ──────────────────────────────────────────

@pytest.mark.parametrize("auth", [AUTH_NO_REPO_SCOPE, AUTH_REPO_SUBSTRING], ids=["no-repo-scope", "repo-substring"])
def test_scopes_without_repo_are_insufficient_warning(tmp_path, auth):
    envelope, _ = _preflight(tmp_path, auth=auth)
    assert envelope["status"] == "ok", "an insufficient scope must warn and continue, not fail"
    assert envelope["data"]["scope_status"] == "insufficient"
    assert envelope["data"]["failure_kind"] == ""
    assert _warning_codes(envelope) == ["insufficient_scope"]


def test_missing_scopes_line_is_unknown_warning(tmp_path):
    """A fine-grained token or GH_TOKEN reports no scopes line at all."""
    envelope, _ = _preflight(tmp_path, auth=AUTH_NO_SCOPES_LINE)
    assert envelope["status"] == "ok"
    assert envelope["data"]["scope_status"] == "unknown"
    assert _warning_codes(envelope) == ["scope_unknown"]


# ── auth failures ────────────────────────────────────────────────────────────

def test_auth_status_nonzero_is_unauthenticated(tmp_path):
    envelope, log = _preflight(tmp_path, auth=AUTH_LOGGED_OUT, auth_rc=1, auth_stream="stderr")
    assert envelope["status"] == "failed"
    data = envelope["data"]
    assert data["failure_kind"] == "unauthenticated"
    assert data["name_with_owner"] == ""
    assert "not logged into" in data["reason"]
    assert not any(line.startswith("repo view") for line in log.read_text().splitlines()), (
        "an unauthenticated gh must stop before the repo view call"
    )


def test_auth_status_unknown_flag_beats_auth_failure(tmp_path):
    """gh exits non-zero for an unknown flag too; that must not read as 'not logged in'."""
    envelope, _ = _preflight(
        tmp_path, auth="unknown flag: --repo\n\nUsage:  gh auth status [flags]\n", auth_rc=1, auth_stream="stderr"
    )
    assert envelope["status"] == "failed"
    assert envelope["data"]["failure_kind"] == "unsupported_flag"
    assert envelope["data"]["reason"] == "unknown flag: --repo"


def test_auth_status_timeout_is_unknown_not_unauthenticated(tmp_path):
    envelope, _ = _preflight(tmp_path, auth="", auth_rc=124, auth_stream="stderr")
    assert envelope["status"] == "failed"
    assert envelope["data"]["failure_kind"] == "unknown"


# ── repo view failures ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "repo_out",
    [
        "GraphQL: Could not resolve to a Repository with the name 'lugassawan/swe-workbench'. (repository)\n",
        "HTTP 404: Not Found (https://api.github.com/repos/lugassawan/swe-workbench)\n",
    ],
    ids=["graphql-resolve", "http-404"],
)
def test_repo_view_not_found_is_repo_inaccessible(tmp_path, repo_out):
    envelope, _ = _preflight(tmp_path, repo=repo_out, repo_rc=1)
    assert envelope["status"] == "failed"
    data = envelope["data"]
    assert data["failure_kind"] == "repo_inaccessible"
    assert data["name_with_owner"] == ""
    assert data["scope_status"] == "ok", "scope was already read before the repo view failed"


def test_repo_view_unknown_flag_is_unsupported_flag(tmp_path):
    envelope, _ = _preflight(tmp_path, repo="unknown shorthand flag: 'x' in -x\n", repo_rc=1)
    assert envelope["status"] == "failed"
    assert envelope["data"]["failure_kind"] == "unsupported_flag"


@pytest.mark.parametrize(
    "repo_out",
    [
        "To get started with GitHub CLI, please run:  gh auth login\n",
        "HTTP 401: Bad credentials (https://api.github.com/graphql)\n",
    ],
    ids=["gh-auth-login", "bad-credentials"],
)
def test_repo_view_auth_markers_are_unauthenticated(tmp_path, repo_out):
    envelope, _ = _preflight(tmp_path, repo=repo_out, repo_rc=1)
    assert envelope["status"] == "failed"
    assert envelope["data"]["failure_kind"] == "unauthenticated"


@pytest.mark.parametrize(
    ("repo_out", "repo_rc"),
    [
        ("error connecting to api.github.com\n", 1),
        ("Get \"https://api.github.com/graphql\": dial tcp: lookup api.github.com: Could not resolve host\n", 1),
        ("", 124),
    ],
    ids=["network", "could-not-resolve-host", "timeout"],
)
def test_repo_view_other_failures_are_unknown(tmp_path, repo_out, repo_rc):
    """Anything unrecognised — including a network error that merely says 'Could not
    resolve' — must not be misreported as the repo being inaccessible."""
    envelope, _ = _preflight(tmp_path, repo=repo_out, repo_rc=repo_rc)
    assert envelope["status"] == "failed"
    assert envelope["data"]["failure_kind"] == "unknown"


def test_unknown_failure_carries_first_meaningful_line_as_reason(tmp_path):
    envelope, _ = _preflight(tmp_path, repo="\n\n  something odd happened\nsecond line\n", repo_rc=1)
    assert envelope["data"]["reason"] == "something odd happened"


# ── gh missing / version ─────────────────────────────────────────────────────

def test_gh_missing_is_gh_missing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _run([REPO], path=empty)
    envelope = _envelope(result)
    assert envelope["status"] == "failed"
    assert envelope["data"]["failure_kind"] == "gh_missing"
    assert envelope["data"]["gh_version"] == ""


def test_version_below_minimum_warns_but_still_runs(tmp_path):
    envelope, log = _preflight(tmp_path, version="gh version 2.44.1 (2024-03-01)\n")
    assert envelope["status"] == "ok", "the minimum version is advisory; real behaviour is the authority"
    assert envelope["data"]["gh_version"] == "2.44.1"
    assert "gh_below_minimum" in _warning_codes(envelope)
    assert any(line.startswith("repo view") for line in log.read_text().splitlines())


@pytest.mark.parametrize("version", ["2.45.0", "2.45.1", "2.102.0", "3.0.0"])
def test_version_at_or_above_minimum_does_not_warn(tmp_path, version):
    """2.102.0 sorts below 2.45.0 as a string; the comparison must be numeric."""
    envelope, _ = _preflight(tmp_path, version=f"gh version {version} (2026-01-01)\n")
    assert envelope["data"]["gh_version"] == version
    assert "gh_below_minimum" not in _warning_codes(envelope)


def test_unparseable_version_is_empty_and_silent(tmp_path):
    envelope, _ = _preflight(tmp_path, version="not a version banner\n")
    assert envelope["status"] == "ok"
    assert envelope["data"]["gh_version"] == ""
    assert "gh_below_minimum" not in _warning_codes(envelope)


# ── argv shape ───────────────────────────────────────────────────────────────

def test_argv_log_pins_command_shapes(tmp_path):
    """`auth status` is host-scoped and must get no repo flag; `repo view` takes the repo
    positionally and must not get --repo."""
    _, log = _preflight(tmp_path)
    lines = log.read_text().splitlines()
    assert "auth status" in lines
    assert f"repo view {REPO} --json nameWithOwner --jq .nameWithOwner" in lines
    assert not any("--repo" in line for line in lines), f"no gh call may carry --repo: {lines}"


# ── bad invocation ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "args",
    [
        [],
        ["not-a-slug"],
        ["a/b/c"],
        ["owner/re po"],
        ["owner/"],
        ["/repo"],
        ["-x/y"],
        ["--repo", REPO],
        [REPO, "extra"],
    ],
    ids=["none", "no-slash", "three-parts", "space", "empty-repo", "empty-owner", "leading-dash", "flag", "extra-arg"],
)
def test_bad_or_missing_argument_exits_2_without_calling_gh(tmp_path, args):
    stub_dir = tmp_path / "stub"
    log = _make_gh_stub(stub_dir)
    result = _run(args, stub_dir=stub_dir)
    assert result.returncode == 2, f"expected exit 2 for {args}, got {result.returncode}"
    assert result.stdout == ""
    assert "Usage:" in result.stderr
    assert log.read_text() == "", "argument validation must happen before any gh call"


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_docstring(flag):
    result = _run([flag])
    assert result.returncode == 0
    assert "swe-workbench-issue-preflight" in result.stdout
    assert "swb.issue-preflight/1" in result.stdout


# ── envelope contract ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"auth": AUTH_NO_REPO_SCOPE},
        {"auth": AUTH_NO_SCOPES_LINE},
        {"auth": AUTH_LOGGED_OUT, "auth_rc": 1, "auth_stream": "stderr"},
        {"repo": "HTTP 404: Not Found\n", "repo_rc": 1},
        {"version": "gh version 2.40.0 (2023-12-01)\n"},
    ],
    ids=["ok", "insufficient", "unknown-scope", "unauthenticated", "inaccessible", "old-gh"],
)
def test_every_envelope_passes_result_check(tmp_path, kwargs):
    stub_dir = tmp_path / "stub"
    _make_gh_stub(stub_dir, **kwargs)
    produced = _run([REPO], stub_dir=stub_dir)
    assert produced.returncode == 0, produced.stderr
    checked = subprocess.run(
        [sys.executable, str(RESULT_CHECK), SCHEMA],
        input=produced.stdout, capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    assert checked.returncode == 0, f"result-check rejected the envelope: {checked.stderr}"
    assert json.loads(checked.stdout) == json.loads(produced.stdout)


def test_data_fields_are_all_strings(tmp_path):
    envelope, _ = _preflight(tmp_path)
    assert set(envelope["data"]) == {
        "repo", "name_with_owner", "failure_kind", "reason", "scope_status", "gh_version",
    }
    assert all(isinstance(v, str) for v in envelope["data"].values())
