"""Runtime regression guard for hooks/hooks.json command strings (issue #557).

Every hooks.json command must resolve correctly when CLAUDE_PLUGIN_ROOT
contains a space, under a bash login shell. Unquoted `$CLAUDE_PLUGIN_ROOT/...`
word-splits under bash/sh (but not zsh) once the value contains a space,
silently killing the hook — for bash_guard.sh and secret_guard.py that means
a security control stops vetting tool calls with no error surfaced. Pinning
`bash -c` here (never `$SHELL`/`sh`) is load-bearing: a harness that shelled
out via zsh would report green against the pre-fix strings and guard nothing.
See docs/plugin-platform-decisions.md for background.
"""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
HOOKS_JSON = ROOT / "hooks" / "hooks.json"


def _hook_commands():
    """Return the deduplicated set of command strings from hooks.json, in
    first-seen order (workflow_resume_hint.sh appears identically 3x)."""
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    seen = []
    for matchers in data["hooks"].values():
        for entry in matchers:
            for hook in entry.get("hooks", []):
                cmd = hook["command"]
                if cmd not in seen:
                    seen.append(cmd)
    return seen


def _script_name(cmd):
    """Basename after the final '/', independent of the shape regex — both
    the pre-fix (unquoted) and fixed (quoted, interpreter-prefixed) forms
    end in '/hooks/<script>', so this works for either without assuming the
    fix is already in place (a pre-fix hooks.json must still build a usable
    fixture so the resolution failure surfaces as a real subprocess exit
    code, not a Python-side AttributeError from a regex that only matches
    the fixed shape)."""
    return cmd.rstrip().rsplit("/", 1)[-1]


def _script_interp(cmd):
    return "python3" if cmd.split(None, 1)[0] == "python3" else "bash"


def _stub_source(interp, name):
    if interp == "python3":
        return f'print("EXECUTED:{name}")\n'
    return f'echo "EXECUTED:{name}"\n'


@pytest.fixture
def fake_plugin_root(tmp_path):
    """A plugin root at a spaced path, with a stub for every hook script.

    Stubs (not the real scripts) are deliberate: the defect under test is
    command-string *resolution*, not hook behavior — that's covered by
    test_hooks.py, test_secret_guard.py, and test_workflow_resume_hook.py.
    """
    root = tmp_path / "with space" / "root"
    hooks_dir = root / "hooks"
    hooks_dir.mkdir(parents=True)
    for cmd in _hook_commands():
        name = _script_name(cmd)
        interp = _script_interp(cmd)
        stub = hooks_dir / name
        stub.write_text(_stub_source(interp, name), encoding="utf-8")
        stub.chmod(0o755)
    return root


def _run_command(cmd, plugin_root):
    return subprocess.run(
        ["bash", "-c", cmd],
        env={**dict(_CLEAN_ENV), "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize("cmd", _hook_commands())
class TestSpacedRootResolution:
    def test_resolves_with_spaced_root(self, cmd, fake_plugin_root):
        name = _script_name(cmd)
        result = _run_command(cmd, fake_plugin_root)
        assert result.returncode == 0, (
            f"command {cmd!r} failed against a spaced CLAUDE_PLUGIN_ROOT "
            f"(exit {result.returncode}): {result.stderr!r}"
        )
        assert result.stdout.strip() == f"EXECUTED:{name}"

    def test_execute_bit_independent(self, cmd, fake_plugin_root):
        """The interpreter prefix means a stub with its exec bit stripped
        must still run — resolution never depends on the shebang or +x."""
        name = _script_name(cmd)
        stub = fake_plugin_root / "hooks" / name
        stub.chmod(0o644)
        result = _run_command(cmd, fake_plugin_root)
        assert result.returncode == 0, (
            f"command {cmd!r} failed against a non-executable stub "
            f"(exit {result.returncode}): {result.stderr!r}"
        )
        assert result.stdout.strip() == f"EXECUTED:{name}"


def test_unquoted_form_word_splits_and_fails_with_127():
    """Literal, hardcoded proof of the underlying bug (issue #557) —
    independent of hooks.json's live content, so this regression proof
    holds even once every real command already passes the fixed shape.

    An unquoted `$CLAUDE_PLUGIN_ROOT` expansion word-splits under bash once
    the value contains a space: the first word ('/no') is treated as the
    command to execute, is not found, and bash exits 127 before ever
    reaching the intended script. This mirrors the empirical verification
    from the issue:

        bash, unquoted  $R/hooks/x.sh   -> ARG=[/no]  ARG=[such/dir/hooks/x.sh]
    """
    result = subprocess.run(
        ["bash", "-c", "$CLAUDE_PLUGIN_ROOT/hooks/bash_guard.sh"],
        env={**dict(_CLEAN_ENV), "CLAUDE_PLUGIN_ROOT": "/no such/dir"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 127, (
        f"expected the unquoted form to word-split and exit 127, got "
        f"{result.returncode}: {result.stderr!r}"
    )
    # The distinguishing signal isn't the exit code alone (a quoted-but-
    # missing script also exits 127) — it's *what* bash reports as missing:
    # the split-off first word, never the intended script path.
    assert "/no: No such file or directory" in result.stderr, (
        f"expected bash to report the split fragment '/no' as missing, got: {result.stderr!r}"
    )
    assert "bash_guard.sh" not in result.stderr


def test_quoted_form_survives_spaced_root():
    """Counterpart to the above: the fixed, quoted form must NOT word-split
    the same spaced value. Exit code is still 127 (the script doesn't exist
    on this scratch path) — the proof is that bash reports the FULL spaced
    path as missing, showing the value survived as one word, not a split
    fragment."""
    result = subprocess.run(
        ["bash", "-c", 'bash "${CLAUDE_PLUGIN_ROOT}"/hooks/bash_guard.sh'],
        env={**dict(_CLEAN_ENV), "CLAUDE_PLUGIN_ROOT": "/no such/dir"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "/no such/dir/hooks/bash_guard.sh" in result.stderr, (
        f"expected the full spaced path in bash's error, got: {result.stderr!r}"
    )


def test_secret_guard_uses_python3():
    cmds = [c for c in _hook_commands() if "secret_guard.py" in c]
    assert cmds, "secret_guard.py not found in hooks.json"
    for cmd in cmds:
        assert cmd.startswith("python3 "), f"expected python3 interpreter, got: {cmd!r}"


def test_sh_scripts_use_bash():
    cmds = [c for c in _hook_commands() if c.rstrip().endswith(".sh")]
    assert cmds, "no .sh hook commands found in hooks.json"
    for cmd in cmds:
        assert cmd.startswith("bash "), f"expected bash interpreter, got: {cmd!r}"


def test_handoff_guard_registered_after_secret_guard_for_mutating_tools():
    """The handoff guard must cover Bash|Edit|Write and sit after secret_guard.py
    so the secret gate vets content before ownership is evaluated."""
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    pre_tool_use = data["hooks"]["PreToolUse"]
    commands = [
        hook["command"]
        for entry in pre_tool_use
        for hook in entry.get("hooks", [])
    ]
    secret_index = next(i for i, cmd in enumerate(commands) if "secret_guard.py" in cmd)
    handoff_commands = [i for i, cmd in enumerate(commands) if "handoff_guard.py" in cmd]
    assert handoff_commands, "handoff_guard.py not registered in PreToolUse"
    assert all(i > secret_index for i in handoff_commands)
    matchers = [entry.get("matcher") for entry in pre_tool_use]
    assert "Bash|Edit|Write" in matchers, (
        f"expected a Bash|Edit|Write matcher for the handoff guard, got: {matchers!r}"
    )
    handoff_entry = next(entry for entry in pre_tool_use if "handoff_guard.py" in str(entry))
    assert handoff_entry["matcher"] == "Bash|Edit|Write"
