"""Tests for runtime/comment-scan.py, the issue #546 comment-quality scanner.

Fixtures live under tests/fixtures/comment_scan/ as .diff files, never as
source files — several fixtures (commented_out.diff) *are* commented-out
code, which as a source file would make this suite fail its own gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "comment_scan"


def _load_module():
    path = ROOT / "runtime" / "comment-scan.py"
    spec = importlib.util.spec_from_file_location("comment_scan", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["comment_scan"] = module
    spec.loader.exec_module(module)
    return module


cs = _load_module()


def _scan(fixture_name):
    text = (FIXTURES / fixture_name).read_text()
    return cs.scan_diff(text)


def _detectors(findings):
    return [f.detector for f in findings]


# ── Per-detector true positives ───────────────────────────────────────────────


def test_over_cap_fires_on_long_docstring():
    findings, _ = _scan("over_cap_docstring.diff")
    assert "OVER_CAP" in _detectors(findings)
    over_cap = next(f for f in findings if f.detector == "OVER_CAP")
    assert over_cap.must_triage
    assert over_cap.path == "example.py"


def test_over_cap_fires_on_long_inline_block():
    findings, _ = _scan("over_cap_inline.diff")
    assert _detectors(findings) == ["OVER_CAP"]


def test_commented_out_fires_on_dead_code_line():
    findings, _ = _scan("commented_out.diff")
    assert _detectors(findings) == ["COMMENTED_OUT"]
    finding = findings[0]
    assert finding.must_triage
    assert "legacy_totalizer" in finding.message


def test_restates_fires_on_paraphrased_comment():
    findings, _ = _scan("restates.diff")
    assert _detectors(findings) == ["RESTATES"]
    assert findings[0].must_triage


def test_density_fires_as_informational_only():
    findings, _ = _scan("density.diff")
    assert _detectors(findings) == ["DENSITY"]
    assert not findings[0].must_triage


def test_over_cap_fires_on_leading_module_docstring():
    """A module docstring at line 1 of a new file is 'leading', but it's a
    doc comment, not a license header — the leading-of-file exemption must
    not blanket-suppress it (regression: it originally did, silencing OVER_CAP
    on the single most common real trigger case: new-file documentation)."""
    findings, _ = _scan("over_cap_leading_docstring.diff")
    assert _detectors(findings) == ["OVER_CAP"]
    assert findings[0].line == 1


def test_no_false_over_cap_across_unrelated_hunks():
    """Three single-line comments in three far-apart, unrelated hunks must
    not merge into one run just because they're adjacent in the diff *view*
    (regression: run-continuation only checked '+' kind, not line-number
    contiguity, so unrelated hunks could merge into a bogus multi-hunk OVER_CAP
    span)."""
    findings, _ = _scan("multi_hunk_no_cross_merge.diff")
    assert findings == []


def test_formula_comment_not_flagged_as_commented_out():
    """"# area = pi * r squared" fits the bare assignment shape but is an
    ordinary formula-explaining WHY-comment, not dead code (regression: the
    assignment heuristic was truly unconditional and flagged it)."""
    findings, _ = _scan("fp_formula_prose.diff")
    assert findings == []


# ── False-positive exclusion classes ──────────────────────────────────────────


def test_python_doctest_excluded_from_over_cap_and_commented_out():
    findings, _ = _scan("fp_python_doctest.diff")
    assert findings == []


def test_jsdoc_example_tag_excluded():
    findings, _ = _scan("fp_jsdoc_example.diff")
    assert findings == []


def test_go_generate_directive_excluded():
    findings, _ = _scan("fp_go_generate.diff")
    assert findings == []


def test_noqa_trailing_comment_excluded():
    findings, _ = _scan("fp_noqa.diff")
    assert findings == []


def test_license_header_excluded_from_over_cap():
    findings, _ = _scan("fp_license_header.diff")
    assert findings == []


def test_pure_rename_hunk_skipped_entirely():
    findings, coverage = _scan("fp_pure_rename.diff")
    assert findings == []
    assert coverage["scanned_files"] == 0


def test_rename_with_modification_exempts_only_the_unchanged_comment():
    """A <100% similarity rename reshows an untouched doc comment as a -/+
    pair (refactorer moves a function + its comment) — that pair must not
    be re-flagged. But the same commit also adds a genuinely new commented-
    out line with no removed-text counterpart, which must still be caught:
    exempting the whole file (the pre-fix behavior) silently defeated the
    gate on exactly the rename+modify shape refactorer's wiring depends on."""
    findings, _ = _scan("fp_rename_with_modification.diff")
    assert _detectors(findings) == ["COMMENTED_OUT"]
    assert "w := &Widget" in findings[0].message


# ── Coverage line ──────────────────────────────────────────────────────────────


def test_unsupported_extension_reported_in_coverage_not_silently_skipped():
    diff = (
        "diff --git a/main.c b/main.c\n"
        "index 1111111..2222222 100644\n"
        "--- a/main.c\n"
        "+++ b/main.c\n"
        "@@ -1,1 +1,2 @@\n"
        " int main() {}\n"
        "+// a c file, unsupported by this scanner\n"
    )
    findings, coverage = cs.scan_diff(diff)
    assert findings == []
    assert coverage["scanned_files"] == 0
    assert coverage["skipped_files"] == 1
    assert ".c" in coverage["skipped_exts"]


def test_markdown_files_excluded_without_appearing_in_coverage():
    diff = (
        "diff --git a/README.md b/README.md\n"
        "index 1111111..2222222 100644\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,2 @@\n"
        " # Title\n"
        "+some new markdown content\n"
    )
    findings, coverage = cs.scan_diff(diff)
    assert findings == []
    assert coverage["scanned_files"] == 0
    assert coverage["skipped_files"] == 0


# ── Fail-open posture ──────────────────────────────────────────────────────────


def test_main_handles_non_diff_input_without_crashing():
    """Garbage stdin (no 'diff --git' markers) parses to zero files, zero
    findings — the parser is defensive by construction, not via fail-open."""
    findings, coverage = cs.scan_diff("not a diff \x00\xff")
    assert findings == []
    assert coverage["scanned_files"] == 0


def test_main_fails_open_when_scan_diff_raises(monkeypatch, capsys):
    """Force the actual exception path: any analysis error must degrade to
    exit 0 with a printed note, never propagate and fail the verify step."""
    monkeypatch.setattr(sys, "stdin", type("F", (), {"read": lambda self: "diff --git a/x b/x\n"})())
    monkeypatch.setattr(cs, "scan_diff", lambda text: (_ for _ in ()).throw(RuntimeError("boom")))
    exit_code = cs.main()
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "degraded" in out
    assert "boom" in out


def test_generated_file_skipped():
    diff = (
        "diff --git a/gen.go b/gen.go\n"
        "index 1111111..2222222 100644\n"
        "--- a/gen.go\n"
        "+++ b/gen.go\n"
        "@@ -1,1 +1,3 @@\n"
        " package pkg\n"
        "+// Code generated by protoc-gen-go. DO NOT EDIT.\n"
        "+// x := 1\n"
    )
    findings, _ = cs.scan_diff(diff)
    assert findings == []


# ── Stable, greppable ids ──────────────────────────────────────────────────────


def test_finding_id_is_detector_path_line():
    findings, _ = _scan("commented_out.diff")
    finding = findings[0]
    assert finding.id == f"COMMENTED_OUT:{finding.path}:{finding.line}"


# ── Footer format ──────────────────────────────────────────────────────────────


def test_format_output_reports_must_triage_and_info_counts():
    findings, coverage = _scan("commented_out.diff")
    output = cs.format_output(findings, coverage)
    assert "1 must-triage" in output
    assert "INFO=0" in output
    assert "COMMENTED_OUT:example.py" in output
