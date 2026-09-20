"""Shellcheck auto-discovery contract for bin/ and .githooks/ scripts (issue #641).

action-shellcheck@2.0.0 lints ANY executable, extensionless file whose shebang matches
^#! */[^ ]*/(env *)?[abk]*sh — hidden dirs included, additional_files irrelevant (its
bin/ entries compiled to find -name patterns containing '/', which never match a
basename). That dead list is removed from pr.yml; this module pins the real precondition
so an ineligible script fails CI loudly, not silently — exec-bit failures also hit Windows
checkouts that drop the bit (CI matrix is ubuntu+macos, where git preserves it)."""

import re
from pathlib import Path

import pytest

from test_bin_scripts import SCRIPTS

ROOT = Path(__file__).parent.parent
BIN = ROOT / "bin"
GITHOOKS = ROOT / ".githooks"
PR_YML = ROOT / ".github" / "workflows" / "pr.yml"

# Exact expected .githooks/ contents — a new hook cannot silently appear (or vanish) either.
HOOKS = frozenset({"commit-msg", "post-merge", "pre-commit", "pre-push"})

# The action's own shebang predicate, verbatim from its composite run step: matches
# sh/ash/bash/ksh, direct or via env. Notably does NOT match zsh or python3.
SHEBANG_RE = re.compile(r"^#! */[^ ]*/(env *)?[abk]*sh")

# python3 scripts are exempt from shellcheck (the predicate cannot match them); their hygiene
# stays pinned in tests/test_bin_scripts.py (py_compile + interpreter checks).
PYTHON_SHEBANG = "#!/usr/bin/env python3"

# (path, interpreter) for every script whose shellcheck eligibility this contract pins.
CANDIDATES = sorted(
    [(BIN / name, interp) for name, interp in SCRIPTS.items()]
    + [(GITHOOKS / name, None) for name in HOOKS],
    key=lambda c: c[0],
)
CANDIDATE_IDS = [str(path.relative_to(ROOT)) for path, _ in CANDIDATES]

# The pinned action ref whose discovery semantics SHEBANG_RE mirrors verbatim — asserting it
# forces any version bump to consciously re-check the mirrored predicate against the new source.
PINNED_ACTION = "action-shellcheck@00cae500b08a931fb5698e11e79bfbd38e612a38"

# Action inputs that would silently shrink discovery without touching eligibility — banned
# alongside additional_files. Longer alternatives first so alternation anchors correctly.
MUTE_BUTTONS_RE = re.compile(r"(?m)^\s*(ignore_paths|ignore_names|scandir|ignore)\s*:")


def test_githooks_contents_match_hooks_set() -> None:
    """Pin exact .githooks/ contents so a new hook can't silently appear or vanish."""
    on_disk = {p.name for p in GITHOOKS.iterdir() if p.is_file()}
    assert on_disk == HOOKS, f".githooks/ {sorted(on_disk)} != expected {sorted(HOOKS)}"


@pytest.mark.parametrize("path,interp", CANDIDATES, ids=CANDIDATE_IDS)
def test_shellcheck_auto_discovery_preconditions(path: Path, interp: str | None) -> None:
    """Assert the script satisfies the action's real discovery precondition."""
    rel = path.relative_to(ROOT)
    assert "." not in path.name, f"{rel}: dotted filename — auto-discovery skips extensioned files"
    assert path.stat().st_mode & 0o111, f"{rel}: no exec bit — auto-discovery requires -perm /111"
    lines = path.read_text().splitlines()
    first_line = lines[0] if lines else ""
    assert SHEBANG_RE.match(first_line) or (
        interp == "python3" and first_line == PYTHON_SHEBANG
    ), (
        f"{rel}: shebang {first_line!r} matches neither the action's family "
        f"({SHEBANG_RE.pattern!r}) nor the python3 exemption — silently unlinted"
    )


def test_pr_yml_keeps_shellcheck_job_without_additional_files() -> None:
    """Pin the job's wiring, version identity, and forbid every discovery-shrinking input."""
    text = PR_YML.read_text()
    assert PINNED_ACTION in text, (
        f"the shellcheck job must stay on the pinned {PINNED_ACTION} — SHEBANG_RE mirrors that "
        "version's discovery step verbatim; on a bump, re-verify the mirrored predicate"
    )
    assert "additional_files" not in text, (
        "additional_files is dead weight (#641): auto-discovery already covers every "
        "eligible script; eligibility is pinned by test_shellcheck_auto_discovery_preconditions"
    )
    muted = MUTE_BUTTONS_RE.findall(text)
    assert not muted, (
        f"shellcheck job sets discovery-shrinking input(s) {muted} — they silently exclude "
        "files while every eligibility assertion here stays green (#641's failure mode)"
    )
