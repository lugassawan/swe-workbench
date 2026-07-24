"""Tests for hooks/inject_catalog.sh — SessionStart hook that injects the
principle/language rule catalog as additionalContext for the main thread.

Rule bodies live under rules/*.md as plain files, not skills, so there's no
Skill-autoload mechanism to surface them to the orchestrator. Subagents get
the catalog via the embedded @./shared/{principles,languages}.md includes in
their own prompts; this hook is the main thread's only delivery path.
Fail-open: never blocks startup, emits nothing if $CLAUDE_PLUGIN_ROOT is
unset or the catalog files are missing/unreadable.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

HOOK = Path(__file__).parent.parent / "hooks" / "inject_catalog.sh"
HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"
REAL_PRINCIPLES = Path(__file__).parent.parent / "agents" / "shared" / "principles.md"
REAL_LANGUAGES = Path(__file__).parent.parent / "agents" / "shared" / "languages.md"


@pytest.fixture(scope="module")
def hook_script():
    assert HOOK.exists(), f"missing {HOOK}"
    assert os.access(HOOK, os.X_OK), f"{HOOK} must be executable"
    return HOOK


def run_hook(script, *, plugin_root, payload=None):
    body = json.dumps(payload if payload is not None else {"source": "startup"})
    env = dict(_CLEAN_ENV)
    if plugin_root is None:
        env.pop("CLAUDE_PLUGIN_ROOT", None)
    else:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    return subprocess.run(
        [str(script)], input=body, text=True, capture_output=True, env=env,
    )


def _make_plugin_root(tmp_path, *, principles="- `principle-x` — x rule → `rules/principle-x.md`\n",
                       languages="- `language-x` — x rule → `rules/language-x.md`\n"):
    shared = tmp_path / "agents" / "shared"
    shared.mkdir(parents=True)
    (shared / "principles.md").write_text(principles, encoding="utf-8")
    (shared / "languages.md").write_text(languages, encoding="utf-8")
    return tmp_path


# ──────────────────────────────────────────────
# Wiring
# ──────────────────────────────────────────────


class TestWiring:
    def test_hook_script_exists_and_executable(self):
        assert HOOK.exists(), f"Missing hook script: {HOOK}"
        assert os.access(HOOK, os.X_OK), f"Hook script not executable: {HOOK}"

    def test_hooks_json_wired_on_all_three_matchers(self):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = data["hooks"]["SessionStart"]
        for matcher in ("startup", "resume", "compact"):
            matched = [e for e in entries if e.get("matcher") == matcher]
            assert matched, f"No SessionStart entry for matcher {matcher!r}"
            assert any(
                "inject_catalog.sh" in h["command"]
                for e in matched
                for h in e["hooks"]
            ), f"inject_catalog.sh not wired for matcher {matcher!r}"

    def test_workflow_resume_hint_still_wired(self):
        """The new entry must be additive — workflow_resume_hint.sh must remain wired."""
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = data["hooks"]["SessionStart"]
        for matcher in ("startup", "resume", "compact"):
            matched = [e for e in entries if e.get("matcher") == matcher]
            assert any(
                "workflow_resume_hint.sh" in h["command"]
                for e in matched
                for h in e["hooks"]
            ), f"workflow_resume_hint.sh missing for matcher {matcher!r}"


# ──────────────────────────────────────────────
# Inject
# ──────────────────────────────────────────────


class TestInject:
    def test_injects_catalog_content(self, hook_script, tmp_path):
        root = _make_plugin_root(tmp_path)
        result = run_hook(hook_script, plugin_root=str(root))
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "principle-x" in ctx
        assert "language-x" in ctx

    def test_hook_event_name_is_sessionstart(self, hook_script, tmp_path):
        root = _make_plugin_root(tmp_path)
        result = run_hook(hook_script, plugin_root=str(root))
        out = json.loads(result.stdout)
        assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_preamble_names_cat_loading_pattern(self, hook_script, tmp_path):
        """Agents must be told how to load a rule body, not just what exists."""
        root = _make_plugin_root(tmp_path)
        result = run_hook(hook_script, plugin_root=str(root))
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "cat" in ctx
        assert "rules/<name>.md" in ctx

    def test_real_catalog_injects_without_error(self, hook_script):
        """Smoke test against the real repo catalog files, not a synthetic fixture."""
        plugin_root = str(Path(__file__).parent.parent)
        result = run_hook(hook_script, plugin_root=plugin_root)
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "principle-tdd" in ctx
        assert "language-python" in ctx


# ──────────────────────────────────────────────
# Fail-open
# ──────────────────────────────────────────────


class TestFailOpen:
    def test_missing_plugin_root_emits_nothing(self, hook_script):
        result = run_hook(hook_script, plugin_root=None)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_missing_principles_file_emits_nothing(self, hook_script, tmp_path):
        shared = tmp_path / "agents" / "shared"
        shared.mkdir(parents=True)
        (shared / "languages.md").write_text("- `language-x` — x\n", encoding="utf-8")
        # principles.md deliberately absent
        result = run_hook(hook_script, plugin_root=str(tmp_path))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_missing_languages_file_emits_nothing(self, hook_script, tmp_path):
        shared = tmp_path / "agents" / "shared"
        shared.mkdir(parents=True)
        (shared / "principles.md").write_text("- `principle-x` — x\n", encoding="utf-8")
        # languages.md deliberately absent
        result = run_hook(hook_script, plugin_root=str(tmp_path))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_empty_catalog_files_emit_nothing(self, hook_script, tmp_path):
        """Both files present but empty — nothing meaningful to inject."""
        root = _make_plugin_root(tmp_path, principles="", languages="")
        result = run_hook(hook_script, plugin_root=str(root))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_malformed_stdin_still_exits_zero(self, hook_script, tmp_path):
        root = _make_plugin_root(tmp_path)
        env = dict(_CLEAN_ENV)
        env["CLAUDE_PLUGIN_ROOT"] = str(root)
        result = subprocess.run(
            [str(hook_script)], input="not json", text=True, capture_output=True, env=env,
        )
        assert result.returncode == 0
