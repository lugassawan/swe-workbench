"""Tests for bin/swe-workbench-result-check.

Validates a producer's envelope against a module-level schema registry and passes it
through unchanged on success — a drop-in eval "$(producer ...)" replacement (see
shared/docs/runtime-result-contract.md). Unit tests import validate_envelope/REGISTRY
directly (SourceFileLoader, mirroring test_preflight_commit_script.py's precedent);
behavioral tests drive the script as a subprocess over stdin.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-result-check"


def _load_module():
    loader = SourceFileLoader("result_check", str(SCRIPT))
    spec = importlib.util.spec_from_file_location("result_check", SCRIPT, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["result_check"] = module
    spec.loader.exec_module(module)
    return module


rc = _load_module()


def _run(args, *, stdin: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin, capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )


# ── Existence ────────────────────────────────────────────────────────────────


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-result-check must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-result-check must be executable (chmod +x)"


# ── Registry ratchet (per-producer contract, golden literal) ───


EXPECTED_REGISTRY = {
    "swb.preflight-commit/1": {
        "staged": "list[str]",
        "suspicious": "list[str]",
        "docs_only": "bool",
    },
    "swb.sweep-residuals/1": {
        "swept_worktrees": "int",
        "swept_state_files": "int",
        "swept_run_dirs": "int",
        "swept_session_files": "int",
        "retained_worktrees": "list[path_reason]",
        "failed_removals": "list[path_reason]",
        "residual_none": "bool",
    },
    "swb.pr-review-submit/1": {
        "posted_inline": "int",
        "posted_pr_level": "int",
        "deduped": "int",
        "submitted": "bool",
        "event": "str",
        "decision": "str",
        "review_url": "str",
        "blocked_by_unresolved": "int",
    },
    "swb.address-feedback-worktree-acquire/1": {
        "path": "str",
        "branch": "str",
        "reused": "bool",
        "reuse_reason": "str",
        "dirty": "bool",
        "deps_installed": "bool",
        "diverged": "bool",
    },
    "swb.address-feedback-worktree-release/1": {
        "removed": "bool",
        "branch_preserved": "bool",
        "method": "str",
    },
    "swb.handoff/1": {},
    "swb.address-feedback-fetch/1": {
        "state": "str",
        "owner": "str",
        "repo": "str",
        "author_login": "str",
        "current_user": "str",
        "pr_branch": "str",
        "base": "str",
        "head_sha": "str",
        "pr_json_path": "str",
        "threads_path": "str",
        "pr_comments_path": "str",
        "eligible_threads": "int",
        "skipped_threads_clarified": "int",
        "eligible_pr_comments": "int",
        "skipped_pr_comments": "int",
        "nothing_to_address": "bool",
        "resume_available": "bool",
    },
}


def test_registry_matches_golden_inventory():
    assert rc.REGISTRY == EXPECTED_REGISTRY, (
        "bin/swe-workbench-result-check's REGISTRY drifted from the expected schema "
        "inventory — update EXPECTED_REGISTRY here deliberately if this is an intended change"
    )


# ── Unit: validate_envelope ───────────────────────────────────────────────────


def _valid_envelope(schema="swb.preflight-commit/1", **overrides):
    base = {
        "schema": schema,
        "status": "ok",
        "data": {"staged": [], "suspicious": [], "docs_only": False},
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_valid_envelope_has_no_problems():
    assert rc.validate_envelope("swb.preflight-commit/1", _valid_envelope()) == []


def test_handoff_schema_accepts_each_subcommand_data_shape():
    for data in (
        {"checkpoint_id": "cp", "target_harness": "pi"},
        {"checkpoint": {"checkpoint_id": "cp"}},
        {"decision": "allow", "reason": "owned"},
    ):
        envelope = {
            "schema": "swb.handoff/1",
            "status": "ok",
            "data": data,
            "warnings": [],
        }
        assert rc.validate_envelope("swb.handoff/1", envelope) == []


def test_non_dict_envelope_is_rejected():
    assert rc.validate_envelope("swb.preflight-commit/1", [1, 2, 3]) != []


def test_missing_top_level_field_is_rejected():
    for key in ("schema", "status", "data", "warnings"):
        envelope = _valid_envelope()
        del envelope[key]
        problems = rc.validate_envelope("swb.preflight-commit/1", envelope)
        assert problems, f"missing {key!r} must be rejected"


def test_schema_mismatch_is_rejected():
    envelope = _valid_envelope(schema="swb.preflight-commit/2")
    problems = rc.validate_envelope("swb.preflight-commit/1", envelope)
    assert any("schema mismatch" in p for p in problems)


def test_invalid_status_is_rejected():
    envelope = _valid_envelope(status="weird")
    assert rc.validate_envelope("swb.preflight-commit/1", envelope) != []


def test_unhashable_status_is_rejected_not_crashed():
    """A list/dict status must produce a clean validation problem, not an unhandled
    TypeError from `x not in a_set` on an unhashable x."""
    for bad_status in (["ok"], {"ok": True}):
        envelope = _valid_envelope(status=bad_status)
        problems = rc.validate_envelope("swb.preflight-commit/1", envelope)
        assert problems, f"status={bad_status!r} must be rejected"
        assert any("status must be one of" in p for p in problems)


def test_each_valid_status_is_accepted():
    for status in ("ok", "partial", "failed"):
        envelope = _valid_envelope(status=status)
        assert rc.validate_envelope("swb.preflight-commit/1", envelope) == []


def test_missing_required_data_field_is_rejected():
    envelope = _valid_envelope()
    del envelope["data"]["docs_only"]
    problems = rc.validate_envelope("swb.preflight-commit/1", envelope)
    assert any("docs_only" in p for p in problems)


def test_wrong_type_data_field_is_rejected():
    envelope = _valid_envelope()
    envelope["data"]["docs_only"] = "true"  # string, not bool
    problems = rc.validate_envelope("swb.preflight-commit/1", envelope)
    assert any("docs_only" in p for p in problems)


def test_list_path_reason_field_valid_and_invalid():
    envelope = _valid_envelope(
        schema="swb.sweep-residuals/1",
        data={
            "swept_worktrees": 1, "swept_state_files": 0, "swept_run_dirs": 0,
            "swept_session_files": 0,
            "retained_worktrees": [{"path": "/tmp/x", "reason": "dirty"}],
            "failed_removals": [],
            "residual_none": False,
        },
    )
    assert rc.validate_envelope("swb.sweep-residuals/1", envelope) == []

    envelope["data"]["retained_worktrees"] = [{"path": "/tmp/x"}]  # missing reason
    assert rc.validate_envelope("swb.sweep-residuals/1", envelope) != []


def test_warnings_must_be_list_of_code_message_objects():
    envelope = _valid_envelope(warnings=[{"code": "x"}])  # missing message
    assert rc.validate_envelope("swb.preflight-commit/1", envelope) != []

    envelope = _valid_envelope(warnings=[{"code": "x", "message": "y"}])
    assert rc.validate_envelope("swb.preflight-commit/1", envelope) == []

    envelope = _valid_envelope(warnings="not-a-list")
    assert rc.validate_envelope("swb.preflight-commit/1", envelope) != []


def test_bool_is_not_accepted_as_int():
    """A JSON `true`/`false` must never satisfy an int-typed field — bool is a Python
    int subclass, so this guards against a naive isinstance(value, int) check."""
    envelope = _valid_envelope(
        schema="swb.pr-review-submit/1",
        data={
            "posted_inline": True, "posted_pr_level": 0, "deduped": 0,
            "submitted": True, "event": "COMMENT", "decision": "COMMENT",
            "review_url": "", "blocked_by_unresolved": 0,
        },
    )
    problems = rc.validate_envelope("swb.pr-review-submit/1", envelope)
    assert any("posted_inline" in p for p in problems)


# ── Behavioral ───────────────────────────────────────────────────────────────


def test_valid_envelope_passes_through_unchanged_exit_0():
    envelope = _valid_envelope()
    result = _run(["swb.preflight-commit/1"], stdin=json.dumps(envelope))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == envelope


def test_handoff_envelope_passes_through_the_cli_unchanged():
    envelope = {
        "schema": "swb.handoff/1",
        "status": "ok",
        "data": {"checkpoint_id": "01992e64-4cc8-7000-8000-000000000001"},
        "warnings": [],
    }
    result = _run(["swb.handoff/1"], stdin=json.dumps(envelope))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == envelope


def test_missing_schema_arg_exits_nonzero_empty_stdout():
    result = _run([], stdin="{}")
    assert result.returncode != 0
    assert result.stdout == ""


def test_unknown_schema_arg_exits_nonzero_empty_stdout():
    result = _run(["swb.does-not-exist/1"], stdin=json.dumps(_valid_envelope()))
    assert result.returncode != 0
    assert result.stdout == ""


def test_malformed_json_exits_nonzero_empty_stdout():
    result = _run(["swb.preflight-commit/1"], stdin="{not valid json")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip() != ""


def test_empty_stdin_exits_nonzero_empty_stdout():
    result = _run(["swb.preflight-commit/1"], stdin="")
    assert result.returncode != 0
    assert result.stdout == ""


def test_missing_required_field_behavioral_exits_nonzero_empty_stdout():
    envelope = _valid_envelope()
    del envelope["data"]["staged"]
    result = _run(["swb.preflight-commit/1"], stdin=json.dumps(envelope))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "staged" in result.stderr


def test_unhashable_status_behavioral_exits_cleanly_no_traceback():
    envelope = _valid_envelope(status=["ok"])
    result = _run(["swb.preflight-commit/1"], stdin=json.dumps(envelope))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "status must be one of" in result.stderr


def test_wrong_type_behavioral_exits_nonzero_empty_stdout():
    envelope = _valid_envelope()
    envelope["data"]["suspicious"] = "not-a-list"
    result = _run(["swb.preflight-commit/1"], stdin=json.dumps(envelope))
    assert result.returncode != 0
    assert result.stdout == ""


def test_schema_major_version_mismatch_exits_nonzero():
    """The ticket's required backward-incompatible-change test: a producer that still
    declares an old major version must be rejected outright, not silently accepted."""
    envelope = _valid_envelope(schema="swb.preflight-commit/2")
    result = _run(["swb.preflight-commit/1"], stdin=json.dumps(envelope))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "schema mismatch" in result.stderr


def test_special_characters_round_trip_in_string_data_fields():
    envelope = _valid_envelope(
        schema="swb.pr-review-submit/1",
        data={
            "posted_inline": 1, "posted_pr_level": 0, "deduped": 0,
            "submitted": True, "event": "COMMENT", "decision": "COMMENT",
            "review_url": "quote\" backslash\\ newline\n tab\t done",
            "blocked_by_unresolved": 0,
        },
    )
    result = _run(["swb.pr-review-submit/1"], stdin=json.dumps(envelope))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["review_url"] == envelope["data"]["review_url"]


def test_every_nonzero_exit_pairs_with_empty_stdout():
    """Structural sweep over every failure case above — the envelope contract's own
    invariant (exit code and stdout trust are orthogonal) must hold for every path."""
    cases = [
        ([], "{}"),
        (["swb.does-not-exist/1"], json.dumps(_valid_envelope())),
        (["swb.preflight-commit/1"], "{not valid json"),
        (["swb.preflight-commit/1"], ""),
    ]
    for args, stdin in cases:
        result = _run(args, stdin=stdin)
        assert result.returncode != 0, f"expected non-zero exit for args={args!r}"
        assert result.stdout == "", f"expected empty stdout for args={args!r}, got {result.stdout!r}"
