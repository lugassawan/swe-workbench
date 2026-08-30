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
_CONTROL_COMMANDS = (
    re.compile(
        rf'^swe-workbench-handoff resume "?{_UUID}"? --as "?claude"? '
        rf'--receiver-session {_CLAUDE_SESSION_ARGUMENT} '
        rf'(?:--acknowledge-degraded )?{_CHECKED_PIPE}$'
    ),
    re.compile(
        rf'^swe-workbench-handoff recover --from "?pi"? --source-stopped {_CHECKED_PIPE}$'
    ),
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
    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        candidate = Path(cwd)
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def _is_control_command(payload: dict[str, object]) -> bool:
    if payload.get("tool_name") != "Bash":
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    if not isinstance(command, str):
        return False
    normalized = " ".join(command.replace("\\\n", " ").split())
    return any(pattern.fullmatch(normalized) for pattern in _CONTROL_COMMANDS)


def _block(message: str) -> None:
    print(f"BLOCKED: {message}", file=sys.stderr)
    raise SystemExit(2)


def _decision(output: str) -> tuple[str, str] | None:
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
    return decision, reason


def main() -> None:
    payload = _load_payload()
    if payload is None or payload.get("tool_name") not in _MUTATING_TOOLS:
        return
    if _is_control_command(payload):
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
        return

    if parsed is not None and parsed[0] == "deny":
        reason = parsed[1]
        if "released" in reason:
            _block("handoff ownership is released; resume the checkpoint in the receiver before mutating")
        if "different receiver session" in reason:
            _block("this worktree is bound to a different receiver session")
        if "held by" in reason:
            _block(reason)
        _block("the handoff lease denies mutation from this Claude session")

    _block("handoff ownership state is unreadable or corrupt; repair it before mutating")


if __name__ == "__main__":
    main()
