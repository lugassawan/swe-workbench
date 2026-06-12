"""Structural assertions for runtime/preflight-pr.sh (Fix A).

Mirrors tests/test_fetch_pr_script.py conventions.
Verifies that preflight-pr.sh:
  - exists and is executable (covered by test_runtime_scripts.py)
  - resolves its sibling fetch-pr.sh via dirname "$0" (never CLAUDE_PLUGIN_ROOT)
  - emits only safe scalars via printf %q (BASE, HEAD_SHA, AUTHOR_LOGIN, OWNER, REPO, STATE)
  - NEVER echoes title or body (free-text → eval-injection risk)
  - uses set -euo pipefail
"""

import re
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "runtime" / "preflight-pr.sh"

SAFE_SCALARS = ["BASE", "HEAD_SHA", "AUTHOR_LOGIN", "OWNER", "REPO", "STATE"]


def test_preflight_script_exists():
    """runtime/preflight-pr.sh must exist."""
    assert SCRIPT.exists(), "runtime/preflight-pr.sh must exist"


def test_preflight_uses_dirname_not_env_root():
    """preflight-pr.sh must resolve sibling scripts via dirname \"$0\", not CLAUDE_PLUGIN_ROOT.

    When cwd is an ephemeral PR worktree, CLAUDE_PLUGIN_ROOT may be unset and the git
    fallback would resolve to the worktree — fetch-pr.sh would not exist there.
    dirname \"$0\" always points to the directory containing preflight-pr.sh itself.
    """
    text = SCRIPT.read_text()
    assert 'dirname "$0"' in text or "$(dirname" in text, (
        "runtime/preflight-pr.sh must resolve its directory via dirname \"$0\" "
        "so sibling scripts (fetch-pr.sh) are found regardless of cwd or CLAUDE_PLUGIN_ROOT"
    )
    # Must NOT resolve via CLAUDE_PLUGIN_ROOT for the fetch-pr.sh call itself
    assert "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse" not in text, (
        "runtime/preflight-pr.sh must not use ${CLAUDE_PLUGIN_ROOT:-$(git rev-parse ...)} — "
        "use dirname \"$0\" instead so the script works in any worktree cwd"
    )


def test_preflight_calls_fetch_pr_sh():
    """preflight-pr.sh must delegate PR JSON fetching to sibling fetch-pr.sh."""
    text = SCRIPT.read_text()
    assert "fetch-pr.sh" in text, (
        "runtime/preflight-pr.sh must call sibling runtime/fetch-pr.sh to write the PR JSON — "
        "reuse the existing fetch+validation logic rather than duplicating inline gh calls"
    )


def test_preflight_emits_printf_q_for_scalars():
    """preflight-pr.sh must emit each safe scalar via printf '%q' to prevent word-splitting."""
    text = SCRIPT.read_text()
    assert "printf" in text and "%q" in text, (
        "runtime/preflight-pr.sh must use printf '%q' (or printf '%%q') to quote scalar output — "
        "unquoted values in eval \"$(...)\" are vulnerable to word-splitting and injection"
    )


def test_preflight_emits_all_safe_scalars():
    """preflight-pr.sh must emit all 6 safe scalars: BASE, HEAD_SHA, AUTHOR_LOGIN, OWNER, REPO, STATE."""
    text = SCRIPT.read_text()
    missing = [s for s in SAFE_SCALARS if s not in text]
    assert not missing, (
        f"runtime/preflight-pr.sh must emit all safe scalars; missing: {missing}. "
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
        "runtime/preflight-pr.sh must NOT echo/printf 'title' — "
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
        "runtime/preflight-pr.sh must NOT echo/printf 'body' — "
        "PR bodies are free-text and echoing them into eval \"$(...)\" enables code injection:\n"
        + "\n".join(body_echo_lines)
    )


def test_preflight_has_set_euo_pipefail():
    """preflight-pr.sh must start with set -euo pipefail for fail-fast error handling."""
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text, (
        "runtime/preflight-pr.sh must use 'set -euo pipefail' — "
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
        f"bash -n runtime/preflight-pr.sh failed:\n{result.stderr}"
    )

