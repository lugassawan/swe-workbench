"""Behavioral tests for hooks/memory_hint.sh — the Claude Code SessionStart
wrapper around bin/swe-workbench-memory (issue #697).

The shim must fail open — exit 0, no stdout on any failure (missing runtime,
runtime error, absent cwd, foreign envelope): a broken hint must never block
session startup. Hermetic: HOME + SWE_WORKBENCH_MEMORY_STATE_DIR point into
tmp dirs, XDG_STATE_HOME unset — no real ~/.claude tree is ever touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SHIM = ROOT / "hooks" / "memory_hint.sh"


def slug_of(path) -> str:
    return str(Path(path).resolve()).replace("/", "-").lstrip("-")


def write_store(store_dir: Path, entries) -> None:
    """Fabricate a Claude-format memory store.

    Duplicated from tests/test_memory_script.py (test files don't import
    across each other); entries: [(name, description, type)] newest-first.
    """
    store_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Memory index", ""]
    for name, description, entry_type in entries:
        file_name = f"{entry_type}_{name}.md"
        (store_dir / file_name).write_text(
            "---\n"
            f"name: {name}\n"
            f'description: "{description}"\n'
            "metadata:\n"
            "  node_type: memory\n"
            f"  type: {entry_type}\n"
            "---\n"
            "\n"
            f"body of {name}\n",
            encoding="utf-8",
        )
        lines.append(f"- [{name}]({file_name}) — {description}")
    (store_dir / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def hermetic_env(cwd: Path) -> dict[str, str]:
    env = dict(_CLEAN_ENV)
    env["HOME"] = str(cwd / "home")
    env["SWE_WORKBENCH_MEMORY_STATE_DIR"] = str(cwd / "state")
    env.pop("XDG_STATE_HOME", None)
    return env


def run_shim(
    script: Path, payload: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env if env is not None else hermetic_env(cwd),
        timeout=30,
    )


def payload_with_cwd(cwd: Path) -> str:
    return json.dumps({"cwd": str(cwd), "source": "startup"})


def payload_with_cwd_and_harness(cwd: Path, harness: str) -> str:
    return json.dumps({"cwd": str(cwd), "source": "startup", "harness": harness})


def test_shim_exists_and_executable():
    assert SHIM.exists(), f"Missing hook script: {SHIM}"
    assert SHIM.stat().st_mode & 0o111, f"Hook script not executable: {SHIM}"


def test_valid_payload_injects_memory_as_additional_context(tmp_path):
    write_store(
        tmp_path / "state" / slug_of(tmp_path),
        [("hint-entry", "Pi remembers this", "feedback")],
    )
    result = run_shim(SHIM, payload_with_cwd(tmp_path), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    hook_output = parsed["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    context = hook_output["additionalContext"]
    assert context.splitlines()[0].startswith(
        "The following is accumulated project memory"
    )
    assert "## Pi memory (read-only)" in context
    assert "hint-entry" in context


def test_empty_stores_emit_no_stdout(tmp_path):
    result = run_shim(SHIM, payload_with_cwd(tmp_path), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_missing_runtime_fails_open(tmp_path):
    hooks = tmp_path / "copied" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(SHIM, hooks / "memory_hint.sh")
    result = run_shim(
        hooks / "memory_hint.sh", payload_with_cwd(tmp_path), cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_harness_pi_payload_renders_pi_store_as_own(tmp_path):
    # The shim reads .harness from the payload (the Pi extension sends "pi") and
    # renders with that harness as the owning side.
    write_store(
        tmp_path / "state" / slug_of(tmp_path),
        [("pi-note", "Pi remembers this", "feedback")],
    )
    write_store(
        tmp_path / "home" / ".claude" / "projects" / slug_of(tmp_path) / "memory",
        [("claude-note", "Claude remembers this", "feedback")],
    )
    result = run_shim(
        SHIM, payload_with_cwd_and_harness(tmp_path, "pi"), cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "## Pi memory (own)" in context
    assert "pi-note" in context
    assert "## Claude Code memory (read-only)" in context
    assert "claude-note" in context


def test_nonzero_runtime_exit_fails_open(tmp_path):
    # A regular file at the state-dir override makes the runtime exit 1 (StorageError)
    # while the shim stays fail-open — the old chmod-000 premise now degrades cleanly.
    state_dir = tmp_path / "state"
    state_dir.write_text("not a directory", encoding="utf-8")
    env = hermetic_env(tmp_path)
    env["SWE_WORKBENCH_MEMORY_STATE_DIR"] = str(state_dir)
    runtime_result = subprocess.run(
        [str(ROOT / "bin" / "swe-workbench-memory"), "render", "--as", "claude"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        timeout=30,
    )
    assert runtime_result.returncode == 1
    assert runtime_result.stdout == ""
    assert runtime_result.stderr.startswith("swe-workbench-memory:")
    assert "Traceback" not in runtime_result.stderr
    result = run_shim(SHIM, payload_with_cwd(tmp_path), cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_stdin_without_cwd_fails_open(tmp_path):
    # The shim falls back to $PWD; under hermetic HOME/state both stores are
    # empty there, so the render is empty and no output is emitted.
    result = run_shim(SHIM, json.dumps({"source": "startup"}), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_foreign_schema_envelope_emits_no_stdout(tmp_path):
    stub_tree = tmp_path / "stubbed"
    hooks = stub_tree / "hooks"
    bin_dir = stub_tree / "bin"
    hooks.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    shutil.copy(SHIM, hooks / "memory_hint.sh")
    stub = bin_dir / "swe-workbench-memory"
    stub.write_text(
        "#!/bin/sh\n"
        ': > "$(dirname "$0")/.stub-ran"\n'
        'printf \'{"schema": "swb.other/1", "status": "ok", '
        '"data": {"markdown": "# injected"}, "warnings": []}\'\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    result = run_shim(
        hooks / "memory_hint.sh", payload_with_cwd(tmp_path), cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    # The stub really ran — the silence came from the schema gate, not an
    # earlier guard (runtime resolution, cd, execution).
    assert (bin_dir / ".stub-ran").exists()
