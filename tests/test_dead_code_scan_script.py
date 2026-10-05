"""Tests for bin/swe-workbench-dead-code-scan.

Full-repo dead/test-only code scanner emitting the standard JSON envelope
(shared/docs/runtime-result-contract.md). Hermetic tests force the grep funnel
and stub the LSP sibling via SWB_DEAD_CODE_LSP_BIN; native-tool tests skip when
the tool is absent. Unit tests import the module directly (SourceFileLoader,
mirroring test_result_check_script.py's precedent); behavioral tests drive the
script as a subprocess.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-dead-code-scan"


def _load_module():
    loader = SourceFileLoader("dead_code_scan", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("dead_code_scan", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dead_code_scan"] = module
    spec.loader.exec_module(module)
    return module


def _env(**extra):
    env = dict(_CLEAN_ENV)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _run(args, *, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd, env=env or _env(),
    )


def _scan(root: Path, *args, env=None):
    """Run the scanner against `root` and return (returncode, envelope-or-None)."""
    proc = _run(["--root", str(root), "--funnel", "grep", *args], env=env or _env())
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        envelope = None
    return proc.returncode, envelope


def _write(root: Path, relpath: str, text: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _find(candidates, symbol):
    return next((c for c in candidates if c["symbol"] == symbol), None)


# ── Existence ────────────────────────────────────────────────────────────────


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-dead-code-scan must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-dead-code-scan must be executable (chmod +x)"


# ── Envelope shape ───────────────────────────────────────────────────────────


def test_envelope_shape_and_exit_zero_with_findings(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan_fn():\n    return 1\n")
    rc, envelope = _scan(tmp_path)
    assert rc == 0, f"findings are not failures — exit 0, stderr: {envelope and ''}"
    assert envelope["schema"] == "swb.dead-code-scan/1"
    assert envelope["status"] == "ok"
    assert envelope["warnings"] == []
    data = envelope["data"]
    assert data["root"] == str(tmp_path)
    assert data["funnel"] == "grep"
    assert data["scanned_files"] == 1
    assert data["candidate_count"] == 1
    assert data["safe_keep_count"] == 0
    assert data["justified_count"] == 0
    orphan = _find(data["candidates"], "orphan_fn")
    assert orphan is not None
    assert orphan["path"] == "src/mod.py"
    assert orphan["line"] == 1
    assert orphan["kind"] == "function"
    assert orphan["keep_class"] == "candidate"
    assert orphan["keep_reason"] == ""
    assert orphan["test_only"] is False
    assert orphan["references"] == []
    assert orphan["detected_by"] == "grep"


def test_clean_repo_reports_zero_candidates(tmp_path):
    _write(tmp_path, "src/mod.py", "def used():\n    return 1\n")
    _write(tmp_path, "src/main.py", "from src.mod import used\nused()\n")
    rc, envelope = _scan(tmp_path)
    assert rc == 0
    assert envelope["data"]["candidate_count"] == 0
    assert envelope["data"]["candidates"] == []


# ── Used vs unused vs test-only ──────────────────────────────────────────────


def test_used_function_not_reported(tmp_path):
    _write(tmp_path, "src/mod.py", "def helper():\n    return 1\n")
    _write(tmp_path, "src/app.py", "from src.mod import helper\nprint(helper())\n")
    rc, envelope = _scan(tmp_path)
    assert _find(envelope["data"]["candidates"], "helper") is None


def test_test_only_symbol_reported_with_test_references(tmp_path):
    _write(tmp_path, "src/mod.py", "def lonely():\n    return 1\n")
    _write(tmp_path, "tests/test_mod.py", "from src.mod import lonely\n\ndef test_lonely():\n    assert lonely() == 1\n")
    rc, envelope = _scan(tmp_path)
    lonely = _find(envelope["data"]["candidates"], "lonely")
    assert lonely is not None
    assert lonely["keep_class"] == "candidate"
    assert lonely["test_only"] is True
    assert lonely["references"], "test-only candidates must carry their reference evidence"
    assert all(ref["reason"] == "test" for ref in lonely["references"])
    assert any(ref["path"].startswith("tests/") for ref in lonely["references"])


@pytest.mark.parametrize("ref_path", ["packages/other/src/caller.py", "apps/cli/main.py"])
def test_cross_package_reference_counts_as_used(tmp_path, ref_path):
    """Test-only means only tests reference it across the WHOLE repo."""
    _write(tmp_path, "libs/core/mod.py", "def shared():\n    return 1\n")
    _write(tmp_path, ref_path, "from libs.core.mod import shared\nshared()\n")
    rc, envelope = _scan(tmp_path)
    assert _find(envelope["data"]["candidates"], "shared") is None


def test_method_references_from_own_class_count_as_used(tmp_path):
    """A method invoked by name within its own class file is used (text mention)."""
    _write(
        tmp_path, "src/svc.py",
        "class Service:\n"
        "    def run(self):\n"
        "        return self.step()\n"
        "    def step(self):\n"
        "        return 2\n",
    )
    rc, envelope = _scan(tmp_path)
    assert _find(envelope["data"]["candidates"], "step") is None


# ── Safe-keep set ────────────────────────────────────────────────────────────


def test_python_all_export_is_safe_keep(tmp_path):
    _write(
        tmp_path, "src/api.py",
        "\"\"\"Public API.\"\"\"\n"
        "__all__ = [\"public_fn\"]\n"
        "\n"
        "def public_fn():\n"
        "    return 1\n",
    )
    rc, envelope = _scan(tmp_path)
    pub = _find(envelope["data"]["candidates"], "public_fn")
    assert pub is not None
    assert pub["keep_class"] == "safe-keep"
    assert "export" in pub["keep_reason"]
    assert envelope["data"]["safe_keep_count"] == 1
    assert envelope["data"]["candidate_count"] == 0


def test_js_export_function_is_safe_keep(tmp_path):
    _write(tmp_path, "src/api.ts", "export function publicFn(): number {\n  return 1;\n}\n")
    rc, envelope = _scan(tmp_path)
    pub = _find(envelope["data"]["candidates"], "publicFn")
    assert pub is not None
    assert pub["keep_class"] == "safe-keep"
    assert envelope["data"]["safe_keep_count"] == 1


def test_non_exported_js_function_is_plain_candidate(tmp_path):
    _write(tmp_path, "src/api.ts", "function internalFn(): number {\n  return 1;\n}\n")
    rc, envelope = _scan(tmp_path)
    fn = _find(envelope["data"]["candidates"], "internalFn")
    assert fn is not None
    assert fn["keep_class"] == "candidate"


def test_package_json_bin_entry_is_safe_keep(tmp_path):
    _write(tmp_path, "package.json", '{"name": "x", "bin": {"x": "bin/x.js"}}\n')
    _write(tmp_path, "bin/x.js", "function main(): void {\n  console.log(1);\n}\nmain();\n")
    rc, envelope = _scan(tmp_path)
    main_fn = _find(envelope["data"]["candidates"], "main")
    assert main_fn is not None
    assert main_fn["keep_class"] == "safe-keep"
    assert "entry" in main_fn["keep_reason"]


def test_dynamic_getattr_reference_is_safe_keep(tmp_path):
    _write(tmp_path, "src/mod.py", "def plugin_hook():\n    return 1\n")
    _write(tmp_path, "src/loader.py", "fn = getattr(mod, \"plugin_hook\")\nfn()\n")
    rc, envelope = _scan(tmp_path)
    hook = _find(envelope["data"]["candidates"], "plugin_hook")
    assert hook is not None
    assert hook["keep_class"] == "safe-keep"
    assert "dynamic" in hook["keep_reason"].lower()


# ── Justification (marker + adjacent comment) ────────────────────────────────


def test_keep_marker_makes_symbol_justified(tmp_path):
    _write(
        tmp_path, "src/mod.py",
        "# dead-code: keep retained for the v2 migration\n"
        "def legacy_fn():\n"
        "    return 1\n",
    )
    rc, envelope = _scan(tmp_path)
    legacy = _find(envelope["data"]["candidates"], "legacy_fn")
    assert legacy is not None
    assert legacy["keep_class"] == "justified"
    assert legacy["keep_reason"] == "retained for the v2 migration"
    assert envelope["data"]["justified_count"] == 1
    assert envelope["data"]["candidate_count"] == 0


def test_marker_on_docstring_line_is_justified(tmp_path):
    _write(
        tmp_path, "src/mod.py",
        "def kept_fn():\n"
        "    \"\"\"dead-code: keep pending follow-up release\"\"\"\n"
        "    return 1\n",
    )
    rc, envelope = _scan(tmp_path)
    kept = _find(envelope["data"]["candidates"], "kept_fn")
    assert kept is not None
    assert kept["keep_class"] == "justified"


def test_plain_adjacent_comment_captured_into_note_not_justified(tmp_path):
    _write(
        tmp_path, "src/mod.py",
        "# This helper exists for historical reasons.\n"
        "def old_fn():\n"
        "    return 1\n",
    )
    rc, envelope = _scan(tmp_path)
    old = _find(envelope["data"]["candidates"], "old_fn")
    assert old is not None
    assert old["keep_class"] == "candidate", "agent judgment decides justification, not the script"
    assert "historical reasons" in old["note"]


# ── Exclusions, caps, purity ─────────────────────────────────────────────────


def test_excluded_dirs_are_skipped_for_scanning_and_references(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    _write(tmp_path, "node_modules/pkg/index.js", "orphan\n")
    rc, envelope = _scan(tmp_path)
    assert envelope["data"]["scanned_files"] == 1, "node_modules must not be scanned"
    orphan = _find(envelope["data"]["candidates"], "orphan")
    assert orphan is not None, "a reference inside node_modules must not count as usage"


@pytest.mark.parametrize(
    "dirname", [".git", "node_modules", "dist", "build", ".venv", "__pycache__", "target"],
)
def test_known_excluded_dirs_never_scanned(tmp_path, dirname):
    _write(tmp_path, f"{dirname}/x.py", "def never_seen():\n    return 1\n")
    rc, envelope = _scan(tmp_path)
    assert envelope["data"]["scanned_files"] == 0
    assert _find(envelope["data"]["candidates"], "never_seen") is None


def test_file_cap_reports_partial_with_warning(tmp_path):
    for i in range(5):
        _write(tmp_path, f"src/m{i}.py", f"def orphan_{i}():\n    return {i}\n")
    rc, envelope = _scan(tmp_path, "--max-files", "2")
    assert rc == 0
    assert envelope["status"] == "partial"
    assert envelope["data"]["scanned_files"] == 2
    assert any("cap" in w["message"].lower() for w in envelope["warnings"])


def test_grep_funnel_spawns_no_subprocess_per_candidate(tmp_path, monkeypatch):
    """The text index is one in-process walk — no per-candidate grep spawning."""
    for i in range(6):
        _write(tmp_path, f"src/m{i}.py", f"def orphan_{i}():\n    return {i}\n")
    module = _load_module()
    calls = []

    def _fail_run(*a, **k):  # pragma: no cover - only reached on violation
        calls.append(a)
        raise AssertionError("grep funnel must not spawn subprocesses")

    monkeypatch.setattr(module.subprocess, "run", _fail_run)
    monkeypatch.setattr(module.subprocess, "Popen", _fail_run)
    result = module.scan_root(str(tmp_path), funnel="grep")
    assert result["data"]["candidate_count"] == 6
    assert calls == []


# ── Funnel selection and fallback ────────────────────────────────────────────


def _stub_lsp(tmp_path, body: str) -> Path:
    stub = tmp_path / "lsp-stub.sh"
    stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def test_lsp_exit3_falls_through_to_grep_cleanly(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    stub = _stub_lsp(tmp_path, "exit 3")
    rc, envelope = _scan(tmp_path, "--funnel", "lsp", env=_env(SWB_DEAD_CODE_LSP_BIN=str(stub)))
    assert rc == 0
    assert envelope["data"]["funnel"] == "grep"
    assert envelope["data"]["candidate_count"] == 1
    assert any(w["code"] == "lsp-unavailable" for w in envelope["warnings"])


def test_lsp_mid_scan_error_reports_partial(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    stub = _stub_lsp(tmp_path, "exit 5")
    rc, envelope = _scan(tmp_path, "--funnel", "lsp", env=_env(SWB_DEAD_CODE_LSP_BIN=str(stub)))
    assert rc == 0
    assert envelope["status"] == "partial"
    assert envelope["data"]["funnel"] == "grep", "grep result still stands after LSP error"
    assert any(w["code"] == "lsp-error" for w in envelope["warnings"])


def test_forced_grep_funnel_never_calls_lsp(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    stub = _stub_lsp(tmp_path, "exit 5")  # would fail loudly if invoked
    rc, envelope = _scan(tmp_path, env=_env(SWB_DEAD_CODE_LSP_BIN=str(stub)))
    assert rc == 0
    assert envelope["data"]["funnel"] == "grep"
    assert envelope["warnings"] == []


@pytest.mark.skipif(shutil.which("vulture") is None, reason="vulture not installed")
def test_native_vulture_funnel_marks_detected_by(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    rc, envelope = _scan(tmp_path, "--funnel", "native")
    assert rc == 0
    orphan = _find(envelope["data"]["candidates"], "orphan")
    assert orphan is not None
    assert orphan["detected_by"] == "native:vulture"


def test_native_funnel_without_tools_falls_back_to_grep(tmp_path, monkeypatch):
    """Unit-level: an empty tool registry means native collapses to the grep base."""
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    module = _load_module()
    monkeypatch.setattr(module, "NATIVE_TOOLS", {})
    envelope = module.scan_root(str(tmp_path), funnel="native")
    assert envelope["status"] == "ok"
    assert envelope["data"]["funnel"] == "grep"
    assert envelope["data"]["candidate_count"] == 1


# ── CLI surface ──────────────────────────────────────────────────────────────


def test_help_self_documents(tmp_path):
    proc = _run(["--help"])
    assert proc.returncode == 0
    for needle in ("--root", "--funnel", "--max-files"):
        assert needle in proc.stdout


def test_root_defaults_to_cwd(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    proc = _run(["--funnel", "grep"], cwd=str(tmp_path))
    assert proc.returncode == 0
    envelope = json.loads(proc.stdout)
    assert envelope["data"]["root"] == str(tmp_path)
    assert envelope["data"]["candidate_count"] == 1


def test_missing_root_is_hard_failure_not_envelope(tmp_path):
    proc = _run(["--root", str(tmp_path / "does-not-exist")], env=_env())
    assert proc.returncode != 0
    assert proc.stdout.strip() == "", "hard failures emit nothing on stdout"
    assert proc.stderr.strip() != ""


def test_stdout_is_envelope_only_diagnostics_on_stderr(tmp_path):
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    proc = _run(["--root", str(tmp_path), "--funnel", "grep"], env=_env())
    assert proc.returncode == 0
    json.loads(proc.stdout)  # entire stdout must be the JSON envelope
