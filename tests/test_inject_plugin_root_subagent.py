"""Tests for hooks/inject_plugin_root_subagent.sh — SubagentStart hook that
hands a dispatched subagent the resolved $CLAUDE_PLUGIN_ROOT as a literal path.

$CLAUDE_PLUGIN_ROOT does not reliably resolve as a live shell variable inside
a subagent's own Bash tool calls (confirmed empirically — see
docs/principles-languages-as-rules-design.md). This hook fires at SubagentStart, in the
orchestrator's own environment (where the var IS reliably set), and injects
the resolved value via additionalContext with an explicit substitution
instruction. Fail-open: never blocks dispatch, emits nothing if
$CLAUDE_PLUGIN_ROOT is unset in its own environment too.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

HOOK = Path(__file__).parent.parent / "hooks" / "inject_plugin_root_subagent.sh"
HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"


@pytest.fixture(scope="module")
def hook_script():
    assert HOOK.exists(), f"missing {HOOK}"
    assert os.access(HOOK, os.X_OK), f"{HOOK} must be executable"
    return HOOK


def run_hook(script, *, plugin_root="/fake/root", payload=None):
    body = json.dumps(payload if payload is not None else {"agent_type": "swe-workbench:reviewer"})
    env = dict(_CLEAN_ENV)
    if plugin_root is None:
        env.pop("CLAUDE_PLUGIN_ROOT", None)
    else:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    return subprocess.run(
        [str(script)], input=body, text=True, capture_output=True, env=env,
    )


# ──────────────────────────────────────────────
# Wiring
# ──────────────────────────────────────────────


class TestWiring:
    def test_hook_script_exists_and_executable(self):
        assert HOOK.exists(), f"Missing hook script: {HOOK}"
        assert os.access(HOOK, os.X_OK), f"Hook script not executable: {HOOK}"

    def test_hooks_json_has_subagent_start_entry(self):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = data["hooks"].get("SubagentStart", [])
        assert entries, "No SubagentStart entries in hooks.json"
        assert any(
            "inject_plugin_root_subagent.sh" in h["command"]
            for e in entries
            for h in e["hooks"]
        ), f"No SubagentStart entry references inject_plugin_root_subagent.sh; entries: {entries}"

    def test_matcher_scopes_to_swe_workbench_agents(self):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [
            e for e in data["hooks"]["SubagentStart"]
            if any("inject_plugin_root_subagent.sh" in h["command"] for h in e["hooks"])
        ]
        assert entries, "entry not found"
        assert entries[0]["matcher"] == "^swe-workbench:.*$"


# ──────────────────────────────────────────────
# Inject
# ──────────────────────────────────────────────


class TestInject:
    def test_injects_resolved_path(self, hook_script):
        result = run_hook(hook_script, plugin_root="/fake/root")
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "/fake/root" in ctx
        assert "$CLAUDE_PLUGIN_ROOT" in ctx  # names the var it's replacing

    def test_hook_event_name_is_subagentstart(self, hook_script):
        result = run_hook(hook_script, plugin_root="/fake/root")
        out = json.loads(result.stdout)
        assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart"

    def test_example_cat_command_uses_literal_path_not_var(self, hook_script):
        """The worked example must show the resolved path substituted in, not
        a bare $CLAUDE_PLUGIN_ROOT reference the subagent would just re-fail on."""
        result = run_hook(hook_script, plugin_root="/fake/root")
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert '/fake/root/rules/' in ctx


# ──────────────────────────────────────────────
# Fail-open
# ──────────────────────────────────────────────


class TestFailOpen:
    def test_empty_plugin_root_emits_nothing(self, hook_script):
        result = run_hook(hook_script, plugin_root=None)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_malformed_stdin_still_exits_zero(self, hook_script):
        env = dict(_CLEAN_ENV)
        env["CLAUDE_PLUGIN_ROOT"] = "/fake/root"
        result = subprocess.run(
            [str(hook_script)], input="not json", text=True, capture_output=True, env=env,
        )
        assert result.returncode == 0
