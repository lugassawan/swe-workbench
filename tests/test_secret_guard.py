"""Tests for hooks/secret_guard.py — PreToolUse Write/Edit secret-detection hook.

Each test drives hooks/secret_guard.py via subprocess (shebang, not python3
directly), mirroring how Claude Code calls the hook.

Exit code 2 + "BLOCKED" in stderr → secret detected, operation blocked.
Exit code 0, empty stderr             → allowed.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "hooks" / "secret_guard.py"

# ── Fixture tokens (shaped like real secrets but not real credentials) ──
# These are test fixtures, not real credentials.
_FAKE_GHP = "ghp_" + "A" * 36                              # nosecret
_FAKE_PAT = "github_pat_" + "B" * 22 + "_" + "C" * 59     # nosecret
_FAKE_AKIA = "AKIA" + "D" * 16                              # nosecret
_FAKE_AWS_SECRET = "E" * 40                                  # nosecret
_FAKE_API_KEY_VAL = "F" * 20                                 # nosecret
_FAKE_SECRET_VAL = "G" * 12                                  # nosecret
_FAKE_PEM_RSA       = "-----BEGIN RSA PRIVATE KEY-----"      # nosecret
_FAKE_PEM_PKCS8     = "-----BEGIN PRIVATE KEY-----"          # nosecret
_FAKE_PEM_ENCRYPTED = "-----BEGIN ENCRYPTED PRIVATE KEY-----"  # nosecret
_FAKE_PEM_SSH2      = "-----BEGIN SSH2 ENCRYPTED PRIVATE KEY-----"  # nosecret


def run_guard(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=dict(_CLEAN_ENV),
    )


def write_payload(content: str, path: str = "/tmp/test.py") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def edit_payload(new_string: str, old_string: str = "", path: str = "/tmp/test.py") -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": path,
            "old_string": old_string,
            "new_string": new_string,
        },
    }


# ──────────────────────────────────────────────
# Unit 1: Plumbing + fail-open
# ──────────────────────────────────────────────

class TestPlumbingAndFailOpen:
    def test_script_exists_and_is_executable(self):
        assert SCRIPT.exists(), f"missing {SCRIPT}"
        assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"

    def test_malformed_stdin_exits_0(self):
        result = subprocess.run(
            [str(SCRIPT)], input="not-json", text=True, capture_output=True,
            env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 0
        assert result.stderr == ""

    def test_missing_tool_name_exits_0(self):
        result = run_guard({"tool_input": {"content": "hello"}})
        assert result.returncode == 0

    def test_missing_tool_input_exits_0(self):
        result = run_guard({"tool_name": "Write"})
        assert result.returncode == 0

    def test_non_write_edit_tool_exits_0(self):
        result = run_guard({"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
        assert result.returncode == 0

    def test_benign_write_content_exits_0(self):
        result = run_guard(write_payload("x = 1\nprint(x)\n"))
        assert result.returncode == 0
        assert result.stderr == ""


# ──────────────────────────────────────────────
# Unit 2: HIGH-confidence patterns
# ──────────────────────────────────────────────

class TestHighPatterns:
    @pytest.mark.parametrize("content,label", [
        (f'token = "{_FAKE_GHP}"', "github-pat ghp_"),
        (f'token = "{_FAKE_PAT}"', "github-fine-grained-pat"),
        (f'key_id = "{_FAKE_AKIA}"', "aws-access-key-id"),
        (_FAKE_PEM_RSA, "private-key-pem rsa"),
        (_FAKE_PEM_PKCS8, "private-key-pem bare pkcs8"),
        (_FAKE_PEM_ENCRYPTED, "private-key-pem encrypted"),
        (_FAKE_PEM_SSH2, "private-key-pem ssh2 encrypted"),
    ])
    def test_blocked(self, content, label):
        result = run_guard(write_payload(content))
        assert result.returncode == 2, f"Expected BLOCKED for {label}: {result.stderr!r}"
        assert "BLOCKED" in result.stderr

    def test_blocked_message_includes_line_number(self):
        content = f"\n\ntoken = '{_FAKE_GHP}'"
        result = run_guard(write_payload(content))
        assert result.returncode == 2
        assert "line 3" in result.stderr

    def test_blocked_message_includes_pattern_name(self):
        result = run_guard(write_payload(f'x = "{_FAKE_AKIA}"'))
        assert "aws-access-key-id" in result.stderr


# ──────────────────────────────────────────────
# Unit 3: NEEDS-CONTEXT patterns
# ──────────────────────────────────────────────

class TestNeedsContextPatterns:
    @pytest.mark.parametrize("content,label", [
        (f'API_KEY = "{_FAKE_API_KEY_VAL}"', "generic-api-key assignment"),
        (f'SECRET = "{_FAKE_SECRET_VAL}"', "generic-secret SECRET"),
        (f'PASSWORD = "{_FAKE_SECRET_VAL}"', "generic-secret PASSWORD"),
        (f'TOKEN = "{_FAKE_SECRET_VAL}"', "generic-secret TOKEN"),
        (f'aws_secret_access_key = "{_FAKE_AWS_SECRET}"', "aws-secret-access-key"),
        (f'API_KEY={_FAKE_API_KEY_VAL}', "dotenv-api-key"),
        (f'SECRET={_FAKE_SECRET_VAL}', "dotenv-secret"),
        (f'PASSWD={_FAKE_SECRET_VAL}', "dotenv-passwd"),
        # getenv as substring should NOT suppress detection (word-boundary fix)
        (f'SECRET = "{_FAKE_SECRET_VAL}"  # see getenv_config.py', "getenv substring in comment"),
    ])
    def test_blocked(self, content, label):
        result = run_guard(write_payload(content))
        assert result.returncode == 2, f"Expected BLOCKED for {label!r}: {result.stderr!r}"
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("content,label", [
        ('SECRET = os.environ["SECRET"]', "env reference - os.environ"),
        ('API_KEY = os.getenv("API_KEY")', "env reference - os.getenv"),
        ('TOKEN = process.env.TOKEN', "env reference - process.env"),
        ('PASSWORD = ENV["PASSWORD"]', "env reference - ENV[]"),
        ('SECRET=os.environ["SECRET"]', "dotenv-style env reference"),
        ('TOKEN=process.env.TOKEN', "dotenv process.env"),
        # Boolean / short values must not be blocked (dotenv flags)
        ('TOKEN=true', "dotenv boolean true"),
        ('TOKEN=false', "dotenv boolean false"),
        ('SECRET=1', "dotenv single char"),
        ('PASSWORD=no', "dotenv short value"),
    ])
    def test_allowed_env_reference(self, content, label):
        result = run_guard(write_payload(content))
        assert result.returncode == 0, f"Expected ALLOWED for {label!r}: {result.stderr!r}"


# ──────────────────────────────────────────────
# Unit 4: Per-line # nosecret suppression
# ──────────────────────────────────────────────

class TestNosecretSuppression:
    def test_high_tier_nosecret_does_not_suppress(self):
        """ghp_ token + # nosecret must still be BLOCKED — HIGH-tier is un-suppressible."""
        content = f'token = "{_FAKE_GHP}"  # nosecret'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 2, f"Expected BLOCKED for HIGH-tier + nosecret: {result.stderr!r}"
        assert "BLOCKED" in result.stderr

    def test_high_tier_akia_nosecret_does_not_suppress(self):
        """AKIA token + # nosecret must still be BLOCKED — HIGH-tier is un-suppressible."""
        content = f'{_FAKE_AKIA}  # nosecret'
        result = run_guard(write_payload(content))
        assert result.returncode == 2

    def test_high_tier_pem_nosecret_does_not_suppress(self):
        """PEM header + # nosecret must still be BLOCKED — HIGH-tier is un-suppressible."""
        content = f'{_FAKE_PEM_RSA}  # nosecret'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_high_tier_nosecret_no_space_does_not_suppress(self):
        """#nosecret (no space) on HIGH-tier still blocks."""
        content = f'{_FAKE_AKIA}  #nosecret'
        result = run_guard(write_payload(content))
        assert result.returncode == 2

    def test_needs_context_nosecret_stays_allowed(self):
        """NEEDS-CONTEXT match with # nosecret remains allowed (regression guard)."""
        content = f'TOKEN = "{_FAKE_SECRET_VAL}"  # nosecret'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 0, f"Expected ALLOWED for NEEDS-CONTEXT + nosecret: {result.stderr!r}"

    def test_secret_on_adjacent_line_still_blocked(self):
        content = f'x = 1  # nosecret\nTOKEN = "{_FAKE_GHP}"\n'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 2

    def test_nosecrets_plural_does_not_suppress(self):
        content = f'TOKEN = "{_FAKE_GHP}"  # nosecrets stored here'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 2

    def test_nosecret_hint_absent_for_high_tier(self):
        """Blocked HIGH-tier error must NOT advertise # nosecret (it won't work)."""
        content = f'token = "{_FAKE_GHP}"'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 2
        assert "nosecret" not in result.stderr

    def test_nosecret_hint_present_for_needs_context_block(self):
        """Blocked NEEDS-CONTEXT error SHOULD advertise # nosecret as a valid escape."""
        content = f'TOKEN = "{_FAKE_SECRET_VAL}"'  # nosecret
        result = run_guard(write_payload(content))
        assert result.returncode == 2
        assert "nosecret" in result.stderr


# ──────────────────────────────────────────────
# Unit 5: Filename allowlist
# ──────────────────────────────────────────────

class TestFilenameAllowlist:
    def test_gitignore_allowed(self):
        content = f'TOKEN = "{_FAKE_GHP}"'
        result = run_guard(write_payload(content, path="/repo/.gitignore"))
        assert result.returncode == 0

    def test_test_corpus_allowed(self):
        content = f'_FAKE_GHP = "{_FAKE_GHP}"'  # nosecret
        corpus_path = str(SCRIPT.parent.parent / "tests" / "test_secret_guard.py")
        result = run_guard(write_payload(content, path=corpus_path))
        assert result.returncode == 0

    def test_arbitrary_test_file_not_in_allowlist(self):
        content = f'token = "{_FAKE_GHP}"'  # nosecret
        result = run_guard(write_payload(content, path="/project/tests/other_test.py"))
        assert result.returncode == 2

    def test_claude_plugin_root_env_redirects_allowlist(self, tmp_path):
        """With CLAUDE_PLUGIN_ROOT set, allowlist resolves test_secret_guard.py from that root."""
        (tmp_path / "tests").mkdir()
        corpus = tmp_path / "tests" / "test_secret_guard.py"
        corpus.touch()
        content = f'_FAKE_GHP = "{_FAKE_GHP}"'  # nosecret
        result = subprocess.run(
            [str(SCRIPT)],
            input=json.dumps(write_payload(content, path=str(corpus))),
            text=True,
            capture_output=True,
            env={**dict(_CLEAN_ENV), "CLAUDE_PLUGIN_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0, f"Expected ALLOWED via CLAUDE_PLUGIN_ROOT: {result.stderr!r}"


# ──────────────────────────────────────────────
# Unit 6: Edit routing
# ──────────────────────────────────────────────

class TestEditRouting:
    def test_secret_in_new_string_blocked(self):
        result = run_guard(edit_payload(
            new_string=f'token = "{_FAKE_GHP}"',
            old_string="token = old_value",
        ))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_secret_only_in_old_string_allowed(self):
        result = run_guard(edit_payload(
            new_string="token = os.environ['TOKEN']",
            old_string=f'token = "{_FAKE_GHP}"',
        ))
        assert result.returncode == 0

    def test_edit_benign_both_strings_allowed(self):
        result = run_guard(edit_payload(
            new_string="x = 2",
            old_string="x = 1",
        ))
        assert result.returncode == 0


# ──────────────────────────────────────────────
# Unit 7: Wiring — hooks.json has Write|Edit entry
# ──────────────────────────────────────────────

class TestHooksJsonWiring:
    HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"

    def test_write_edit_entry_present(self):
        data = json.loads(self.HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "Write|Edit"
        ]
        assert entries, "Write|Edit PreToolUse entry missing from hooks.json"

    def test_secret_guard_referenced(self):
        data = json.loads(self.HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "Write|Edit"
        ]
        assert any(
            "secret_guard.py" in e["hooks"][0]["command"] for e in entries
        ), f"No entry references secret_guard.py; entries: {entries}"

    def test_hook_script_exists_and_executable(self):
        script = Path(__file__).parent.parent / "hooks" / "secret_guard.py"
        assert script.exists(), f"Missing: {script}"
        assert os.access(script, os.X_OK), f"Not executable: {script}"
