"""Existence, executability, shebang, and syntax checks for bin/ scripts (issue #571).

bin/ is now the sole home for these twelve scripts — runtime/ is retired, and there is no
wrapper/target split left to check. Each script must: carry the swe-workbench- prefix (the
only guard against a future user PATH collision — see docs/plugin-platform-decisions.md),
be executable, start with a #!/usr/bin/env <interp> shebang matching its own interpreter,
never reference $CLAUDE_PLUGIN_ROOT, and resolve any sibling script via
dirname "${BASH_SOURCE[0]}" / dirname "$0" — never a bare PATH lookup, since a script running
by absolute path must not depend on <plugin>/bin being on PATH for its own internal calls.
"""

import os
import py_compile
import re
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
BIN = ROOT / "bin"

# bare command name -> interpreter
SCRIPTS = {
    "swe-workbench-clean-ephemeral": "bash",
    "swe-workbench-clean-state-files": "bash",
    "swe-workbench-comment-scan": "python3",
    "swe-workbench-diff-line-lookup": "bash",
    "swe-workbench-doctor": "bash",
    "swe-workbench-fetch-pr": "bash",
    "swe-workbench-gh-timeout": "bash",
    "swe-workbench-new-run-dir": "bash",
    "swe-workbench-preflight-pr": "bash",
    "swe-workbench-reap-run-dir": "bash",
    "swe-workbench-reply-and-resolve": "bash",
    "swe-workbench-sync-pr-metadata": "bash",
}

# scripts known to call a sibling script by basename (script -> sibling basenames it calls)
SIBLING_CALLERS = {
    "swe-workbench-fetch-pr": ["swe-workbench-gh-timeout"],
    "swe-workbench-new-run-dir": ["swe-workbench-reap-run-dir"],
    "swe-workbench-preflight-pr": ["swe-workbench-gh-timeout", "swe-workbench-fetch-pr"],
    "swe-workbench-reply-and-resolve": ["swe-workbench-gh-timeout"],
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
    py_compile.compile(str(BIN / "swe-workbench-comment-scan"), doraise=True)


def test_no_claude_plugin_root_reference():
    for name in SCRIPTS:
        text = (BIN / name).read_text()
        assert "CLAUDE_PLUGIN_ROOT" not in text, (
            f"bin/{name} must not reference CLAUDE_PLUGIN_ROOT"
        )


_SCRIPT_DIR_RE = re.compile(r'\$\(dirname "(\$0|\$\{BASH_SOURCE\[0\]\})"\)')


def test_sibling_calls_resolve_via_script_dir():
    """Sibling-calling scripts must resolve via dirname "$0"/"${BASH_SOURCE[0]}", never bare PATH."""
    for name, siblings in SIBLING_CALLERS.items():
        text = (BIN / name).read_text()
        assert _SCRIPT_DIR_RE.search(text), (
            f"bin/{name} calls a sibling script but does not resolve SCRIPT_DIR via "
            'dirname "$0" or dirname "${BASH_SOURCE[0]}"'
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
