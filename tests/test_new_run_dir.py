"""Tests for bin/swe-workbench-new-run-dir — run-scoped scratch directory allocation.

Mirrors tests/test_reap_run_dir.py and tests/test_clean_ephemeral.py. Each
test invokes the script as a subprocess and reads its bare-path stdout contract
(Tier S per shared/docs/runtime-result-contract.md — a single trusted scalar,
no envelope, no eval; a caller reads it as `RUN_DIR=$(swe-workbench-new-run-dir ...)`).

Exit code 0 + the bare path printed -> allocation succeeded.
Exit code 1                         -> rejected invocation.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "bin" / "swe-workbench-new-run-dir"
REPO_ROOT = Path(__file__).parent.parent

RUN_ROOT = Path("/tmp/swe-workbench-run")


def run_script(*args: str, env=None, cwd=None):
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=merged_env,
    )


def parse_run_dir(stdout: str) -> str:
    path = stdout.strip()
    assert path, f"expected a bare path in stdout, got: {stdout!r}"
    return path


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
    # cwd=REPO_ROOT has an origin remote, so no-flag allocation auto-scopes
    # (issue #713): pr-review-<owner-repo-slug>-42-XXXXXX.
    assert run_dir.name.startswith("pr-review-")
    assert re.fullmatch(r"pr-review-[a-zA-Z0-9._-]+-42-[A-Za-z0-9]{6}", run_dir.name)


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


def test_accepts_hyphenated_review_mode():
    """A hyphenated specialist mode name (e.g. contributor-trust) must be
    accepted, not just single-word modes — commands/review.md's postable-mode
    table includes hyphenated normalized names."""
    result = run_script("review-contributor-trust", "42")
    assert result.returncode == 0, f"stderr: {result.stderr!r}"
    run_dir = Path(parse_run_dir(result.stdout))
    assert run_dir.is_dir()


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


# ──────────────────────────────────────────────────────
# Repo-scoped allocation (issue #713)
# ──────────────────────────────────────────────────────

def test_allocation_with_explicit_repo_embeds_slug():
    r = run_script("pr-review", "42", "--repo", "octocat/widgets")
    assert r.returncode == 0, f"stderr: {r.stderr!r}"
    base = os.path.basename(parse_run_dir(r.stdout))
    assert re.fullmatch(r"pr-review-octocat-widgets-42-[A-Za-z0-9]{6}", base)


def test_allocation_without_repo_uses_origin_slug():
    # cwd=REPO_ROOT has an origin remote -> auto-scoped allocation.
    r = run_script("pr-review", "42")
    assert r.returncode == 0, f"stderr: {r.stderr!r}"
    base = os.path.basename(parse_run_dir(r.stdout))
    assert re.fullmatch(r"pr-review-[a-zA-Z0-9._-]+-42-[A-Za-z0-9]{6}", base)
    # The slug segment is a real owner-repo pair (contains the repo's own
    # name), not just any charset run.
    assert "swe-workbench" in base


def test_allocation_falls_back_to_legacy_naming_outside_git(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    r = run_script("pr-review", "42", cwd=d)
    assert r.returncode == 0, f"stderr: {r.stderr!r}"
    base = os.path.basename(parse_run_dir(r.stdout))
    assert re.fullmatch(r"pr-review-42-[A-Za-z0-9]{6}", base)


def test_invalid_repo_value_rejected():
    r = run_script("pr-review", "42", "--repo", "not-a-scope")
    assert r.returncode == 1
    assert "invalid --repo value" in r.stderr


def test_repo_flag_requires_value():
    r = run_script("pr-review", "42", "--repo")
    assert r.returncode == 1


def test_unexpected_third_argument_rejected():
    r = run_script("pr-review", "42", "bogus")
    assert r.returncode == 1
    assert "unexpected argument" in r.stderr


def test_orphan_sweep_reaps_slugged_shape():
    # Slugged-name dir older than the sweep threshold is reaped at allocation.
    stale = RUN_ROOT / "pr-review-octocat-widgets-42-zzzzzz"
    stale.mkdir(parents=True, exist_ok=True)
    old = time.time() - 25 * 3600
    os.utime(stale, (old, old))
    r = run_script("pr-review", "43", "--repo", "octocat/widgets")
    assert r.returncode == 0, f"stderr: {r.stderr!r}"
    assert not stale.exists()
