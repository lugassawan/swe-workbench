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
    assert envelope["status"] == "ok", f"real vulture exits 3 on findings: {envelope['warnings']}"
    assert envelope["data"]["funnel"] == "native+grep"
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


# ── Review-fix regression tests ─────────────────────────────────────────


def test_defs_in_test_files_are_never_candidates(tmp_path):
    """Test functions are invoked by the runner by name/pattern — zero textual
    references by design. Reporting them as removable candidates floods the
    envelope (a repo self-scan is ~90% test functions)."""
    _write(tmp_path, "src/mod.py", "def prod_fn():\n    return 1\n")
    _write(
        tmp_path, "tests/test_mod.py",
        "from src.mod import prod_fn\n\n"
        "def helper_fixture():\n    return 2\n\n"
        "def test_mod():\n    assert prod_fn() == 1\n",
    )
    rc, envelope = _scan(tmp_path)
    symbols = [c["symbol"] for c in envelope["data"]["candidates"]]
    assert "test_mod" not in symbols, "test functions must never be removal candidates"
    assert "helper_fixture" not in symbols, "helpers defined in test files are harness code"
    prod = _find(envelope["data"]["candidates"], "prod_fn")
    assert prod is not None, "referenced only by tests → test-only candidate (the headline feature)"
    assert prod["test_only"] is True


def test_flat_layout_test_file_counts_as_test_path(tmp_path):
    """pytest's canonical flat layout (test_utils.py next to sources) must count
    as a test path, not a production reference."""
    _write(tmp_path, "src/mod.py", "def lonely():\n    return 1\n")
    _write(tmp_path, "src/test_utils.py", "from src.mod import lonely\n\ndef check():\n    return lonely()\n")
    rc, envelope = _scan(tmp_path)
    lonely = _find(envelope["data"]["candidates"], "lonely")
    assert lonely is not None, "a reference from test_utils.py is a test reference"
    assert lonely["test_only"] is True
    assert all(ref["reason"] == "test" for ref in lonely["references"])


def test_lsp_verify_covers_row_after_removed_row(tmp_path):
    """Removing a row mid-iteration must not skip the next row's verification."""
    _write(tmp_path, "src/mod.py", "def first_orphan():\n    return 1\n\ndef second_orphan():\n    return 2\n")
    payload = (
        '{"server":"stub","analyzed_files":1,"truncated":false,'
        '"elapsed_seconds":0,"results":[{"file":"src/real_caller.py","line":3,"character":1}]}'
    )
    stub = _stub_lsp(
        tmp_path,
        f"if [[ \"$*\" == *\"--symbol\"* ]]; then cat <<'JSON'\n{payload}\nJSON\nfi",
    )
    rc, envelope = _scan(
        tmp_path, "--funnel", "lsp", env=_env(SWB_DEAD_CODE_LSP_BIN=str(stub))
    )
    symbols = [c["symbol"] for c in envelope["data"]["candidates"]
               if c["symbol"] in ("first_orphan", "second_orphan")]
    assert symbols == [], (
        f"both orphans must be LSP-verified and dropped; got {symbols} "
        "(second row was skipped after the first was removed)"
    )


def test_native_only_row_respects_safe_keep(tmp_path):
    """A native finding for a symbol grep counts as used must still pass the
    safe-keep chain before becoming a candidate row."""
    _write(tmp_path, "src/api.ts", "export function pubApi(): number {\n  return 1;\n}\n")
    _write(tmp_path, "src/app.ts", "import { pubApi } from \"./api\";\npubApi();\n")
    module = _load_module()
    records = [r for r in (module.parse_file(tmp_path.resolve(), p) for p in tmp_path.rglob("*.ts")) if r]
    native_row = {
        "symbol": "pubApi", "kind": "function", "path": "src/api.ts",
        "line": 1, "detected_by": "native:vulture",
    }
    merged = module.merge_native([], [native_row], records)
    pub = _find(merged, "pubApi")
    assert pub is not None
    assert pub["keep_class"] == "safe-keep", (
        "exported symbols found only by native tooling must never be removal candidates"
    )


def test_all_tuple_form_is_recognized(tmp_path):
    _write(
        tmp_path, "src/api.py",
        "__all__ = (\"tuple_exported\",)\n\n"
        "def tuple_exported():\n    return 1\n",
    )
    rc, envelope = _scan(tmp_path)
    row = _find(envelope["data"]["candidates"], "tuple_exported")
    assert row is not None
    assert row["keep_class"] == "safe-keep"


# ── Review-round-2 regression tests ──────────────────────────────────────────


def _parse_records(module, root: Path):
    return [
        r for r in (module.parse_file(root.resolve(), p) for p in sorted(root.rglob("*")) if p.is_file()) if r
    ]


def test_native_findings_in_test_files_are_dropped(tmp_path):
    """The native funnel must honor the same test-file invariant as classify():
    a vulture report naming a test-path symbol never becomes a candidate row."""
    _write(tmp_path, "src/mod.py", "def prod_fn():\n    return 1\n")
    _write(tmp_path, "tests/test_mod.py", "def test_mod():\n    assert True\n")
    module = _load_module()
    records = _parse_records(module, tmp_path)
    native = [
        {"symbol": "test_mod", "kind": "function", "path": "tests/test_mod.py",
         "line": 1, "detected_by": "native:vulture"},
        {"symbol": "unseen_helper", "kind": "function", "path": "tests/helpers.py",
         "line": 4, "detected_by": "native:vulture"},
    ]
    merged = module.merge_native([], native, records)
    assert merged == [], "test-path native findings must be dropped, including symbols with no parsed def"


def test_native_same_name_prod_symbol_not_classified_from_test_def(tmp_path):
    """A prod-path native row must be classified from the prod def, not from a
    same-named def that happens to live in a test file."""
    _write(tmp_path, "tests/test_a.py", "# dead-code: keep fixture\ndef shared_name():\n    return 1\n")
    _write(tmp_path, "src/b.py", "def shared_name():\n    return 2\n")
    module = _load_module()
    native = [{"symbol": "shared_name", "kind": "function", "path": "src/b.py",
               "line": 1, "detected_by": "native:vulture"}]
    merged = module.merge_native([], native, _parse_records(module, tmp_path))
    row = _find(merged, "shared_name")
    assert row is not None
    assert row["keep_class"] == "candidate", "the test file's keep marker must not leak onto the prod def"


@pytest.mark.parametrize("entry", ["bin/cli.js", "./bin/cli.js"])
def test_monorepo_package_json_entry_resolves_against_manifest_dir(tmp_path, entry):
    _write(tmp_path, "packages/cli/package.json", f'{{"name": "cli", "bin": "{entry}"}}\n')
    _write(tmp_path, "packages/cli/bin/cli.js", "function cliMain() {\n  return 1;\n}\n")
    rc, envelope = _scan(tmp_path)
    row = _find(envelope["data"]["candidates"], "cliMain")
    assert row is not None
    assert row["keep_class"] == "safe-keep"
    assert "entry" in row["keep_reason"]


def test_package_json_entry_escaping_scan_root_is_ignored(tmp_path):
    _write(tmp_path, "pkg/package.json", '{"main": "../../outside.js"}\n')
    _write(tmp_path, "pkg/lib.js", "function orphanFn() {\n  return 1;\n}\n")
    rc, envelope = _scan(tmp_path)
    assert rc == 0
    assert _find(envelope["data"]["candidates"], "orphanFn")["keep_class"] == "candidate"


@pytest.mark.parametrize(
    ("manifest", "text"),
    [
        ("pyproject.toml", '[project.scripts]\nxcmd = "pkg.mod:cliMain"\n'),
        ("pyproject.toml", '[tool.poetry.scripts]\nxcmd = "pkg.mod:cliMain"\n'),
        ("pyproject.toml", '[project.entry-points."my.plugins"]\nxcmd = "pkg.mod:cliMain [extra]"\n'),
        ("setup.cfg", "[options.entry_points]\nconsole_scripts =\n    xcmd = pkg.mod:cliMain\n"),
    ],
)
def test_python_console_script_target_is_safe_keep(tmp_path, manifest, text):
    if manifest == "pyproject.toml" and sys.version_info < (3, 11):
        pytest.skip("tomllib unavailable before Python 3.11")
    _write(tmp_path, manifest, text)
    _write(tmp_path, "pkg/mod.py", "def cliMain():\n    return 0\n\ndef orphanFn():\n    return 1\n")
    rc, envelope = _scan(tmp_path)
    cands = envelope["data"]["candidates"]
    cli = _find(cands, "cliMain")
    assert cli is not None
    assert cli["keep_class"] == "safe-keep"
    assert "entry" in cli["keep_reason"]
    assert _find(cands, "orphanFn")["keep_class"] == "candidate", "only the declared target is protected"


def test_native_only_row_in_entry_file_is_safe_keep(tmp_path):
    _write(tmp_path, "package.json", '{"bin": "bin/x.js"}\n')
    _write(tmp_path, "bin/x.js", "function cliMain() {\n  return 1;\n}\n")
    module = _load_module()
    files = [tmp_path / "package.json", tmp_path / "bin" / "x.js"]
    entries = module.collect_entry_points(tmp_path.resolve(), files)
    native = [{"symbol": "cliMain", "kind": "export", "path": "bin/x.js",
               "line": 1, "detected_by": "native:knip"}]
    merged = module.merge_native([], native, _parse_records(module, tmp_path), entries)
    assert _find(merged, "cliMain")["keep_class"] == "safe-keep"


@pytest.mark.parametrize(
    "source",
    [
        "/**\n * dead-code: keep public SDK surface\n */\nfunction f(): void {}\n",
        "/** dead-code: keep public SDK surface */\nfunction f(): void {}\n",
        "/* dead-code: keep public SDK surface */\nfunction f(): void {}\n",
    ],
)
def test_block_comment_keep_marker_is_justified(tmp_path, source):
    _write(tmp_path, "src/api.ts", source)
    rc, envelope = _scan(tmp_path)
    row = _find(envelope["data"]["candidates"], "f")
    assert row is not None
    assert row["keep_class"] == "justified"
    assert row["keep_reason"] == "public SDK surface", "comment delimiters must not leak into the reason"


def test_same_line_keep_marker_without_comment_above_is_justified(tmp_path):
    _write(tmp_path, "src/api.ts", "function f(): void {} // dead-code: keep trailing marker\n")
    rc, envelope = _scan(tmp_path)
    row = _find(envelope["data"]["candidates"], "f")
    assert row is not None
    assert row["keep_class"] == "justified"
    assert row["keep_reason"] == "trailing marker"


def test_rust_pub_and_go_capitalized_are_exported_safe_keep(tmp_path):
    _write(tmp_path, "src/lib.rs", "pub fn public_api_fn() {}\n\nfn private_fn() {}\n\npub(crate) fn crate_fn() {}\n")
    _write(tmp_path, "pkg/api.go", "package pkg\n\nfunc ExportedFn() {}\n\nfunc unexportedFn() {}\n")
    rc, envelope = _scan(tmp_path)
    cands = envelope["data"]["candidates"]
    assert _find(cands, "public_api_fn")["keep_class"] == "safe-keep"
    assert _find(cands, "ExportedFn")["keep_class"] == "safe-keep"
    assert _find(cands, "private_fn")["keep_class"] == "candidate"
    assert _find(cands, "crate_fn")["keep_class"] == "candidate", "pub(crate) is not external API"
    assert _find(cands, "unexportedFn")["keep_class"] == "candidate"


def test_dunder_methods_are_safe_keep(tmp_path):
    _write(
        tmp_path, "src/widget.py",
        "class Widget:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def orphan_method(self):\n"
        "        return 2\n",
    )
    _write(tmp_path, "src/app.py", "from src.widget import Widget\nWidget()\n")
    rc, envelope = _scan(tmp_path)
    cands = envelope["data"]["candidates"]
    for dunder in ("__init__", "__eq__"):
        row = _find(cands, dunder)
        assert row is not None
        assert row["keep_class"] == "safe-keep"
        assert "dunder" in row["keep_reason"]
    assert _find(cands, "orphan_method")["keep_class"] == "candidate"


def test_inapplicable_native_tools_are_a_designed_skip(tmp_path, monkeypatch):
    """Installed-but-inapplicable tools must not run (no warning, status stays
    ok); applicable ones still do. Every registry argv is swapped for a stub
    that exits 2, so a warning for a tool proves it ran."""
    _write(tmp_path, "src/mod.py", "def orphan():\n    return 1\n")
    stub = _stub_lsp(tmp_path, "exit 2")
    module = _load_module()
    monkeypatch.delenv("GIT_DIR", raising=False)  # in-process scan: drop the conftest guard sentinel
    monkeypatch.setattr(
        module, "NATIVE_TOOLS",
        {name: tool._replace(argv=[str(stub)]) for name, tool in module.NATIVE_TOOLS.items()},
    )

    def ran(envelope):
        return {w["message"].split()[0] for w in envelope["warnings"] if w["code"] == "native-error"}

    python_only = module.scan_root(str(tmp_path), funnel="native")
    assert ran(python_only) == {"vulture"}, "knip needs package.json, staticcheck needs go.mod"

    _write(tmp_path, "package.json", "{}\n")
    _write(tmp_path, "go.mod", "module x\n")
    all_markers = module.scan_root(str(tmp_path), funnel="native")
    assert ran(all_markers) == {"vulture", "staticcheck", "knip"}


def test_repo_with_no_applicable_native_tool_stays_ok(tmp_path, monkeypatch):
    _write(tmp_path, "src/lib.rs", "pub fn api() {}\n")
    stub = _stub_lsp(tmp_path, "exit 2")
    module = _load_module()
    monkeypatch.delenv("GIT_DIR", raising=False)  # in-process scan: drop the conftest guard sentinel
    monkeypatch.setattr(
        module, "NATIVE_TOOLS",
        {name: tool._replace(argv=[str(stub)]) for name, tool in module.NATIVE_TOOLS.items()},
    )
    envelope = module.scan_root(str(tmp_path), funnel="native")
    assert envelope["status"] == "ok"
    assert envelope["warnings"] == []


# ── Review-round-3 regression tests ──────────────────────────────────────────

# Captured from the real tools: vulture 2.16 (exit 3), staticcheck (exit 1),
# knip 6.39.0 `--reporter json` (exit 1). The parsers must accept exactly this.
VULTURE_REAL = (
    "mod.py:4: unused function 'unused_fn' (60% confidence)\n"
    "mod.py:7: unused class 'Unused' (60% confidence)\n"
    "pkg/svc.py:3: unused import 'os' (90% confidence)\n"
    "pkg/svc.py:9: unreachable code after 'return' (100% confidence)\n"
)
STATICCHECK_REAL = (
    "main.go:5:2: field unusedF is unused (U1000)\n"
    "main.go:8:13: func (*T).unusedM is unused (U1000)\n"
    "main.go:12:5: var unusedV is unused (U1000)\n"
    "main.go:14:7: const unusedC is unused (U1000)\n"
    "main.go:16:6: func unusedFn is unused (U1000)\n"
)
KNIP_REAL = json.dumps({"issues": [{
    "file": "lib.js", "binaries": [], "dependencies": [], "duplicates": [], "files": [],
    "exports": [{"name": "neverUsed", "line": 2, "col": 17, "pos": 42},
                {"name": "alsoUnused", "line": 3, "col": 14, "pos": 70}],
    "types": [{"name": "Shape", "line": 4, "col": 13, "pos": 90}],
    "unlisted": [], "unresolved": [],
}]})


def test_parse_vulture_real_format():
    rows = _load_module().parse_vulture(VULTURE_REAL)
    assert [(r["symbol"], r["kind"], r["path"], r["line"]) for r in rows] == [
        ("unused_fn", "function", "mod.py", 4),
        ("Unused", "class", "mod.py", 7),
        ("os", "import", "pkg/svc.py", 3),
    ], "unreachable-code lines carry no symbol and must be skipped"
    assert {r["detected_by"] for r in rows} == {"native:vulture"}


def test_parse_staticcheck_real_format():
    rows = _load_module().parse_staticcheck(STATICCHECK_REAL)
    assert [(r["symbol"], r["kind"], r["line"]) for r in rows] == [
        ("unusedF", "attribute", 5),
        ("unusedM", "method", 8),
        ("unusedV", "variable", 12),
        ("unusedC", "variable", 14),
        ("unusedFn", "function", 16),
    ]
    assert {r["path"] for r in rows} == {"main.go"}


def test_parse_knip_real_format():
    rows = _load_module().parse_knip(KNIP_REAL)
    assert [(r["symbol"], r["kind"], r["path"], r["line"]) for r in rows] == [
        ("neverUsed", "export", "lib.js", 2),
        ("alsoUnused", "export", "lib.js", 3),
        ("Shape", "type", "lib.js", 4),
    ]


@pytest.mark.parametrize("payload", ['{"issues": {"files": {}}}', "[]", '{"issues": [{"exports": []}]}'])
def test_parse_knip_rejects_unrecognised_shape(payload):
    with pytest.raises(ValueError):
        _load_module().parse_knip(payload)


@pytest.mark.parametrize(
    ("tool", "sample", "path", "symbol", "exit_code"),
    [
        ("vulture", VULTURE_REAL, "mod.py", "unused_fn", 3),
        ("staticcheck", STATICCHECK_REAL, "main.go", "unusedFn", 1),
        ("knip", KNIP_REAL, "lib.js", "neverUsed", 1),
    ],
)
def test_findings_exit_code_is_not_a_native_failure(
    tmp_path, tmp_path_factory, monkeypatch, tool, sample, path, symbol, exit_code
):
    """Each tool signals findings through its own exit code; that must neither
    warn nor flip the status to partial, and the rows must reach the envelope."""
    _write(tmp_path, "go.mod", "module x\n")
    _write(tmp_path, "package.json", "{}\n")
    _write(tmp_path, "mod.py", "def unused_fn():\n    return 1\n")
    stub = _stub_lsp(tmp_path_factory.mktemp("native-stub"), f"cat <<'OUT'\n{sample.rstrip()}\nOUT\nexit {exit_code}")
    module = _load_module()
    monkeypatch.delenv("GIT_DIR", raising=False)  # in-process scan: drop the conftest guard sentinel
    monkeypatch.setattr(
        module, "NATIVE_TOOLS",
        {tool: module.NATIVE_TOOLS[tool]._replace(argv=[str(stub)], applicable=lambda root, records: True)},
    )
    envelope = module.scan_root(str(tmp_path), funnel="native")
    assert envelope["status"] == "ok", envelope["warnings"]
    assert envelope["warnings"] == []
    assert envelope["data"]["funnel"] == "native+grep"
    assert _find(envelope["data"]["candidates"], symbol)["detected_by"] == f"native:{tool}"


def test_vulture_is_told_to_skip_excluded_dirs_and_rows_under_them_are_dropped():
    module = _load_module()
    argv = module.NATIVE_TOOLS["vulture"].argv
    assert "--exclude" in argv
    assert {".venv", "node_modules"} <= set(argv[argv.index("--exclude") + 1].split(","))
    native = [{"symbol": "dead", "kind": "function", "path": ".venv/lib/x.py", "line": 1,
               "detected_by": "native:vulture"}]
    assert module.merge_native([], native, []) == []


def test_native_row_is_matched_to_its_own_def_not_a_same_named_one(tmp_path):
    """Common names (`process`, `run`) recur across files: the native row for
    b.go must see b.go's keep marker, and must not fold into a.go's row."""
    _write(tmp_path, "pkg_a/a.go", "package a\n\nfunc process() {}\n")
    _write(tmp_path, "pkg_b/b.go", "package b\n\n// dead-code: keep wired up by the plugin loader\nfunc process() {}\n")
    module = _load_module()
    records = _parse_records(module, tmp_path)
    grep_row = {"symbol": "process", "kind": "function", "path": "pkg_a/a.go", "line": 3,
                "keep_class": "candidate", "keep_reason": "", "note": "", "detected_by": "grep",
                "test_only": False, "references": []}
    native = [{"symbol": "process", "kind": "function", "path": "pkg_b/b.go", "line": 4,
               "detected_by": "native:staticcheck"}]
    merged = module.merge_native([grep_row], native, records)
    assert len(merged) == 2, "b.go's finding must not be absorbed by a.go's same-named row"
    assert grep_row["detected_by"] == "grep"
    b_row = next(r for r in merged if r["path"] == "pkg_b/b.go")
    assert b_row["keep_class"] == "justified"
    assert b_row["keep_reason"] == "wired up by the plugin loader"


def test_lsp_plain_text_reply_leaves_row_unverified_and_continues(tmp_path, tmp_path_factory):
    """An unresolved anchor prints plain text with exit 0; that is not an LSP
    failure — the rest of the candidates must still be verified."""
    _write(tmp_path, "src/mod.py", "def first_orphan():\n    return 1\n\ndef second_orphan():\n    return 2\n")
    payload = (
        '{"server":"stub","analyzed_files":1,"truncated":false,'
        '"elapsed_seconds":0,"results":[{"file":"src/real_caller.py","line":3,"character":1}]}'
    )
    stub = _stub_lsp(
        tmp_path_factory.mktemp("lsp-stub"),
        'case "$*" in\n'
        '  *first_orphan*) echo "no call-hierarchy item resolved at anchor";;\n'
        f"  *) cat <<'JSON'\n{payload}\nJSON\n;;\n"
        "esac",
    )
    rc, envelope = _scan(tmp_path, "--funnel", "lsp", env=_env(SWB_DEAD_CODE_LSP_BIN=str(stub)))
    assert envelope["status"] == "ok", envelope["warnings"]
    symbols = {c["symbol"] for c in envelope["data"]["candidates"]}
    assert "first_orphan" in symbols, "unresolved anchor stays an unverified candidate"
    assert "second_orphan" not in symbols, "the pass must continue past the unresolved anchor"


def test_decorator_registered_symbols_are_safe_keep(tmp_path):
    _write(
        tmp_path, "src/cli.py",
        "import click\n\n"
        "@click.command()\n"
        "def migrate():\n    pass\n\n"
        "@register\n"
        "def hook_a():\n    pass\n\n"
        "class Box:\n"
        "    @staticmethod\n"
        "    def helper():\n        return 1\n\n"
        "    @property\n"
        "    def size(self):\n        return 2\n",
    )
    _write(
        tmp_path, "src/lib.rs",
        "#[test]\nfn adds_two() {}\n\n#[derive(Debug)]\nstruct Plain;\n\nfn bare() {}\n",
    )
    rc, envelope = _scan(tmp_path)
    cands = envelope["data"]["candidates"]
    for name in ("migrate", "hook_a", "adds_two"):
        row = _find(cands, name)
        assert row is not None and row["keep_class"] == "safe-keep", name
        assert "decorator" in row["keep_reason"]
    for name in ("helper", "size", "Plain", "bare"):
        assert _find(cands, name)["keep_class"] == "candidate", f"{name}: non-registering decorators don't protect"


def test_keep_marker_above_decorator_is_honored(tmp_path):
    _write(
        tmp_path, "src/cli.py",
        "# dead-code: keep exposed to the plugin API\n"
        "@functools.lru_cache(maxsize=None)\n"
        "def cached():\n    return 1\n",
    )
    rc, envelope = _scan(tmp_path)
    row = _find(envelope["data"]["candidates"], "cached")
    assert row["keep_class"] == "justified"
    assert row["keep_reason"] == "exposed to the plugin API"


def test_extensionless_shebang_script_counts_as_a_reference(tmp_path):
    """`bin/` executables carry no extension; a function they alone call is used."""
    _write(tmp_path, "lib/util.py", "def helper():\n    return 1\n")
    _write(tmp_path, "bin/tool", "#!/usr/bin/env python3\nfrom lib.util import helper\nhelper()\n\ndef orphan_in_script():\n    return 2\n")
    _write(tmp_path, "LICENSE", "helper — not a script, never scanned\n")
    rc, envelope = _scan(tmp_path)
    assert envelope["data"]["scanned_files"] == 2, "only the shebang script joins the scan"
    cands = envelope["data"]["candidates"]
    assert _find(cands, "helper") is None
    assert _find(cands, "orphan_in_script")["path"] == "bin/tool"


@pytest.mark.parametrize(
    ("shebang", "def_line", "symbol"),
    [
        ("#!/usr/bin/env node", "function nodeFn() {}", "nodeFn"),
        ("#!/usr/bin/ruby", "def rubyFn\nend", "rubyFn"),
        ("#!/usr/bin/python3 -u", "def pyFn():\n    pass", "pyFn"),
    ],
)
def test_shebang_interpreter_selects_def_rules(tmp_path, shebang, def_line, symbol):
    _write(tmp_path, "bin/run", f"{shebang}\n{def_line}\n")
    rc, envelope = _scan(tmp_path)
    assert _find(envelope["data"]["candidates"], symbol) is not None


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
