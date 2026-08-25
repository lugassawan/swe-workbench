"""Existence, executability, shebang, and syntax checks for bin/ scripts (issue #571, #550).

bin/ is the sole home for these scripts — runtime/ is retired, and there is no
wrapper/target split left to check. Each must carry the swe-workbench- prefix, be executable,
start with a matching #!/usr/bin/env <interp> shebang, never reference $CLAUDE_PLUGIN_ROOT,
and resolve any sibling script via dirname "$0"/"${BASH_SOURCE[0]}" (bash) or
Path(__file__).parent (python3) — never a bare PATH lookup.
"""

import os
import py_compile
import re
import shutil
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
BIN = ROOT / "bin"

# bare command name -> interpreter
SCRIPTS = {
    "swe-workbench-address-feedback-fetch": "python3",
    "swe-workbench-address-feedback-worktree": "bash",
    "swe-workbench-apply-conflict-resolution": "bash",
    "swe-workbench-clean-ephemeral": "bash",
    "swe-workbench-clean-state-files": "bash",
    "swe-workbench-comment-scan": "python3",
    "swe-workbench-diff-line-lookup": "bash",
    "swe-workbench-doctor": "bash",
    "swe-workbench-fetch-pr": "bash",
    "swe-workbench-gh-timeout": "bash",
    "swe-workbench-lsp": "python3",
    "swe-workbench-new-run-dir": "bash",
    "swe-workbench-preflight-commit": "python3",
    "swe-workbench-preflight-pr": "bash",
    "swe-workbench-pr-review-submit": "python3",
    "swe-workbench-pr-review-worktree": "bash",
    "swe-workbench-reap-run-dir": "bash",
    "swe-workbench-reap-session-scratch": "bash",
    "swe-workbench-reply-and-resolve": "bash",
    "swe-workbench-result-check": "python3",
    "swe-workbench-session-scratch-adapter-claude": "bash",
    "swe-workbench-session-scratch-adapter-pi": "bash",
    "swe-workbench-skill-script": "bash",
    "swe-workbench-sweep-residuals": "bash",
    "swe-workbench-sync-pr-metadata": "bash",
}

# scripts known to call a sibling script by basename (script -> sibling basenames it calls)
SIBLING_CALLERS = {
    "swe-workbench-address-feedback-fetch": ["swe-workbench-preflight-pr", "swe-workbench-gh-timeout"],
    "swe-workbench-address-feedback-worktree": ["swe-workbench-skill-script", "swe-workbench-clean-ephemeral"],
    "swe-workbench-fetch-pr": ["swe-workbench-gh-timeout"],
    "swe-workbench-new-run-dir": ["swe-workbench-reap-run-dir"],
    "swe-workbench-preflight-pr": [
        "swe-workbench-gh-timeout",
        "swe-workbench-fetch-pr",
        "swe-workbench-clean-state-files",
    ],
    "swe-workbench-pr-review-submit": ["swe-workbench-gh-timeout", "swe-workbench-diff-line-lookup"],
    "swe-workbench-pr-review-worktree": ["swe-workbench-skill-script", "swe-workbench-clean-ephemeral"],
    "swe-workbench-reply-and-resolve": ["swe-workbench-gh-timeout"],
    "swe-workbench-sweep-residuals": [
        "swe-workbench-skill-script",
        "swe-workbench-clean-state-files",
        "swe-workbench-clean-ephemeral",
        "swe-workbench-reap-run-dir",
        "swe-workbench-reap-session-scratch",
    ],
    "swe-workbench-sync-pr-metadata": ["swe-workbench-gh-timeout"],
}


def test_bin_contents_match_scripts_dict():
    """bin/ must contain exactly the tracked scripts plus README.md (prevents coverage gaps)."""
    on_disk = {p.name for p in BIN.iterdir() if p.is_file()}
    assert on_disk == set(SCRIPTS) | {"README.md"}, (
        f"bin/ contents {sorted(on_disk)} do not match SCRIPTS {sorted(SCRIPTS)} | " "{'README.md'}"
    )


def test_every_script_exists_and_is_executable():
    for name in SCRIPTS:
        path = BIN / name
        assert path.is_file(), f"bin/{name} must exist"
        assert os.access(path, os.X_OK), f"bin/{name} must be executable (chmod +x)"


def test_shebang_matches_own_interpreter():
    for name, interp in SCRIPTS.items():
        first_line = (BIN / name).read_text().splitlines()[0]
        assert first_line == f"#!/usr/bin/env {interp}", (
            f"bin/{name} shebang must be exactly '#!/usr/bin/env {interp}', got {first_line!r}"
        )


def test_prefix_present():
    for name in SCRIPTS:
        assert name.startswith("swe-workbench-"), f"{name} must carry the swe-workbench- prefix"


def test_no_sh_or_py_suffix():
    for name in SCRIPTS:
        assert not name.endswith(".sh") and not name.endswith(".py"), (
            f"bin/{name} must be a bare command name, not a scripted-extension filename"
        )


def test_bash_scripts_pass_syntax_check():
    for name, interp in SCRIPTS.items():
        if interp != "bash":
            continue
        result = subprocess.run(
            ["bash", "-n", str(BIN / name)],
            capture_output=True, text=True,
            env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 0, f"bash -n bin/{name} failed:\n{result.stderr}"


def test_python_script_compiles():
    for name, interp in SCRIPTS.items():
        if interp != "python3":
            continue
        py_compile.compile(str(BIN / name), doraise=True)


def test_no_claude_plugin_root_reference():
    for name in SCRIPTS:
        text = (BIN / name).read_text()
        assert "CLAUDE_PLUGIN_ROOT" not in text, (
            f"bin/{name} must not reference CLAUDE_PLUGIN_ROOT"
        )


_SCRIPT_DIR_RE = re.compile(r'\$\(dirname "(\$0|\$\{BASH_SOURCE\[0\]\})"\)')
_PY_SCRIPT_DIR_RE = re.compile(r"Path\(__file__\)(\.resolve\(\))?\.parent")


def test_sibling_calls_resolve_via_script_dir():
    """Sibling-calling scripts must resolve via dirname "$0"/"${BASH_SOURCE[0]}" (bash) or
    Path(__file__).parent (python3) — never bare PATH."""
    for name, siblings in SIBLING_CALLERS.items():
        text = (BIN / name).read_text()
        script_dir_re = _PY_SCRIPT_DIR_RE if SCRIPTS[name] == "python3" else _SCRIPT_DIR_RE
        assert script_dir_re.search(text), (
            f"bin/{name} calls a sibling script but does not resolve its own script dir via "
            f"{'Path(__file__).parent' if SCRIPTS[name] == 'python3' else 'dirname \"$0\"/dirname \"${BASH_SOURCE[0]}\"'}"
        )
        for sibling in siblings:
            assert sibling in text, (
                f"bin/{name} must reference its sibling bin/{sibling} by its new bare-command basename"
            )


def test_e2e_doctor_runs_by_absolute_path():
    result = subprocess.run(
        [str(BIN / "swe-workbench-doctor")],
        capture_output=True, text=True,
        cwd="/tmp",
        env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, f"bin/swe-workbench-doctor failed:\n{result.stderr}"
    assert "swe-workbench preflight check" in result.stdout


def test_e2e_comment_scan_reads_stdin():
    result = subprocess.run(
        [str(BIN / "swe-workbench-comment-scan")],
        input="", capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, f"bin/swe-workbench-comment-scan failed:\n{result.stderr}"


# ──────────────────────────────────────────────
# swe-workbench-skill-script dispatcher (issue #569): runtime behavior
# ──────────────────────────────────────────────
#
# These tests build an isolated <tmp>/bin + <tmp>/skills tree (copying only the dispatcher
# itself) rather than exercising it against the real skills/ directory, so the dispatcher's
# own traversal-rejection and passthrough behavior is verified independently of any real
# skill script's content or future changes.


def _isolated_dispatcher(tmp_path):
    """Copy the dispatcher into <tmp_path>/bin/ so its self-located ROOT is <tmp_path>."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dispatcher = bin_dir / "swe-workbench-skill-script"
    shutil.copy2(BIN / "swe-workbench-skill-script", dispatcher)
    dispatcher.chmod(0o755)
    return dispatcher


def _write_scratch_script(tmp_path, skill, script, body):
    scripts_dir = tmp_path / "skills" / skill / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / script
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)
    return path


def test_e2e_skill_script_dispatches_and_passes_stdout_through(tmp_path):
    dispatcher = _isolated_dispatcher(tmp_path)
    _write_scratch_script(tmp_path, "fake-skill", "greet.sh", 'echo "hello $1"')
    result = subprocess.run(
        [str(dispatcher), "fake-skill", "greet.sh", "world"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0
    assert result.stdout == "hello world\n"


def test_e2e_skill_script_passes_exit_code_through(tmp_path):
    dispatcher = _isolated_dispatcher(tmp_path)
    _write_scratch_script(tmp_path, "fake-skill", "fail.sh", "exit 3")
    result = subprocess.run(
        [str(dispatcher), "fake-skill", "fail.sh"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 3


def test_e2e_skill_script_passes_args_with_spaces_through(tmp_path):
    dispatcher = _isolated_dispatcher(tmp_path)
    _write_scratch_script(tmp_path, "fake-skill", "echo-arg.sh", 'printf "%s" "$1"')
    result = subprocess.run(
        [str(dispatcher), "fake-skill", "echo-arg.sh", "a file with spaces.txt"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0
    assert result.stdout == "a file with spaces.txt"


def test_e2e_skill_script_rejects_missing_target():
    result = subprocess.run(
        [str(BIN / "swe-workbench-skill-script"), "bogus-skill", "nope.sh"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "not found" in result.stderr


def test_e2e_skill_script_rejects_traversal():
    dispatcher = BIN / "swe-workbench-skill-script"
    cases = [
        ("../etc", "passwd"),
        ("workflow-cleanup-merged", "../../../etc/passwd"),
        ("a/b", "script.sh"),
        ("skill", "a/b.sh"),
        ("..", "script.sh"),
        ("foo..bar", "script.sh"),
    ]
    for skill, script in cases:
        result = subprocess.run(
            [str(dispatcher), skill, script],
            capture_output=True, text=True, env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 1, f"expected rejection for skill={skill!r} script={script!r}"
        assert result.stdout == ""
        assert result.stderr.strip(), f"expected a stderr message for skill={skill!r} script={script!r}"


def test_e2e_skill_script_requires_both_args():
    dispatcher = BIN / "swe-workbench-skill-script"
    for args in ([], ["only-skill"]):
        result = subprocess.run(
            [str(dispatcher), *args],
            capture_output=True, text=True, env=dict(_CLEAN_ENV),
        )
        assert result.returncode != 0, f"expected non-zero exit for args={args!r}"
