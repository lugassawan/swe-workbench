"""Tests for runtime/new-run-dir.sh — run-scoped scratch directory allocation.

Mirrors tests/test_reap_run_dir.py and tests/test_clean_ephemeral.py. Each
test invokes the script as a subprocess and parses its `RUN_DIR=<path>`
stdout contract.

Exit code 0 + `RUN_DIR=<path>` printed -> allocation succeeded.
Exit code 1                            -> rejected invocation.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "runtime" / "new-run-dir.sh"
REPO_ROOT = Path(__file__).parent.parent

RUN_ROOT = Path("/tmp/swe-workbench-run")

_RUN_DIR_RE = re.compile(r"^RUN_DIR=(.+)$", re.MULTILINE)


def run_script(*args: str, env=None):
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
        env=merged_env,
    )


def parse_run_dir(stdout: str) -> str:
    m = _RUN_DIR_RE.search(stdout)
    assert m, f"expected RUN_DIR=<path> in stdout, got: {stdout!r}"
    return m.group(1).strip()


@pytest.fixture(autouse=True)
def _clean_run_root():
    """Each test leaves the shared run root clean for the next test."""
    yield
    if RUN_ROOT.exists():
        import shutil
        for entry in RUN_ROOT.iterdir():
            shutil.rmtree(entry, ignore_errors=True)


# ──────────────────────────────────────────────────────
# Script existence
# ──────────────────────────────────────────────────────

def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"


# ──────────────────────────────────────────────────────
# Happy path — allocation
# ──────────────────────────────────────────────────────

def test_allocates_run_dir_for_pr_review():
    result = run_script("pr-review", "42")
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    run_dir = Path(parse_run_dir(result.stdout))
    assert run_dir.is_dir(), "RUN_DIR must exist as a directory"
    assert run_dir.name.startswith("pr-review-42-")
    assert re.fullmatch(r"pr-review-42-[A-Za-z0-9]{6}", run_dir.name)


def test_run_dir_mode_is_0700():
    result = run_script("capture", "1")
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    run_dir = Path(parse_run_dir(result.stdout))
    mode = run_dir.stat().st_mode & 0o777
    assert mode == 0o700, f"expected mode 0700, got {oct(mode)}"


@pytest.mark.parametrize("prefix", [
    "pr-review", "pr-followup", "address-feedback", "review-security",
    "review-general", "extend", "capture", "audit-emit", "hotfix",
])
def test_accepts_all_flow_prefixes(prefix):
    result = run_script(prefix, "7")
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    run_dir = Path(parse_run_dir(result.stdout))
    assert run_dir.is_dir()


# ──────────────────────────────────────────────────────
# Rejection — invalid arguments
# ──────────────────────────────────────────────────────

def test_rejects_unknown_prefix():
    result = run_script("not-a-flow", "1")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_rejects_review_prefix_with_uppercase():
    result = run_script("review-Security", "1")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_rejects_non_numeric_id():
    result = run_script("pr-review", "abc")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_rejects_missing_id():
    result = run_script("pr-review")
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


def test_rejects_no_args():
    result = run_script()
    assert result.returncode != 0, f"stderr: {result.stderr!r}"


# ──────────────────────────────────────────────────────
# Concurrency — two allocations for the same PR are distinct
# ──────────────────────────────────────────────────────

def test_two_allocations_for_same_pr_are_distinct():
    """mktemp -d's O_EXCL creation must produce two different directories for
    the same (prefix, id) pair — this is what makes two concurrent review
    passes on one PR safe from collision."""
    r1 = run_script("pr-review", "42")
    r2 = run_script("pr-review", "42")
    assert r1.returncode == 0 and r2.returncode == 0
    d1 = Path(parse_run_dir(r1.stdout))
    d2 = Path(parse_run_dir(r2.stdout))
    assert d1 != d2
    assert d1.is_dir() and d2.is_dir()


# ──────────────────────────────────────────────────────
# Age-gated orphan sweep
# ──────────────────────────────────────────────────────

def _make_backdated_dir(name: str, age_hours: float) -> Path:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    d = RUN_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    backdated = time.time() - age_hours * 3600
    os.utime(d, (backdated, backdated))
    return d


def test_sweeps_orphan_older_than_24h():
    old = _make_backdated_dir("pr-review-99-old25h", 25)
    result = run_script("capture", "1")
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert not old.exists(), "25h-old orphan must be swept"


def test_survives_orphan_younger_than_24h():
    young = _make_backdated_dir("pr-review-98-yng23h", 23)
    result = run_script("capture", "1")
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    assert young.exists(), "23h-old dir must survive (below the 24h threshold)"
    import shutil
    shutil.rmtree(young, ignore_errors=True)


def test_sweep_never_touches_pr_review_state_dir():
    """The age-gated sweep is scoped to /tmp/swe-workbench-run/ only — it must
    never reach into /tmp/swe-workbench-pr-review/, whose *-triage.json resume
    points are meant to outlive a day by design."""
    pr_review_dir = Path("/tmp/swe-workbench-pr-review")
    pr_review_dir.mkdir(exist_ok=True)
    sentinel = pr_review_dir / "999-triage.json"
    sentinel.write_text("{}")
    old_epoch = time.time() - 48 * 3600
    os.utime(sentinel, (old_epoch, old_epoch))
    try:
        result = run_script("capture", "1")
        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert sentinel.exists(), "sweep must never reach /tmp/swe-workbench-pr-review/"
    finally:
        sentinel.unlink(missing_ok=True)
