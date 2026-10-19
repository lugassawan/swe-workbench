"""Prose-contract fixes found in review of the redaction wiring (report-issue, capture, product-manager)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOCS = {
    "report-issue": ROOT / "commands" / "report-issue.md",
    "capture": ROOT / "commands" / "capture.md",
    "product-manager": ROOT / "agents" / "product-manager.md",
}
TIMESTAMP = "<unix-timestamp>"


def _text(name: str) -> str:
    return DOCS[name].read_text()


@pytest.mark.parametrize("name", sorted(DOCS))
def test_restored_terms_accumulate_across_redactor_reruns(name):
    assert "every earlier `--allow`" in _text(name), (
        f"{name}: a re-run must carry forward every earlier --allow term, or an earlier restore is lost"
    )


@pytest.mark.parametrize("name", sorted(DOCS))
def test_preserve_file_needs_explicit_intent_and_never_covers_machine_identifiers(name):
    text = _text(name)
    assert "must stay verbatim" in text, (
        f"{name}: .preserve is written only when the user says their wording must stay verbatim"
    )
    assert "never exempts" in text and "local paths" in text, (
        f"{name}: the prose must say a preserved span never exempts local paths, IPs or the username"
    )


def test_capture_duplicate_scan_strips_and_single_quotes_its_keywords():
    text = _text("capture")
    scan = text[text.find("**Duplicate scan.**"):text.find("**Preview gate.**")]
    assert "[a-zA-Z0-9_-]" in scan and "single-quote" in scan, (
        "keywords reach a shell command line — strip them and single-quote the search string"
    )


def test_capture_edit_loop_rewrites_the_cmd_sidecar_for_label_edits():
    text = _text("capture")
    loop = text[text.find("**Edit loop.**"):text.find("9. **File on confirm.**")]
    assert "`.cmd`" in loop, "a label edit must rewrite the .cmd sidecar or filing uses the old label"


def test_product_manager_no_longer_claims_the_search_precedes_drafting():
    assert "One cheap search before drafting" not in _text("product-manager")


@pytest.mark.parametrize("name", sorted(DOCS))
def test_cleanup_names_each_sanitized_file_exactly(name):
    """A bare '.title' substring is satisfied by '.title.draft'; pin the quoted full filenames."""
    text = _text(name)
    cleanup = text[text.find("swe-workbench-clean-state-files \""):]
    cleanup = cleanup[: cleanup.find("2>/dev/null")]
    for suffix in (".md\"", ".title\"", ".draft.md\"", ".title.draft\"", ".preserve\"", ".cmd\""):
        assert f"{TIMESTAMP}{suffix}" in cleanup, f"{name}: cleanup must name the {suffix} file exactly"
