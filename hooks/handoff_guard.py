#!/usr/bin/env python3
"""PreToolUse hook: enforce Claude ownership of the current handoff lease.

The hook receives Claude Code hook JSON on stdin. It mediates mutating tools
through the harness-neutral ``swe-workbench-handoff guard`` decision. Missing
runtime installation fails open to avoid a plugin-installation deadlock;
corrupt or unreadable handoff state fails closed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_MUTATING_TOOLS = frozenset({"Bash", "Edit", "Write"})
_RUNTIME_NAME = "swe-workbench-handoff"
_TIMEOUT_SECONDS = 10
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_CHECKED_PIPE = r"\| swe-workbench-result-check swb\.handoff/1"
_CLAUDE_SESSION_ARGUMENT = re.escape(
    '"${CLAUDE_CODE_SESSION_ID:?missing CLAUDE_CODE_SESSION_ID}"'
)
_CLAUDE_SESSION_ENV_ARGUMENT = re.escape("CLAUDE_CODE_SESSION_ID")
_ABANDON_COMMAND = re.compile(
    rf'^swe-workbench-handoff abandon "?{_UUID}"? --source-stopped {_CHECKED_PIPE}$'
)
_CONTROL_COMMANDS = (
    re.compile(
        rf'^swe-workbench-handoff resume "?{_UUID}"? --as "?claude"? '
        rf'--receiver-session {_CLAUDE_SESSION_ARGUMENT} '
        rf'(?:--acknowledge-degraded )?{_CHECKED_PIPE}$'
    ),
    # Literal-argument form: lets a harness's static command guard prove the pipeline inert
    # (mirrors bin/swe-workbench-handoff's resolve_session_ref allowlist).
    re.compile(
        rf'^swe-workbench-handoff resume "?{_UUID}"? --as "?claude"? '
        rf'--receiver-session-env {_CLAUDE_SESSION_ENV_ARGUMENT} '
        rf'(?:--acknowledge-degraded )?{_CHECKED_PIPE}$'
    ),
    re.compile(
        rf'^swe-workbench-handoff recover --from "?pi"? --source-stopped {_CHECKED_PIPE}$'
    ),
    re.compile(rf"^swe-workbench-handoff list {_CHECKED_PIPE}$"),
    _ABANDON_COMMAND,
)


def _load_payload() -> dict[str, object] | None:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _runtime_path() -> Path | None:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        candidate = Path(plugin_root) / "bin" / _RUNTIME_NAME
        if candidate.is_file():
            return candidate
    executable = shutil.which(_RUNTIME_NAME)
    return Path(executable) if executable else None


def _working_directory(payload: dict[str, object]) -> Path:
    """Resolve the directory the guarded tool call will run in.

    Falls back to ``Path.cwd()`` when the PreToolUse payload carries no ``cwd`` — a
    Claude-Code-specific payload artifact with no Pi counterpart (Pi reads ``ctx.cwd``
    directly). Do not "fix" this asymmetry by adding a fallback on the Pi side.
    """
    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        candidate = Path(cwd)
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def _safe_terminal_text(value: object, *, absolute_path: bool = False) -> str | None:
    """Validate untrusted runtime text before it reaches stderr."""
    if (
        isinstance(value, str)
        and (not absolute_path or value.startswith("/"))
        and len(value) <= 4096
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    ):
        return value
    return None


def _safe_worktree_root(value: object) -> str | None:
    return _safe_terminal_text(value, absolute_path=True)


def _safe_receiver_command(value: object) -> str | None:
    return _safe_terminal_text(value)


def _control_command(payload: dict[str, object]) -> re.Pattern[str] | None:
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    normalized = " ".join(command.replace("\\\n", " ").split())
    return next((pattern for pattern in _CONTROL_COMMANDS if pattern.fullmatch(normalized)), None)


def _block(message: str) -> None:
    print(f"BLOCKED: {message}", file=sys.stderr)
    raise SystemExit(2)


def _with_worktree_clause(message: str, worktree_root: str | None) -> str:
    return f"{message} (worktree: {worktree_root})" if worktree_root else message


def _decision(output: str) -> tuple[str, str, str | None, str | None, str | None, str | None] | None:
    try:
        envelope = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    decision = data.get("decision")
    reason = data.get("reason")
    if decision not in {"allow", "deny"} or not isinstance(reason, str):
        return None
    checkpoint_id = data.get("checkpoint_id")
    target_harness = data.get("target_harness")
    safe_checkpoint_id = (
        checkpoint_id
        if isinstance(checkpoint_id, str) and re.fullmatch(_UUID, checkpoint_id)
        else None
    )
    safe_target_harness = (
        target_harness
        if isinstance(target_harness, str) and target_harness in {"claude", "pi"}
        else None
    )
    safe_worktree_root = _safe_worktree_root(data.get("worktree_root"))
    safe_receiver_command = _safe_receiver_command(data.get("receiver_command"))
    return decision, reason, safe_checkpoint_id, safe_target_harness, safe_worktree_root, safe_receiver_command


def main() -> None:
    payload = _load_payload()
    if payload is None or payload.get("tool_name") not in _MUTATING_TOOLS:
        return
    control_command = _control_command(payload)
    abandon_command = control_command is _ABANDON_COMMAND
    if control_command is not None and not abandon_command:
        return

    runtime = _runtime_path()
    if runtime is None:
        return

    command = [sys.executable, str(runtime), "guard", "--as", "claude"]
    session_ref = payload.get("session_id")
    if isinstance(session_ref, str) and session_ref:
        command.extend(["--session-ref", session_ref])

    try:
        result = subprocess.run(
            command,
            cwd=_working_directory(payload),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _block("handoff ownership could not be verified; repair the handoff runtime or state before mutating")

    parsed = _decision(result.stdout)
    if result.returncode == 0 and parsed is not None and parsed[0] == "allow":
        if abandon_command:
            _block("handoff abandon requires a released lease")
        return

    if parsed is not None and parsed[0] == "deny":
        reason, checkpoint_id, target_harness, worktree_root, receiver_command = parsed[1:]
        if abandon_command and "released" in reason:
            return
        if "released" in reason:
            if checkpoint_id is None or target_harness is None:
                if "swept" in reason:
                    _block(
                        "handoff ownership is released; clear the stale lease with "
                        "`swe-workbench-handoff abandon <checkpoint-id> --source-stopped "
                        "| swe-workbench-result-check swb.handoff/1`"
                    )
                _block("handoff ownership is released but its receiver state is invalid")
            instruction = (
                f"/{'handoff' if target_harness == 'pi' else 'swe-workbench:handoff'} "
                f"resume {checkpoint_id}"
            )
            receiver = (
                f"start the receiver with `{receiver_command}`"
                if receiver_command is not None
                else f"start a {target_harness} receiver in this worktree, then run `{instruction}`"
            )
            _block(
                _with_worktree_clause(
                    f"handoff ownership is released to {target_harness}; {receiver}",
                    worktree_root,
                )
            )
        if "different receiver session" in reason:
            _block(_with_worktree_clause("this worktree is bound to a different receiver session", worktree_root))
        if "held by" in reason:
            _block(_with_worktree_clause(reason, worktree_root))
        _block("the handoff lease denies mutation from this Claude session")

    if result.returncode != 0 and "Traceback" in result.stderr:
        _interpreter_failure()
    _block("handoff ownership state is unreadable or corrupt; repair it before mutating")


def _interpreter_failure() -> None:
    _block(
        "handoff runtime could not start: bin/swe-workbench-handoff requires Python 3.9+, "
        "and this repository's python3 could not run it. Check the repository's Python "
        "version pin (mise/asdf/pyenv/.python-version), ensure a Python 3.9+ interpreter "
        "is on PATH, or repair the swe-workbench plugin install"
    )


if __name__ == "__main__":
    main()
