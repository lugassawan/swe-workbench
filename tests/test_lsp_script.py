"""Tests for bin/swe-workbench-lsp.

CI has no real language servers, so behavioral tests drive a fake one — a
tmp_path script speaking the same Content-Length JSON-RPC framing — swapped
in via monkeypatching LANGUAGE_SERVERS (test_pr_review_submit_script.py's
PATH-scoped `gh`-stub convention, adapted to a subprocess-command swap).
Pure helpers are unit tested via that file's importlib pattern.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-lsp"

FAKE_SERVER_BODY = '''#!/usr/bin/env python3
import json, os, sys

LOG = os.environ.get("FAKE_LSP_LOG")
REFS_MODE = os.environ.get("FAKE_LSP_REFS_MODE", "empty")
DELAY_METHOD = os.environ.get("FAKE_LSP_DELAY_METHOD")
ERROR_METHOD = os.environ.get("FAKE_LSP_ERROR_METHOD")


def log(event):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(event + "\\n")


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.rstrip(b"\\r\\n")
        if line == b"":
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get(b"content-length", b"0"))
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def send(obj):
    data = json.dumps(obj).encode("utf-8")
    header = ("Content-Length: %d\\r\\n\\r\\n" % len(data)).encode("ascii")
    sys.stdout.buffer.write(header + data)
    sys.stdout.buffer.flush()


while True:
    msg = read_message()
    if msg is None:
        break
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "exit":
        break
    if method and method == DELAY_METHOD:
        continue
    if method and method == ERROR_METHOD and msg_id is not None:
        send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": "fake server error"}})
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {"capabilities": {}}})
    elif method == "textDocument/didOpen":
        uri = msg.get("params", {}).get("textDocument", {}).get("uri", "")
        log(f"didOpen {uri}")
    elif method == "textDocument/references":
        if REFS_MODE == "empty":
            send({"jsonrpc": "2.0", "id": msg_id, "result": []})
        else:
            send({"jsonrpc": "2.0", "id": msg_id, "result": [
                {"uri": "file:///tmp/fake_target.py",
                 "range": {"start": {"line": 4, "character": 2}, "end": {"line": 4, "character": 6}}},
            ]})
    elif method == "textDocument/definition":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {
            "uri": "file:///tmp/fake_def.py",
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
        }})
    elif method == "textDocument/prepareCallHierarchy":
        send({"jsonrpc": "2.0", "id": msg_id, "result": [{
            "name": "target", "kind": 12, "uri": "file:///tmp/fake_item.py",
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 6}},
            "selectionRange": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 6}},
        }]})
    elif method == "callHierarchy/incomingCalls":
        send({"jsonrpc": "2.0", "id": msg_id, "result": [{
            "from": {
                "name": "caller_fn", "kind": 12, "uri": "file:///tmp/fake_caller.py",
                "range": {"start": {"line": 7, "character": 0}, "end": {"line": 7, "character": 9}},
                "selectionRange": {"start": {"line": 7, "character": 4}, "end": {"line": 7, "character": 13}},
            },
            "fromRanges": [{"start": {"line": 8, "character": 4}, "end": {"line": 8, "character": 10}}],
        }]})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": msg_id, "result": None})
    elif msg_id is not None:
        send({"jsonrpc": "2.0", "id": msg_id, "result": None})
'''


def _load_module():
    loader = SourceFileLoader("swe_workbench_lsp", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("swe_workbench_lsp", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["swe_workbench_lsp"] = module
    spec.loader.exec_module(module)
    return module


lsp = _load_module()


def _args(**kw):
    defaults = dict(anchor=None, symbol=None, json=False, timeout=5.0, max_files=40, root=None,
                     file=None, query=None, ext=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


@pytest.fixture
def fake_server(tmp_path_factory):
    """A directory independent of any given test's own tmp_path — otherwise
    the fake server's own source (which legitimately contains words like
    "target" in its canned responses) would sit inside the prefilter's
    search root and inflate analyzed-file counts in file-count-sensitive
    assertions."""
    d = tmp_path_factory.mktemp("fake_server")
    path = d / "fake_server.py"
    path.write_text(FAKE_SERVER_BODY, encoding="utf-8")
    return path


@pytest.fixture
def use_fake_server(monkeypatch, fake_server):
    """Redirect .py's registered server to the fake server for this test."""
    fake_spec = lsp.ServerSpec("fake-server", (sys.executable, str(fake_server)))
    monkeypatch.setitem(lsp.LANGUAGE_SERVERS, ".py", fake_spec)
    return fake_spec


# ── Pure helpers ─────────────────────────────────────────────────────────────


class TestParseAnchor:
    def test_bare_path(self):
        assert lsp._parse_anchor("foo/bar.py") == ("foo/bar.py", None, None)

    def test_path_with_line(self):
        assert lsp._parse_anchor("foo/bar.py:42") == ("foo/bar.py", 42, None)

    def test_path_with_line_and_col(self):
        assert lsp._parse_anchor("foo/bar.py:42:7") == ("foo/bar.py", 42, 7)


class TestResolvePosition:
    def test_symbol_no_line_searches_whole_file(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("x = 1\ndef target():\n    pass\n", encoding="utf-8")
        line0, col0 = lsp._resolve_position(f, None, None, "target")
        assert (line0, col0) == (1, 4)

    def test_symbol_with_line_restricts_search(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("target = 1\ndef other():\n    return target\n", encoding="utf-8")
        line0, col0 = lsp._resolve_position(f, 3, None, "target")
        assert (line0, col0) == (2, 11)

    def test_symbol_not_found_raises(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(lsp.AnchorError):
            lsp._resolve_position(f, None, None, "missing_symbol")

    def test_explicit_line_col(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("abcdef\n", encoding="utf-8")
        assert lsp._resolve_position(f, 1, 3, None) == (0, 2)

    def test_line_out_of_range_raises(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("one line\n", encoding="utf-8")
        with pytest.raises(lsp.AnchorError):
            lsp._resolve_position(f, 99, None, None)

    def test_no_line_no_symbol_raises(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(lsp.AnchorError):
            lsp._resolve_position(f, None, None, None)


class TestWordAt:
    def test_extracts_identifier_under_cursor(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("result = compute_total(x)\n", encoding="utf-8")
        assert lsp._word_at(f, 0, 10) == "compute_total"

    def test_no_identifier_raises(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("x = 1 + 2\n", encoding="utf-8")
        with pytest.raises(lsp.AnchorError):
            lsp._word_at(f, 0, 6)  # the '+' character


class TestPrefilter:
    def test_seeds_from_matching_files_only(self, tmp_path):
        (tmp_path / "a.py").write_text("def needle(): pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("needle()\n", encoding="utf-8")
        (tmp_path / "c.py").write_text("no match here\n", encoding="utf-8")
        matches, truncated = lsp._prefilter(tmp_path, "needle", {".py"}, None, 40)
        assert {p.name for p in matches} == {"a.py", "b.py"}
        assert truncated is False

    def test_excludes_anchor_file(self, tmp_path):
        anchor = tmp_path / "a.py"
        anchor.write_text("def needle(): pass\n", encoding="utf-8")
        matches, _truncated = lsp._prefilter(tmp_path, "needle", {".py"}, anchor, 40)
        assert anchor not in matches

    def test_respects_max_files_cap_and_reports_truncation(self, tmp_path):
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("needle\n", encoding="utf-8")
        matches, truncated = lsp._prefilter(tmp_path, "needle", {".py"}, None, 2)
        assert len(matches) == 2
        assert truncated is True

    def test_word_boundary_does_not_match_substring(self, tmp_path):
        (tmp_path / "a.py").write_text("needleworks = 1\n", encoding="utf-8")
        matches, _truncated = lsp._prefilter(tmp_path, "needle", {".py"}, None, 40)
        assert matches == []

    def test_excludes_vendor_directories(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.py").write_text("needle\n", encoding="utf-8")
        (tmp_path / "real.py").write_text("needle\n", encoding="utf-8")
        matches, _truncated = lsp._prefilter(tmp_path, "needle", {".py"}, None, 40)
        assert {p.name for p in matches} == {"real.py"}


class TestNormalizeLocations:
    def test_none_returns_empty(self):
        assert lsp._normalize_locations(None) == []

    def test_single_location_dict(self):
        loc = {"uri": "file:///a.py", "range": {"start": {"line": 3, "character": 5}, "end": {}}}
        assert lsp._normalize_locations(loc) == [("file:///a.py", 3, 5)]

    def test_location_list(self):
        locs = [
            {"uri": "file:///a.py", "range": {"start": {"line": 1, "character": 0}}},
            {"uri": "file:///b.py", "range": {"start": {"line": 2, "character": 1}}},
        ]
        assert lsp._normalize_locations(locs) == [("file:///a.py", 1, 0), ("file:///b.py", 2, 1)]

    def test_location_link_uses_target_selection_range(self):
        link = {
            "targetUri": "file:///a.py",
            "targetRange": {"start": {"line": 9, "character": 9}},
            "targetSelectionRange": {"start": {"line": 4, "character": 2}},
        }
        assert lsp._normalize_locations(link) == [("file:///a.py", 4, 2)]


class TestFlattenSymbols:
    def test_hierarchical_symbols_flatten_with_depth(self):
        tree = [{
            "name": "Outer", "kind": 5, "selectionRange": {"start": {"line": 0, "character": 0}},
            "children": [
                {"name": "inner", "kind": 6, "selectionRange": {"start": {"line": 1, "character": 4}}},
            ],
        }]
        flat = lsp._flatten_symbols(tree)
        assert [(d, n) for d, n, _k, _l, _u in flat] == [(0, "Outer"), (1, "inner")]

    def test_flat_symbol_information(self):
        flat_syms = [{"name": "foo", "kind": 12, "location": {"uri": "file:///a.py", "range": {"start": {"line": 5, "character": 0}}}}]
        flat = lsp._flatten_symbols(flat_syms)
        assert flat == [(0, "foo", 12, 5, "file:///a.py")]


class TestHoverText:
    def test_string_contents(self):
        assert lsp._hover_text("plain text") == "plain text"

    def test_markup_content_dict(self):
        assert lsp._hover_text({"kind": "markdown", "value": "**bold**"}) == "**bold**"

    def test_none_contents(self):
        assert lsp._hover_text(None) is None


# ── Protocol / behavioral tests (fake server subprocess) ───────────────────


def test_protocol_framing_round_trip(tmp_path, use_fake_server):
    """A full initialize -> definition -> shutdown round trip against a real
    subprocess speaking Content-Length framing — proves the client's framing,
    not just its data shaping."""
    anchor = tmp_path / "m.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="target", root=str(tmp_path))
    rc = lsp.cmd_def(args)
    assert rc == lsp.EXIT_OK


def test_prefilter_seeds_didopen_for_every_candidate(tmp_path, use_fake_server, monkeypatch):
    """Regression test for the empty-result trap: refs must didOpen every
    prefiltered candidate file, not just the anchor — the exact gap the
    plan's dogfood run found (0 sites without prefilter, 136 with it)."""
    log_file = tmp_path / "didopen.log"
    monkeypatch.setenv("FAKE_LSP_LOG", str(log_file))
    monkeypatch.setenv("FAKE_LSP_REFS_MODE", "empty")

    anchor = tmp_path / "anchor.py"
    anchor.write_text("def needle():\n    pass\n", encoding="utf-8")
    (tmp_path / "caller_a.py").write_text("needle()\n", encoding="utf-8")
    (tmp_path / "caller_b.py").write_text("needle()\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("x = 1\n", encoding="utf-8")

    args = _args(anchor=f"{anchor}:1", symbol="needle", root=str(tmp_path))
    rc = lsp.cmd_refs(args)
    assert rc == lsp.EXIT_OK

    opened = log_file.read_text(encoding="utf-8").splitlines()
    assert len(opened) == 3  # anchor.py + caller_a.py + caller_b.py, never unrelated.py
    assert any("anchor.py" in line for line in opened)
    assert any("caller_a.py" in line for line in opened)
    assert any("caller_b.py" in line for line in opened)
    assert not any("unrelated.py" in line for line in opened)


def test_empty_result_still_emits_provenance_line(tmp_path, use_fake_server, monkeypatch, capsys):
    """The dangerous-empty guard: a genuine zero-result refs call must never
    print a bare empty output — the provenance line proves the run happened."""
    monkeypatch.setenv("FAKE_LSP_REFS_MODE", "empty")
    anchor = tmp_path / "anchor.py"
    anchor.write_text("def lonely():\n    pass\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="lonely", root=str(tmp_path))
    rc = lsp.cmd_refs(args)
    assert rc == lsp.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("server: fake-server | analyzed:")
    assert "0 site(s) in 0 file(s)" in out


def test_refs_with_results_reports_them(tmp_path, use_fake_server, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_LSP_REFS_MODE", "hit")
    anchor = tmp_path / "anchor.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="target", root=str(tmp_path))
    rc = lsp.cmd_refs(args)
    assert rc == lsp.EXIT_OK
    out = capsys.readouterr().out
    assert "1 site(s) in 1 file(s)" in out


def test_json_shape(tmp_path, use_fake_server, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_LSP_REFS_MODE", "hit")
    anchor = tmp_path / "anchor.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="target", root=str(tmp_path), json=True)
    rc = lsp.cmd_refs(args)
    assert rc == lsp.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["server"] == "fake-server"
    assert payload["analyzed_files"] == 1
    assert payload["truncated"] is False
    assert isinstance(payload["elapsed_seconds"], float)
    assert payload["results"] == [{"file": "/tmp/fake_target.py", "line": 5, "character": 3}]


def test_exit_3_when_no_server_registered_for_extension(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# nothing here\n", encoding="utf-8")
    result = subprocess.run(
        [str(SCRIPT), "refs", str(readme), "--symbol", "anything"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == lsp.EXIT_NO_SERVER


def test_exit_3_when_server_binary_missing_from_path(tmp_path, monkeypatch):
    monkeypatch.setitem(lsp.LANGUAGE_SERVERS, ".py", lsp.ServerSpec("nonexistent-server", ("swe-workbench-lsp-nonexistent-binary",)))
    anchor = tmp_path / "m.py"
    anchor.write_text("x = 1\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="x", root=str(tmp_path))
    with pytest.raises(lsp.ServerUnavailable):
        lsp.cmd_def(args)


def test_exit_4_on_timeout(tmp_path, use_fake_server, monkeypatch):
    monkeypatch.setenv("FAKE_LSP_DELAY_METHOD", "textDocument/definition")
    anchor = tmp_path / "m.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="target", root=str(tmp_path), timeout=0.5)
    with pytest.raises(lsp.LspTimeout):
        lsp.cmd_def(args)


def test_main_maps_timeout_to_exit_4(tmp_path, use_fake_server, monkeypatch):
    monkeypatch.setenv("FAKE_LSP_DELAY_METHOD", "textDocument/definition")
    anchor = tmp_path / "m.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    rc = lsp.main(["def", f"{anchor}:1", "--symbol", "target", "--root", str(tmp_path), "--timeout", "0.5"])
    assert rc == lsp.EXIT_TIMEOUT


def test_check_reports_missing_and_present_servers(capsys, monkeypatch):
    monkeypatch.setattr(lsp.shutil, "which", lambda name: "/usr/bin/" + name if name == "gopls" else None)
    args = _args()
    rc = lsp.cmd_check(args)
    assert rc == lsp.EXIT_OK
    out = capsys.readouterr().out
    assert "OK       gopls" in out
    assert "MISSING  pyright-langserver" in out


def test_callers_walks_call_hierarchy_with_prefilter(tmp_path, use_fake_server, monkeypatch):
    """The plan's central risk scenario (a refactorer deciding whether a
    rename is safe) runs through `callers`, not `refs` — cover its own
    prepareCallHierarchy -> incomingCalls round trip and "from" key
    selection, not just the shared pure helpers."""
    log_file = tmp_path / "didopen.log"
    monkeypatch.setenv("FAKE_LSP_LOG", str(log_file))
    anchor = tmp_path / "anchor.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text("target()\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="target", root=str(tmp_path))
    rc = lsp.cmd_callers(args)
    assert rc == lsp.EXIT_OK
    opened = log_file.read_text(encoding="utf-8").splitlines()
    assert any("caller.py" in line for line in opened)


def test_callees_skips_prefilter(tmp_path, use_fake_server, monkeypatch):
    log_file = tmp_path / "didopen.log"
    monkeypatch.setenv("FAKE_LSP_LOG", str(log_file))
    anchor = tmp_path / "anchor.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("target\n", encoding="utf-8")
    args = _args(anchor=f"{anchor}:1", symbol="target", root=str(tmp_path))
    rc = lsp.cmd_callees(args)
    assert rc == lsp.EXIT_OK
    opened = log_file.read_text(encoding="utf-8").splitlines()
    assert not any("unrelated.py" in line for line in opened)


def test_exit_5_on_server_error_response(tmp_path, use_fake_server, monkeypatch):
    monkeypatch.setenv("FAKE_LSP_ERROR_METHOD", "textDocument/definition")
    anchor = tmp_path / "m.py"
    anchor.write_text("def target():\n    pass\n", encoding="utf-8")
    rc = lsp.main(["def", f"{anchor}:1", "--symbol", "target", "--root", str(tmp_path)])
    assert rc == lsp.EXIT_SERVER_ERROR


def test_spawn_failure_on_init_does_not_leak_subprocess(tmp_path, use_fake_server, monkeypatch):
    """Regression test for the leak both independent reviews converged on:
    _spawn_and_init must close the just-spawned server if the handshake
    itself (not just a later command request) fails."""
    monkeypatch.setenv("FAKE_LSP_DELAY_METHOD", "initialize")
    spec = lsp.LANGUAGE_SERVERS[".py"]
    closed = []
    real_close = lsp.LspClient.close

    def spy_close(self):
        closed.append(self.proc.pid)
        real_close(self)

    monkeypatch.setattr(lsp.LspClient, "close", spy_close)
    with pytest.raises(lsp.LspTimeout):
        lsp._spawn_and_init(spec, tmp_path, 0.5)
    assert len(closed) == 1
