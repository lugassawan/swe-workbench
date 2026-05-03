"""Tests for hooks/hooks.json regex blockers (issue #81).

Each of the three embedded grep -Eq patterns is extracted from the real
hooks.json and tested with subprocess.run(["grep", "-Eq", ...]) — the same
regex engine the hook uses — so platform-specific POSIX character classes
(e.g. [[:space:]]) behave identically.

Note on hard-reset: the hook only exits 2 when BOTH the regex matches AND the
current branch is main/master/release/*. TestHardResetPatternMatch verifies the
first gate (regex match); branch-protection logic requires a live git environment
and is intentionally out of scope for unit tests.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

HOOKS_PATH = Path(__file__).parent.parent / "hooks" / "hooks.json"


@pytest.fixture(scope="module")
def hook_patterns():
    """Return a dict of named grep -Eq patterns extracted from hooks.json.

    Keys: 'rm_rf', 'force_push', 'main_master', 'hard_reset'
    """
    data = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
    command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    raw = re.findall(r"grep -Eq '([^']+)'", command)
    assert len(raw) == 4, f"Expected 4 patterns, found {len(raw)}: {raw}"

    # Match by characteristic substring to survive reordering in hooks.json.
    def find(keyword):
        matches = [p for p in raw if keyword in p]
        assert len(matches) == 1, f"Expected 1 pattern containing {keyword!r}, got {matches}"
        return matches[0]

    return {
        "rm_rf": find("rm"),
        "force_push": find("push"),
        "main_master": find("main|master"),
        "hard_reset": find("reset"),
    }


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
# rm -rf against root or home
# ──────────────────────────────────────────────

class TestRmRfBlocker:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -rf $HOME",
        "rm -rf ~",
        "rm -rf /*",
        "sudo rm -rf /",
    ])
    def test_pattern_matches(self, hook_patterns, cmd):
        assert grep_matches(hook_patterns["rm_rf"], cmd), f"Expected match for: {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        "rm -rf ./build",
        "rm -rf node_modules",
        "rm -rf /tmp/foo",
        "rm -f somefile",
        "rm -r ./dist",
    ])
    def test_pattern_does_not_match(self, hook_patterns, cmd):
        assert not grep_matches(hook_patterns["rm_rf"], cmd), f"Expected no match for: {cmd!r}"


# ──────────────────────────────────────────────
# force-push to main/master (AND of two patterns)
# ──────────────────────────────────────────────

def force_push_blocked(hook_patterns, cmd: str) -> bool:
    """Mirror the hook logic: block iff BOTH force-push patterns match."""
    return grep_matches(hook_patterns["force_push"], cmd) and grep_matches(hook_patterns["main_master"], cmd)


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
# hard reset — pattern-match gate only
# (full block requires branch == main/master/release/*)
# ──────────────────────────────────────────────

class TestHardResetPatternMatch:
    @pytest.mark.parametrize("cmd", [
        "git reset --hard",
        "git reset --hard HEAD~1",
        "  git reset --hard origin/main",
        "git reset --hard HEAD",
    ])
    def test_pattern_matches(self, hook_patterns, cmd):
        assert grep_matches(hook_patterns["hard_reset"], cmd), f"Expected pattern match for: {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        "git reset HEAD",
        "git reset --soft HEAD~1",
        "git reset --mixed",
        "git reset --keep HEAD~1",
    ])
    def test_pattern_does_not_match(self, hook_patterns, cmd):
        assert not grep_matches(hook_patterns["hard_reset"], cmd), f"Expected no match for: {cmd!r}"
