"""Real-gh compatibility checks for /swe-workbench:report-issue.

The PATH-stub tests in test_issue_preflight_script.py and the prose assertions in
test_report_issue_command.py cannot prove that a real gh parses the flags the flow uses —
a stub accepts anything. This file runs the commands against real gh binaries instead:

  - the current gh on PATH, and
  - the pinned minimum gh named by $SWB_GH_MIN_BIN (the version the README promises).

Nothing here may reach GitHub or mutate anything. gh is run with no token, an empty
config dir, an unresolvable host, and a dead proxy; gh rejects an unknown flag before it
checks auth or touches the network, so "no unknown-flag error" is exactly the property
under test. `gh issue create` and the other mutating commands are never executed — their
flags are checked against that command's own `--help` output.

A missing binary skips the test locally. With SWB_REQUIRE_GH_COMPAT=1 (set in CI) the
current gh is required, and the minimum gh is required whenever SWB_GH_MIN_BIN is set —
the Ubuntu leg provisions it, the macOS leg does not.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV
from helpers import gh_spans

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-issue-preflight"
REPORT_ISSUE_MD = ROOT / "commands" / "report-issue.md"
README = ROOT / "README.md"
REPO = "lugassawan/swe-workbench"

# Credentials that would turn a "no auth" run into a real, authenticated one.
_STRIPPED_ENV = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "NO_PROXY",
    "no_proxy",
)
_DEAD_PROXY = "http://127.0.0.1:9"
_UNKNOWN_FLAG_RE = re.compile(r"unknown (?:shorthand )?flag|unknown command", re.IGNORECASE)

# Commands safe to run with no token: read-only, and rejected at flag-parse or auth time.
_EXECUTABLE = {("label", "list"), ("issue", "list"), ("api",), ("repo", "view"), ("auth", "status")}
_FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*|-[a-zA-Z])(?=[\s=\]]|$)")


def _load_script_module():
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # never drop a __pycache__ into bin/
    try:
        loader = SourceFileLoader("issue_preflight", str(SCRIPT))
        spec = importlib.util.spec_from_file_location("issue_preflight", SCRIPT, loader=loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


preflight = _load_script_module()


def _command_key(span: str):
    """The (group, subcommand) a gh span invokes, or None for a descriptive fragment."""
    tokens = span.split()
    if len(tokens) < 2 or tokens[0] != "gh":
        return None
    if tokens[1] == "api":
        return ("api",)
    if len(tokens) >= 3 and re.fullmatch(r"[a-z-]+", tokens[2]):
        return (tokens[1], tokens[2])
    return None


def _prose_spans():
    return [s for s in gh_spans(REPORT_ISSUE_MD.read_text()) if _command_key(s)]


def _runnable(span: str) -> bool:
    """Executable commands with real arguments; a bare `gh repo view` would resolve its
    repo from cwd, and descriptive three-token mentions say nothing about flag shapes."""
    key = _command_key(span)
    return key in _EXECUTABLE and (key == ("auth", "status") or len(span.split()) >= 4)


def _argv_for(span: str) -> list[str]:
    """The prose command with placeholders filled, cut at the first pipe."""
    first_segment = span.split(" | ")[0]
    return shlex.split(re.sub(r"<[^>]+>", "placeholder", first_segment))


RUNNABLE_SPANS = sorted({s for s in _prose_spans() if _runnable(s)})
MUTATING_SPANS = sorted({s for s in _prose_spans() if _command_key(s) not in _EXECUTABLE})


@pytest.fixture(params=["current", "minimum"])
def gh_bin(request):
    require = os.environ.get("SWB_REQUIRE_GH_COMPAT") == "1"
    if request.param == "current":
        path, required = shutil.which("gh"), require
    else:
        path = os.environ.get("SWB_GH_MIN_BIN")
        required = require and bool(path)
    if not path or not os.access(path, os.X_OK):
        message = f"no {request.param} gh binary available (path={path!r})"
        if required:
            pytest.fail(message + " — SWB_REQUIRE_GH_COMPAT=1 requires it")
        pytest.skip(message)
    return Path(path)


@pytest.fixture
def gh_env(gh_bin, tmp_path):
    env = {k: v for k, v in _CLEAN_ENV.items() if k not in _STRIPPED_ENV}
    config_dir = tmp_path / "gh-config"
    config_dir.mkdir()
    env.update({
        "PATH": f"{gh_bin.parent}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}",
        "GH_CONFIG_DIR": str(config_dir),
        "GH_HOST": "gh.invalid",
        "HTTP_PROXY": _DEAD_PROXY,
        "HTTPS_PROXY": _DEAD_PROXY,
        "ALL_PROXY": _DEAD_PROXY,
        "http_proxy": _DEAD_PROXY,
        "https_proxy": _DEAD_PROXY,
        "all_proxy": _DEAD_PROXY,
        "GH_PROMPT_DISABLED": "1",
        "GH_NO_UPDATE_NOTIFIER": "1",
    })
    return env


def _gh(gh_bin: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(gh_bin), *args],
        capture_output=True, text=True, errors="replace",
        env=env, cwd=str(ROOT), timeout=60,
    )


def _combined(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def test_the_prose_yields_commands_to_check():
    """A parser regression must not turn the checks below into vacuous passes."""
    assert len(RUNNABLE_SPANS) >= 5, f"expected the prose's read-only gh commands: {RUNNABLE_SPANS}"
    assert any(s.startswith("gh issue create") for s in MUTATING_SPANS), MUTATING_SPANS
    assert any(s.startswith("gh auth refresh") for s in MUTATING_SPANS), MUTATING_SPANS


def test_minimum_binary_is_the_declared_minimum(gh_bin, request):
    if "minimum" not in request.node.callspec.id:
        pytest.skip("only meaningful for the pinned minimum binary")
    reported = subprocess.run(
        [str(gh_bin), *preflight.VERSION_ARGS], capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    parsed = preflight.parse_version(reported.stdout + reported.stderr)
    assert parsed is not None, f"could not parse gh --version: {reported.stdout!r}"
    assert ".".join(map(str, parsed)) == preflight.MIN_GH_VERSION, (
        f"$SWB_GH_MIN_BIN must be gh {preflight.MIN_GH_VERSION} (MIN_GH_VERSION), got {parsed}"
    )


def test_readme_states_the_declared_minimum_gh_version():
    assert f"gh {preflight.MIN_GH_VERSION} or newer" in README.read_text(), (
        f"README.md must state the minimum gh as MIN_GH_VERSION ({preflight.MIN_GH_VERSION})"
    )


def test_preflight_end_to_end_reports_unauthenticated(gh_bin, gh_env):
    """With no credentials the real gh's own not-logged-in output must classify as
    unauthenticated — not unsupported_flag and not unknown."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), REPO],
        capture_output=True, text=True, env=gh_env, cwd=str(ROOT), timeout=120,
    )
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "failed", envelope
    assert envelope["data"]["failure_kind"] == "unauthenticated", envelope
    assert envelope["data"]["gh_version"], "gh --version must parse on a real gh"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(preflight.VERSION_ARGS, id="version"),
        pytest.param(preflight.AUTH_STATUS_ARGS, id="auth-status"),
        pytest.param(preflight.repo_view_args(REPO), id="repo-view"),
    ],
)
def test_preflight_script_argv_is_accepted_by_real_gh(gh_bin, gh_env, argv):
    """The end-to-end run stops at `auth status`, so `repo view` flags are exercised here,
    from the script's own argv builder rather than a copy."""
    result = _gh(gh_bin, gh_env, *argv)
    assert not _UNKNOWN_FLAG_RE.search(_combined(result)), (
        f"gh {' '.join(argv)} was rejected as an unknown flag/command:\n{_combined(result)}"
    )


@pytest.mark.parametrize("span", RUNNABLE_SPANS, ids=lambda s: s[:70])
def test_prose_read_only_gh_commands_are_accepted_by_real_gh(gh_bin, gh_env, span):
    argv = _argv_for(span)
    assert argv[0] == "gh", argv
    result = _gh(gh_bin, gh_env, *argv[1:])
    assert not _UNKNOWN_FLAG_RE.search(_combined(result)), (
        f"`{span}` was rejected as an unknown flag/command by {gh_bin}:\n{_combined(result)}"
    )


@pytest.mark.parametrize("span", MUTATING_SPANS, ids=lambda s: s[:70])
def test_prose_mutating_gh_commands_use_flags_their_help_documents(gh_bin, gh_env, span):
    """Never executed — `gh issue create` would file a real issue. Each flag must instead
    appear in that command's own --help."""
    key = _command_key(span)
    flags = _FLAG_RE.findall(span)
    if not flags:
        pytest.skip("no flags to verify")
    help_result = _gh(gh_bin, gh_env, *key, "--help")
    assert help_result.returncode == 0, f"gh {' '.join(key)} --help failed:\n{_combined(help_result)}"
    help_text = _combined(help_result)
    for flag in flags:
        assert re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text), (
            f"`{span}` uses {flag}, which `gh {' '.join(key)} --help` does not document "
            f"for {gh_bin}"
        )


def test_unknown_flag_wording_canary(gh_bin, gh_env):
    """The classifier keys on gh's 'unknown flag' wording. If a gh release rewords it, this
    fails here instead of silently reclassifying the old bug as 'repo inaccessible'."""
    long_flag = _gh(gh_bin, gh_env, "repo", "view", "--repo", "x/y")
    assert long_flag.returncode != 0
    assert preflight.UNKNOWN_FLAG_RE.search(_combined(long_flag)), _combined(long_flag)
    short_flag = _gh(gh_bin, gh_env, "auth", "status", "-Z")
    assert short_flag.returncode != 0
    assert preflight.UNKNOWN_FLAG_RE.search(_combined(short_flag)), _combined(short_flag)
