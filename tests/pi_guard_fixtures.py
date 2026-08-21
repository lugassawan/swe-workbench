"""Shared fixture set for hooks/bash_guard.sh's #607 acceptance criterion:

  For this fixture set (including the #401 backtick/$(...) vectors bash_guard.sh now closes),
  the verdict produced through the Pi adapter must be identical to the verdict produced by
  invoking the guard script directly with the equivalent Claude-Code-shaped payload.

A single source shared by tests/test_hooks.py (direct invocation) and
tests/test_pi_extension.py (through pi/extensions/guards.ts) — a future change to
hooks/bash_guard.sh's semantics has to update the expectation here, and both suites re-verify
against it, or CI fails on whichever one goes stale.

Each entry is (command, expect_blocked). expect_blocked=True means exit 2 + "BLOCKED" in
stderr directly, or {block: true} through the Pi adapter.
"""

BASH_GUARD_FIXTURES: list[tuple[str, bool]] = [
    ("rm -rf /", True),
    ("rm -rf ~", True),
    ("rm -rf $HOME", True),
    ("sudo rm -rf /", True),
    ("rm -rf /Users/foo", True),
    # #401 bypass vectors — the reason this fixture set exists as a differential contract
    ("`rm -rf /`", True),
    ("var=`rm -rf /`", True),
    ("$(rm -rf /)", True),
    ("var=$(rm -rf /)", True),
    ("echo `rm -rf /`", True),
    ("echo $(rm -rf /)", True),
    # allow-list, including legitimate backtick/$(...) subshells with no rm inside
    ("ls -la", False),
    ("rm -rf ./build", False),
    ("rm -rf node_modules", False),
    ("echo `ls`", False),
    ("x=$(date)", False),
]
