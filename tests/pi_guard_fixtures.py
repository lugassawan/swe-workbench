"""Shared fixture set for hooks/bash_guard.sh's differential acceptance criterion:

  For this fixture set (including the backtick/$(...) vectors bash_guard.sh now closes),
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
    # backtick/$(...) rm -rf bypass vectors — the reason this fixture set exists as a
    # differential contract
    ("`rm -rf /`", True),
    ("var=`rm -rf /`", True),
    ("$(rm -rf /)", True),
    ("var=$(rm -rf /)", True),
    ("echo `rm -rf /`", True),
    ("echo $(rm -rf /)", True),
    # same bypass class: process substitution (`<(...)`/`>(...)`) has the identical "(" shape
    # and was left open by a $(-only patch
    ("<(rm -rf ~)", True),
    (">(rm -rf /)", True),
    ("echo <(rm -rf /Users/bob)", True),
    # quote-wrapped / backslash-escaped rm — found by the same review: the fast-gate case
    # used to run on pre-quote-strip text, so a quote immediately before "rm" defeated it
    ('"rm" -rf ~', True),
    ("'rm' -rf $HOME", True),
    ('bash -c "rm -rf /"', True),
    ("\\rm -rf ~", True),
    # allow-list, including legitimate backtick/$(...) subshells with no rm inside
    ("ls -la", False),
    ("rm -rf ./build", False),
    ("rm -rf node_modules", False),
    ("echo `ls`", False),
    ("x=$(date)", False),
    ("echo $(pwd)", False),
    # nested non-interactive `pi` session — the bash escape hatch around the subagent
    # dispatcher's --exclude-tools recursion guard
    ("pi -p 'review this'", True),
    ("pi --print x", True),
    ("echo $(pi -p x)", True),
    ("/usr/local/bin/pi -p x", True),
    # a separator character embedded inside a QUOTED pi argument must not be treated as a
    # segment break — this is the vector that defeated the segmenter's first version
    ('pi -m ";" -p file.txt', True),
    ('pi --system-prompt "a;b" --print', True),
    # backslash-continuation join must be parity-aware: an EVEN trailing-backslash count is
    # literal escaped backslashes, not a continuation — it must not swallow a genuinely
    # separate command (rm or pi) on the next line
    ("echo hi\\\\\nrm -rf ~", True),
    ("echo hi\\\\\npi -p x", True),
    # a backslash-ESCAPED separator between pi and its flag is a literal argument byte in
    # real bash, not a real segment break
    ('pi \\; -p "review this"', True),
    # a trailing backslash INSIDE a comment has no continuation meaning — the comment must
    # not absorb a real command on the next physical line
    ("echo a # note \\\nrm -rf ~", True),
    ("echo a # note \\\npi -p x", True),
    # a REAL (unescaped) newline INSIDE a quoted argument is a literal argument byte, not a
    # segment break — the awk record boundary must respect quote state too
    ('pi -m "a\nb" -p x', True),
    # case-insensitive command-name resolution ("Pi"/"PI" resolve to the same binary as "pi"
    # on a case-insensitive filesystem, e.g. macOS's default) must still be caught
    ("Pi -p x", True),
    # flags stay case-sensitive even though the command name doesn't — "--PRINT" is not a
    # real flag spelling
    ("Pi --PRINT x", False),
    # non-recursive pi invocations must stay allowed
    ("pi --version", False),
    ("pi list", False),
    ("git log -p && pi list", False),
]
