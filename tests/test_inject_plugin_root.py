"""Tests for hooks/inject_plugin_root.sh — PreToolUse:Bash CLAUDE_PLUGIN_ROOT
injector (issue #530).

CLAUDE_PLUGIN_ROOT is empty in the Bash tool's own environment even though
it's present in the hook process's environment. This hook reads the
authoritative value from its own env and rewrites `tool_input.command` to
export it, ONLY for commands that reference the var and don't already assign
it. It must never emit `permissionDecision` (composability with
bash_guard.sh) and must never exit non-zero (fail-open).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

HOOK = Path(__file__).parent.parent / "hooks" / "inject_plugin_root.sh"
HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"
DOCTOR_CMD = Path(__file__).parent.parent / "commands" / "doctor.md"


@pytest.fixture(scope="module")
def hook_script():
    assert HOOK.exists(), f"missing {HOOK}"
    assert os.access(HOOK, os.X_OK), f"{HOOK} must be executable"
    return HOOK


def run_hook(script, cmd, *, plugin_root="/fake/root", extra_env=None):
    payload = json.dumps({"tool_input": {"command": cmd}})
    env = dict(_CLEAN_ENV)
    if plugin_root is None:
        env.pop("CLAUDE_PLUGIN_ROOT", None)
    else:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(script)], input=payload, text=True, capture_output=True, env=env,
    )


# ──────────────────────────────────────────────
# Wiring
# ──────────────────────────────────────────────


class TestWiring:
    def test_hook_script_exists_and_executable(self):
        assert HOOK.exists(), f"Missing hook script: {HOOK}"
        assert os.access(HOOK, os.X_OK), f"Hook script not executable: {HOOK}"

    def test_hooks_json_has_bash_entry(self):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "Bash"
        ]
        assert entries, "No PreToolUse Bash entries in hooks.json"
        assert any(
            "inject_plugin_root.sh" in h["command"]
            for e in entries
            for h in e["hooks"]
        ), f"No Bash entry references inject_plugin_root.sh; entries: {entries}"

    def test_bash_guard_entry_still_present(self):
        """The new entry must be additive — bash_guard.sh must remain wired."""
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "Bash"
        ]
        assert any(
            "bash_guard.sh" in h["command"]
            for e in entries
            for h in e["hooks"]
        ), "bash_guard.sh entry must remain wired alongside the injector"


# ──────────────────────────────────────────────
# Inject
# ──────────────────────────────────────────────


class TestInject:
    def test_injects_export_for_referencing_command(self, hook_script):
        cmd = 'bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert updated.startswith("export CLAUDE_PLUGIN_ROOT="), updated
        assert "/fake/root" in updated
        assert cmd in updated, "original command must be preserved verbatim"

    def test_injects_for_braced_reference(self, hook_script):
        cmd = 'bash "${CLAUDE_PLUGIN_ROOT}/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert updated.startswith("export CLAUDE_PLUGIN_ROOT=")
        assert cmd in updated

    def test_hook_event_name_is_pretooluse(self, hook_script):
        cmd = 'bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        out = json.loads(result.stdout)
        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


# ──────────────────────────────────────────────
# Pass-through / idempotency / empty-env
# ──────────────────────────────────────────────


class TestPassThrough:
    def test_no_reference_passes_through(self, hook_script):
        result = run_hook(hook_script, "ls -la", plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_already_assigned_is_idempotent(self, hook_script):
        cmd = 'CLAUDE_PLUGIN_ROOT=/already/set; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_already_exported_is_idempotent(self, hook_script):
        cmd = 'export CLAUDE_PLUGIN_ROOT=/already/set; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_empty_plugin_root_env_passes_through(self, hook_script):
        cmd = 'bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root=None)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_blank_plugin_root_env_passes_through(self, hook_script):
        cmd = 'bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="")
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ──────────────────────────────────────────────
# Word-boundary gate (regression: bare substring match previously
# mis-fired on unrelated identifiers containing CLAUDE_PLUGIN_ROOT)
# ──────────────────────────────────────────────


class TestWordBoundaryGate:
    def test_unrelated_var_assignment_does_not_suppress_injection(self, hook_script):
        """MY_CLAUDE_PLUGIN_ROOT= must NOT be mistaken for a real assignment
        of $CLAUDE_PLUGIN_ROOT — the real var still needs injection."""
        cmd = 'MY_CLAUDE_PLUGIN_ROOT=/other/value; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert updated.startswith("export CLAUDE_PLUGIN_ROOT=")
        assert "/fake/root" in updated

    def test_unrelated_var_reference_does_not_trigger_injection(self, hook_script):
        """$CLAUDE_PLUGIN_ROOTS (a different, longer var name) must NOT be
        mistaken for a reference to $CLAUDE_PLUGIN_ROOT."""
        cmd = 'echo "$CLAUDE_PLUGIN_ROOTS"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_real_assignment_still_suppresses_injection(self, hook_script):
        """A genuine assignment (word-boundary correct) must still be
        idempotent — no regression from the boundary tightening."""
        cmd = 'CLAUDE_PLUGIN_ROOT=/already/set; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ──────────────────────────────────────────────
# Assignment-position anchoring (regression: a bare word-boundary check
# still mis-fired on CLAUDE_PLUGIN_ROOT= appearing inside a URL query
# string or --data payload, not a real shell assignment — reviewer finding)
# ──────────────────────────────────────────────


class TestAssignmentPositionAnchoring:
    def test_url_query_string_does_not_suppress_injection(self, hook_script):
        """CLAUDE_PLUGIN_ROOT= inside a URL query string is not a real
        assignment — the real $CLAUDE_PLUGIN_ROOT reference elsewhere in
        the same command must still get injected."""
        cmd = 'curl "https://example.com/?CLAUDE_PLUGIN_ROOT=x"; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert updated.startswith("export CLAUDE_PLUGIN_ROOT=")
        assert "/fake/root" in updated

    def test_data_payload_does_not_suppress_injection(self, hook_script):
        cmd = 'curl --data "CLAUDE_PLUGIN_ROOT=x" example.com && bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert updated.startswith("export CLAUDE_PLUGIN_ROOT=")

    def test_assignment_after_semicolon_still_suppresses(self, hook_script):
        cmd = 'echo hi; CLAUDE_PLUGIN_ROOT=/already/set; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_assignment_after_and_operator_still_suppresses(self, hook_script):
        cmd = 'echo hi && CLAUDE_PLUGIN_ROOT=/already/set; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_export_assignment_after_semicolon_still_suppresses(self, hook_script):
        cmd = 'echo hi; export CLAUDE_PLUGIN_ROOT=/already/set; bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ──────────────────────────────────────────────
# Fail-open on malformed input
# ──────────────────────────────────────────────


class TestFailOpen:
    @pytest.mark.parametrize("payload", [
        "",
        "not json at all",
        "{",
        '{"tool_input": {}}',
        '{"tool_input": {"command": null}}',
        "null",
    ])
    def test_malformed_or_empty_input_never_blocks(self, hook_script, payload):
        env = dict(_CLEAN_ENV)
        env["CLAUDE_PLUGIN_ROOT"] = "/fake/root"
        result = subprocess.run(
            [str(hook_script)], input=payload, text=True, capture_output=True, env=env,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for payload {payload!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )


# ──────────────────────────────────────────────
# Security: permission-neutral, guard-token preservation, JSON-escaping
# ──────────────────────────────────────────────


class TestSecurity:
    def test_never_emits_permission_decision(self, hook_script):
        cmd = 'bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert "permissionDecision" not in result.stdout, (
            "Injector must never emit permissionDecision — that would bypass "
            "bash_guard.sh's exit-2 block"
        )

    def test_destructive_tokens_preserved_verbatim_for_guard(self, hook_script):
        """A destructive command that also references the var must still
        carry the rm/git tokens unchanged so bash_guard.sh (which reads the
        ORIGINAL tool_input.command, not this hook's output) still detects
        them."""
        cmd = 'rm -rf "$CLAUDE_PLUGIN_ROOT/tmp" && echo done'
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert 'rm -rf "$CLAUDE_PLUGIN_ROOT/tmp" && echo done' in updated

    @pytest.mark.parametrize("cmd", [
        'echo "quote\\"s" && echo "$CLAUDE_PLUGIN_ROOT"',
        'echo \'$CLAUDE_PLUGIN_ROOT\' && echo "$CLAUDE_PLUGIN_ROOT/x"',
        'echo "line one\nline two $CLAUDE_PLUGIN_ROOT"',
        'echo "$CLAUDE_PLUGIN_ROOT" "$(pwd)"',
    ])
    def test_json_escaping_round_trips(self, hook_script, cmd):
        result = run_hook(hook_script, cmd, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)  # must parse as valid JSON
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert cmd in updated

    def test_plugin_root_value_shell_quoted(self, hook_script):
        """A plugin root path containing a space or quote must be safely
        shell-quoted in the export prefix."""
        cmd = 'bash "$CLAUDE_PLUGIN_ROOT/runtime/doctor.sh"'
        result = run_hook(hook_script, cmd, plugin_root="/fake root/with'quote")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        updated = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert updated.startswith("export CLAUDE_PLUGIN_ROOT=")

    def test_bash_guard_still_blocks_original_stdin_when_both_hooks_wired(self, hook_script):
        """Chained-hooks integration: both PreToolUse:Bash entries receive
        the SAME original tool_input independently (Claude Code does not
        pipe one hook's updatedInput into the next hook's stdin). Feed a
        destructive command that also references CLAUDE_PLUGIN_ROOT through
        BOTH scripts and confirm bash_guard.sh still blocks on the original,
        unmodified stdin regardless of what the injector produces."""
        guard = Path(__file__).parent.parent / "hooks" / "bash_guard.sh"
        cmd = 'rm -rf ~ "$CLAUDE_PLUGIN_ROOT/tmp"'
        payload = json.dumps({"tool_input": {"command": cmd}})
        env = dict(_CLEAN_ENV)
        env["CLAUDE_PLUGIN_ROOT"] = "/fake/root"

        guard_result = subprocess.run(
            [str(guard)], input=payload, text=True, capture_output=True, env=env,
        )
        injector_result = subprocess.run(
            [str(hook_script)], input=payload, text=True, capture_output=True, env=env,
        )

        assert guard_result.returncode == 2, guard_result.stderr
        assert "BLOCKED" in guard_result.stderr
        assert injector_result.returncode == 0
        assert "permissionDecision" not in injector_result.stdout


# ──────────────────────────────────────────────
# doctor.md guard (static)
# ──────────────────────────────────────────────


class TestDoctorGuard:
    def test_doctor_has_hard_fail_guard(self):
        text = DOCTOR_CMD.read_text()
        assert '[ -n "$_RT" ]' in text, (
            "doctor.md must contain the hard-fail guard checking $_RT"
        )
        assert '$_RT/runtime/doctor.sh' in text, (
            "doctor.md must invoke doctor.sh via $_RT after the guard"
        )
