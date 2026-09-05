"""Ratchet tests for _CLEAN_ENV's credential-prompt guard.

See tests/README.md's `_CLEAN_ENV` section for the rationale: fixtures that fake
HOME have no credential helper, so a git operation reaching an unauthenticated
remote would otherwise block on an interactive prompt instead of failing fast.
"""

from __future__ import annotations

import http.server
import subprocess
import threading

from conftest import _CLEAN_ENV


def test_clean_env_disables_git_credential_prompts():
    assert _CLEAN_ENV["GIT_TERMINAL_PROMPT"] == "0"


class _UnauthorizedHandler(http.server.BaseHTTPRequestHandler):
    """Answers every request with 401, as a real auth-requiring git remote would."""

    def do_GET(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="git"')
        self.end_headers()

    def log_message(self, format, *args):
        pass


def test_git_fetch_fails_fast_on_unauthenticated_remote(tmp_path):
    """Proves GIT_TERMINAL_PROMPT=0 actually changes git's behavior, not just
    that the key is present: against a real 401-returning remote, with no
    credential helper visible (HOME faked, same as the fixtures this guards),
    git must fail immediately instead of blocking on a tty prompt."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _UnauthorizedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    try:
        port = server.server_address[1]
        result = subprocess.run(
            ["git", "ls-remote", f"http://127.0.0.1:{port}/repo.git"],
            capture_output=True,
            text=True,
            env={**_CLEAN_ENV, "HOME": str(fake_home)},
            timeout=10,
        )
        assert result.returncode != 0
        assert "terminal prompts disabled" in result.stderr
    finally:
        server.shutdown()
        thread.join(timeout=5)
