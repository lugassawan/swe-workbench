"""Tests for hooks/hooks.json regex blockers (issue #81).

Each of the three embedded grep -Eq patterns is extracted from the real
hooks.json and tested with subprocess.run(["grep", "-Eq", ...]) — the same
regex engine the hook uses — so platform-specific POSIX character classes
(e.g. [[:space:]]) behave identically.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

HOOKS_PATH = Path(__file__).parent.parent / "hooks" / "hooks.json"


@pytest.fixture(scope="module")
def hook_patterns():
    """Return the list of grep -Eq patterns extracted from hooks.json in order."""
    data = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    patterns = re.findall(r"grep -Eq '([^']+)'", command)
    assert len(patterns) == 4, f"Expected 4 patterns, found {len(patterns)}: {patterns}"
    return patterns


def grep_matches(pattern: str, text: str) -> bool:
    """Return True if *text* matches *pattern* using grep -Eq."""
    result = subprocess.run(
        ["grep", "-Eq", pattern],
        input=text,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


# ──────────────────────────────────────────────
# Pattern 0 — destructive rm against root or home
# ──────────────────────────────────────────────

class TestRmRfBlocker:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -rf $HOME",
        "rm -rf ~",
        "rm -rf /*",
        "sudo rm -rf /",
    ])
    def test_blocked(self, hook_patterns, cmd):
        assert grep_matches(hook_patterns[0], cmd), f"Expected BLOCK for: {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        "rm -rf ./build",
        "rm -rf node_modules",
        "rm -rf /tmp/foo",
        "rm -f somefile",
        "rm -r ./dist",
    ])
    def test_allowed(self, hook_patterns, cmd):
        assert not grep_matches(hook_patterns[0], cmd), f"Expected ALLOW for: {cmd!r}"


# ──────────────────────────────────────────────
# Pattern 1 — force-push (AND with pattern 2)
# Pattern 1a: git push ... --force or -f
# Pattern 1b: branch name contains main or master
# ──────────────────────────────────────────────

def force_push_blocked(patterns, cmd: str) -> bool:
    """Mirror the hook logic: block iff BOTH patterns match."""
    return grep_matches(patterns[1], cmd) and grep_matches(patterns[2], cmd)


class TestForcePushBlocker:
    @pytest.mark.parametrize("cmd", [
        "git push --force origin main",
        "git push -f origin master",
        "git push --force origin main:main",
        "git push --force origin master:master",
    ])
    def test_blocked(self, hook_patterns, cmd):
        assert force_push_blocked(hook_patterns, cmd), f"Expected BLOCK for: {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        "git push origin main",               # no force flag
        "git push --force origin feature/x",  # force but not main/master
        "git push --force origin mainline",   # "mainline" is not main (boundary check)
        "git push --force origin my-master",  # "my-master" is not master
    ])
    def test_allowed(self, hook_patterns, cmd):
        assert not force_push_blocked(hook_patterns, cmd), f"Expected ALLOW for: {cmd!r}"


# ──────────────────────────────────────────────
# Pattern 2 (index 3 in hook) — hard reset
# ──────────────────────────────────────────────

class TestHardResetBlocker:
    @pytest.mark.parametrize("cmd", [
        "git reset --hard",
        "git reset --hard HEAD~1",
        "  git reset --hard origin/main",
        "git reset --hard HEAD",
    ])
    def test_blocked(self, hook_patterns, cmd):
        assert grep_matches(hook_patterns[3], cmd), f"Expected BLOCK for: {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        "git reset HEAD",
        "git reset --soft HEAD~1",
        "git reset --mixed",
        "git reset --keep HEAD~1",
    ])
    def test_allowed(self, hook_patterns, cmd):
        assert not grep_matches(hook_patterns[3], cmd), f"Expected ALLOW for: {cmd!r}"
