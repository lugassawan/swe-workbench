"""Structural + behavioural assertions for bin/swe-workbench-preflight-pr.

Mirrors tests/test_fetch_pr_script.py conventions.
Verifies that preflight-pr.sh:
  - exists and is executable (covered by test_bin_scripts.py)
  - resolves its sibling swe-workbench-fetch-pr via dirname "$0" (never CLAUDE_PLUGIN_ROOT)
  - emits only safe scalars via printf %q (BASE, HEAD_SHA, AUTHOR_LOGIN, OWNER, REPO, STATE)
  - NEVER echoes title or body (free-text → eval-injection risk)
  - uses set -euo pipefail
  - owns cleanup of $OUT_JSON on its own failure (an EXIT trap), and leaves
    $OUT_JSON in place on success — a caller invokes it as eval "$(...)", which
    structurally discards the script's own exit status, so the script must
    reap its own artifact rather than relying on the caller to do so.
"""

import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-preflight-pr"

SAFE_SCALARS = ["BASE", "HEAD_SHA", "AUTHOR_LOGIN", "OWNER", "REPO", "STATE"]


def test_preflight_script_exists():
    """bin/swe-workbench-preflight-pr must exist."""
    assert SCRIPT.exists(), "bin/swe-workbench-preflight-pr must exist"


def test_preflight_uses_dirname_not_env_root():
    """preflight-pr must resolve sibling scripts via dirname \"$0\", not CLAUDE_PLUGIN_ROOT.

    dirname \"$0\" always points to the directory containing preflight-pr itself,
    regardless of cwd — including an ephemeral PR worktree.
    """
    text = SCRIPT.read_text()
    assert 'dirname "$0"' in text or "$(dirname" in text, (
        "bin/swe-workbench-preflight-pr must resolve its directory via dirname \"$0\" "
        "so sibling scripts (swe-workbench-fetch-pr) are found regardless of cwd"
    )
    # Must NOT resolve via CLAUDE_PLUGIN_ROOT for the fetch-pr call itself
    assert "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse" not in text, (
        "bin/swe-workbench-preflight-pr must not use ${CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)} — "
        "use dirname \"$0\" instead so the script works in any cwd"
    )


def test_preflight_calls_fetch_pr_sh():
    """preflight-pr must delegate PR JSON fetching to sibling swe-workbench-fetch-pr."""
    text = SCRIPT.read_text()
    assert "swe-workbench-fetch-pr" in text, (
        "bin/swe-workbench-preflight-pr must call sibling bin/swe-workbench-fetch-pr to write "
        "the PR JSON — reuse the existing fetch+validation logic rather than duplicating inline gh calls"
    )


def test_preflight_emits_printf_q_for_scalars():
    """preflight-pr.sh must emit each safe scalar via printf '%q' to prevent word-splitting."""
    text = SCRIPT.read_text()
    assert "printf" in text and "%q" in text, (
        "bin/swe-workbench-preflight-pr must use printf '%q' (or printf '%%q') to quote scalar output — "
        "unquoted values in eval \"$(...)\" are vulnerable to word-splitting and injection"
    )


def test_preflight_emits_all_safe_scalars():
    """preflight-pr.sh must emit all 6 safe scalars: BASE, HEAD_SHA, AUTHOR_LOGIN, OWNER, REPO, STATE."""
    text = SCRIPT.read_text()
    missing = [s for s in SAFE_SCALARS if s not in text]
    assert not missing, (
        f"bin/swe-workbench-preflight-pr must emit all safe scalars; missing: {missing}. "
        "Skills rely on BASE/HEAD_SHA/AUTHOR_LOGIN/OWNER/REPO/STATE being set after eval."
    )


def test_preflight_does_not_echo_title():
    """preflight-pr.sh must never echo or printf the PR title (free-text → eval injection)."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    title_echo_lines = [
        ln for ln in lines
        if re.search(r'(echo|printf)[^\n]*title', ln, re.IGNORECASE)
        and not ln.lstrip().startswith("#")
    ]
    assert not title_echo_lines, (
        "bin/swe-workbench-preflight-pr must NOT echo/printf 'title' — "
        "PR titles are free-text and echoing them into eval \"$(...)\" enables code injection:\n"
        + "\n".join(title_echo_lines)
    )


def test_preflight_does_not_echo_body():
    """preflight-pr.sh must never echo or printf the PR body (free-text → eval injection)."""
    text = SCRIPT.read_text()
    lines = text.splitlines()
    body_echo_lines = [
        ln for ln in lines
        if re.search(r'(echo|printf)[^\n]*\bbody\b', ln, re.IGNORECASE)
        and not ln.lstrip().startswith("#")
    ]
    assert not body_echo_lines, (
        "bin/swe-workbench-preflight-pr must NOT echo/printf 'body' — "
        "PR bodies are free-text and echoing them into eval \"$(...)\" enables code injection:\n"
        + "\n".join(body_echo_lines)
    )


def test_preflight_has_set_euo_pipefail():
    """preflight-pr.sh must start with set -euo pipefail for fail-fast error handling."""
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text, (
        "bin/swe-workbench-preflight-pr must use 'set -euo pipefail' — "
        "without it, a failing gh call or jq parse silently produces empty variables"
    )


def test_preflight_bash_syntax():
    """bash -n must pass for preflight-pr.sh (no syntax errors)."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, (
        f"bash -n bin/swe-workbench-preflight-pr failed:\n{result.stderr}"
    )


# ── Behavioural: own-artifact cleanup ────────────────────────────────────────
#
# Extends the _make_gh_stub / PATH-prepend pattern from test_fetch_pr_script.py
# to an argument-dispatching stub, since preflight-pr drives three distinct
# `gh` subcommands (auth status, pr view, repo view) through the real sibling
# scripts (swe-workbench-gh-timeout, swe-workbench-fetch-pr) rather than a
# single call.

def _make_gh_dispatch_stub(stub_dir: Path, *, pr_json: str, pr_exit: int = 0,
                            owner: str = "test-owner", repo: str = "test-repo") -> None:
    """Write a fake gh binary that dispatches on subcommand.

    - `auth status`            -> exit 0
    - `pr view ...`            -> emit `pr_json`, exit `pr_exit`
    - `repo view --json owner` -> emit `owner`, exit 0
    - `repo view --json name`  -> emit `repo`, exit 0
    """
    stub_dir.mkdir(exist_ok=True)
    pr_json_file = stub_dir / "_pr_view_output"
    pr_json_file.write_text(pr_json)
    stub = stub_dir / "gh"
    stub.write_text(f"""#!/bin/sh
case "$1" in
  auth)
    [ "$2" = "status" ] && exit 0
    exit 1
    ;;
  pr)
    if [ "$2" = "view" ]; then
      cat '{pr_json_file}'
      exit {pr_exit}
    fi
    exit 1
    ;;
  repo)
    if [ "$2" = "view" ]; then
      for a in "$@"; do
        case "$a" in
          *owner*) echo '{owner}'; exit 0 ;;
          *name*) echo '{repo}'; exit 0 ;;
        esac
      done
    fi
    exit 1
    ;;
esac
exit 1
""")
    stub.chmod(0o755)


def _run_preflight(pr: str, out_json: Path, *, stub_dir: Path):
    env = dict(_CLEAN_ENV)
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(SCRIPT), pr, str(out_json)],
        capture_output=True, text=True,
        cwd=str(ROOT),
        env=env,
    )


# $OUT_JSON must be a sanctioned path — swe-workbench-clean-state-files (invoked
# by the trap) rejects anything outside /tmp/swe-workbench-{pr-review,
# address-feedback}/ or the bare-/tmp basename allowlist, so a tmp_path fixture
# path would make the trap a silent no-op and the assertions below would pass
# for the wrong reason. A unique basename avoids the shared-/tmp race with a
# concurrent session.
def _sanctioned_out_json() -> Path:
    return Path(f"/tmp/swe-workbench-pr-review/{uuid.uuid4().hex}.json")


def test_preflight_trap_removes_out_json_on_null_field_abort():
    """author.login == null trips the L33-39 field-emptiness loop -> exit 1 ->
    the EXIT trap must remove $OUT_JSON (the script's own failed artifact)."""
    with tempfile.TemporaryDirectory() as stub_dir_str:
        stub_dir = Path(stub_dir_str)
        pr_json = (
            '{"state":"OPEN","number":1,"headRefName":"feature-x",'
            '"baseRefName":"main","headRefOid":"abc123","title":"t","body":"b",'
            '"author":{"login":null},"reviewDecision":null}'
        )
        _make_gh_dispatch_stub(stub_dir, pr_json=pr_json)
        out_json = _sanctioned_out_json()
        try:
            result = _run_preflight("1", out_json, stub_dir=stub_dir)
            assert result.returncode != 0, (
                f"Expected non-zero exit on null author.login\nstderr: {result.stderr!r}"
            )
            assert not out_json.exists(), (
                "the trap must remove $OUT_JSON when the script aborts after creating it — "
                "a caller invoking this via eval \"$(...)\" cannot do this cleanup itself, "
                "since eval discards the script's exit status"
            )
        finally:
            out_json.unlink(missing_ok=True)


def test_preflight_trap_leaves_out_json_on_success():
    """Fully valid PR JSON -> script exits 0 -> $OUT_JSON must remain (it is the
    deliverable callers read title/body/headRefName from)."""
    with tempfile.TemporaryDirectory() as stub_dir_str:
        stub_dir = Path(stub_dir_str)
        pr_json = (
            '{"state":"OPEN","number":1,"headRefName":"feature-x",'
            '"baseRefName":"main","headRefOid":"abc123","title":"t","body":"b",'
            '"author":{"login":"octocat"},"reviewDecision":null}'
        )
        _make_gh_dispatch_stub(stub_dir, pr_json=pr_json)
        out_json = _sanctioned_out_json()
        try:
            result = _run_preflight("1", out_json, stub_dir=stub_dir)
            assert result.returncode == 0, (
                f"Expected exit 0 on valid PR JSON\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
            assert out_json.exists(), (
                "the trap must NOT remove $OUT_JSON on a successful run — over-broad "
                "trap logic would delete the file callers rely on for title/body/headRefName"
            )
        finally:
            out_json.unlink(missing_ok=True)

