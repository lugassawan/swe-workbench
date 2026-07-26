"""Existence, executability, shebang, and target-resolution checks for bin/ wrappers (issue #560).

bin/ wrappers are the bare-command invocation surface for runtime/ scripts once <plugin>/bin
is on PATH. Each wrapper must: carry the swe-workbench- prefix (the only guard against a
future user PATH collision — see docs/plugin-platform-decisions.md), be executable, start with
a #!/usr/bin/env <interp> shebang, and exec its sibling runtime/ script via dirname
"${BASH_SOURCE[0]}" — never $CLAUDE_PLUGIN_ROOT (see runtime/preflight-pr.sh's own precedent).
"""

import os
import re
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
BIN = ROOT / "bin"
RUNTIME = ROOT / "runtime"

# wrapper name -> (expected exec interpreter, expected runtime/ target)
WRAPPERS = {
    "swe-workbench-clean-ephemeral": ("bash", "clean-ephemeral.sh"),
    "swe-workbench-clean-state-files": ("bash", "clean-state-files.sh"),
    "swe-workbench-comment-scan": ("python3", "comment-scan.py"),
    "swe-workbench-doctor": ("bash", "doctor.sh"),
    "swe-workbench-fetch-pr": ("bash", "fetch-pr.sh"),
    "swe-workbench-gh-timeout": ("bash", "gh-timeout.sh"),
    "swe-workbench-preflight-pr": ("bash", "preflight-pr.sh"),
    "swe-workbench-reply-and-resolve": ("bash", "reply-and-resolve.sh"),
    "swe-workbench-sync-pr-metadata": ("bash", "sync-pr-metadata.sh"),
}

_SHEBANG_RE = re.compile(r'^#!/usr/bin/env \S+\n')


def test_bin_dir_has_exactly_the_expected_wrappers():
    """bin/ must contain exactly the tracked wrappers (prevents silent coverage gaps)."""
    on_disk = {p.name for p in BIN.iterdir() if p.is_file()}
    assert on_disk == set(WRAPPERS), (
        f"bin/ contents {sorted(on_disk)} do not match the tracked WRAPPERS "
        f"{sorted(WRAPPERS)} — update WRAPPERS in this test when adding/removing a wrapper"
    )


def test_every_wrapper_is_executable():
    for name in WRAPPERS:
        path = BIN / name
        assert path.exists(), f"bin/{name} must exist"
        assert os.access(path, os.X_OK), f"bin/{name} must be executable (chmod +x)"


def test_every_wrapper_has_env_shebang():
    for name in WRAPPERS:
        text = (BIN / name).read_text()
        first_line = text.splitlines(keepends=True)[0]
        assert _SHEBANG_RE.match(first_line), (
            f"bin/{name} must start with a #!/usr/bin/env <interp> shebang, got: {first_line!r}"
        )


def test_every_wrapper_carries_required_prefix():
    for name in WRAPPERS:
        assert name.startswith("swe-workbench-"), (
            f"bin/{name} must carry the swe-workbench- prefix — the only guard against "
            "colliding with a user's own PATH entries"
        )


def test_every_wrapper_execs_its_runtime_sibling_via_dirname():
    """Each wrapper must resolve runtime/ via dirname "${BASH_SOURCE[0]}", never $CLAUDE_PLUGIN_ROOT."""
    for name, (interp, target) in WRAPPERS.items():
        text = (BIN / name).read_text()
        assert "CLAUDE_PLUGIN_ROOT" not in text, (
            f"bin/{name} must not reference CLAUDE_PLUGIN_ROOT — resolve via "
            "dirname \"${BASH_SOURCE[0]}\" so it works from the installed plugin cache"
        )
        assert 'dirname "${BASH_SOURCE[0]}"' in text, (
            f"bin/{name} must resolve its own directory via dirname \"${{BASH_SOURCE[0]}}\""
        )
        assert f"exec {interp}".replace("exec bash", "exec") in text or f'exec "$(cd' in text, (
            f"bin/{name} must exec via '{interp}'"
        )
        assert target in text, (
            f"bin/{name} must exec runtime/{target}, its designated sibling script"
        )
        assert (RUNTIME / target).exists(), (
            f"bin/{name} targets runtime/{target}, which does not exist"
        )


def test_every_wrapper_passes_bash_syntax_check():
    """bash -n must pass for every wrapper (they are all bash scripts, even the python one)."""
    for name in WRAPPERS:
        path = BIN / name
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True, text=True,
            env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 0, f"bash -n bin/{name} failed:\n{result.stderr}"


def test_comment_scan_runtime_target_stays_non_executable():
    """runtime/comment-scan.py stays mode 644 — the wrapper is the executable, not the script."""
    path = RUNTIME / "comment-scan.py"
    assert path.exists(), "runtime/comment-scan.py must exist"
    assert not os.access(path, os.X_OK), (
        "runtime/comment-scan.py must NOT be executable — bin/swe-workbench-comment-scan "
        "invokes it via `exec python3 <path>`, so the script itself never needs the exec bit"
    )


def test_wrapper_actually_execs_doctor_and_produces_output():
    """End-to-end: running the wrapper produces doctor.sh's own output, from any cwd."""
    result = subprocess.run(
        ["bash", str(BIN / "swe-workbench-doctor")],
        capture_output=True, text=True,
        cwd="/tmp",
        env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, f"bin/swe-workbench-doctor failed from /tmp cwd:\n{result.stderr}"
    assert "swe-workbench preflight check" in result.stdout


def test_wrapper_passes_stdin_through_to_comment_scan():
    """Comment-scan's wrapper must pass stdin through unchanged (git diff | swe-workbench-comment-scan)."""
    direct = subprocess.run(
        ["python3", str(RUNTIME / "comment-scan.py")],
        input="", capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    wrapped = subprocess.run(
        ["bash", str(BIN / "swe-workbench-comment-scan")],
        input="", capture_output=True, text=True,
        env=dict(_CLEAN_ENV),
    )
    assert wrapped.returncode == direct.returncode
    assert wrapped.stdout == direct.stdout
