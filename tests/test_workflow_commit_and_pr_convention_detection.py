"""Tests for branch-convention detection and concrete commit-format inference (issue #394).

Covers:
  (a) Branch-convention 3-tier probe: git branch -a, commit type-set, <type>/<kebab> fallback, ambiguous/undetectable warning.
  (b) Rename offer: AskUserQuestion + git branch -m; suggest-only when upstream/pushed or open PR exists; main/master warning.
  (c) EnterWorktree-mangled worktree-* pattern recognition; rimba pointer; canonical prefixes.
  (d) Commit-fallback concreteness: git log --oneline, prefix/leading, dominant/plurality, scope, "only when no shape reaches a plurality".
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL_PATH = ROOT / "skills" / "workflow-commit-and-pr" / "SKILL.md"

BRANCH_SECTION_HEADING = "## Branch-convention detection"
COMMIT_FORMAT_HEADING = "## Codified commit format"


def _section_body(text: str, heading: str) -> str:
    """Return text from heading to the next ## heading (exclusive)."""
    start = text.find(heading)
    if start == -1:
        return ""
    end = text.find("\n## ", start + len(heading))
    return text[start:end] if end != -1 else text[start:]


# ---------------------------------------------------------------------------
# (a) 3-tier branch-convention probe
# ---------------------------------------------------------------------------


def test_branch_section_uses_3tier_detection():
    """Branch section must describe the 3-tier detection probe.

    Asserts:
    1. Section heading is 'Branch-convention detection' (not the old 'Branch-naming check').
    2. Tier 1: infers prefixes from git branch -a.
    3. Tier 2: derives prefix set from commit type-set.
    4. Tier 3: <type>/<kebab> fallback retained.
    5. Warns on ambiguous or undetectable conventions.
    """
    body = SKILL_PATH.read_text()

    assert BRANCH_SECTION_HEADING in body, (
        f"Missing section '{BRANCH_SECTION_HEADING}' — old heading 'Branch-naming check' must be renamed"
    )

    section = _section_body(body, BRANCH_SECTION_HEADING)

    assert "git branch -a" in section, (
        "Tier 1 detection must reference 'git branch -a' to infer dominant prefix from history"
    )

    assert re.search(r"commit type.set|type.set|derived? from.{0,30}commit", section, re.IGNORECASE), (
        "Tier 2 detection must describe deriving branch prefix from detected commit type-set"
    )

    assert re.search(r"<type>/<kebab>|type/kebab", section), (
        "Tier 3 fallback '<type>/<kebab>' must be retained in the branch section"
    )

    assert re.search(r"ambiguous|undetectable", section, re.IGNORECASE), (
        "Branch section must warn clearly when convention is ambiguous or undetectable"
    )


# ---------------------------------------------------------------------------
# (b) Rename offer mechanics
# ---------------------------------------------------------------------------


def test_branch_rename_offer_mechanics():
    """Branch section must specify the rename offer, suggest-only safety, and main/master warning.

    Asserts:
    1. AskUserQuestion is called to offer the rename (never silent/auto).
    2. git branch -m is the rename command.
    3. Detects pushed/upstream state (checks for upstream or @{upstream}).
    4. Detects open PR via gh pr view.
    5. Downgrades to suggest-only when pushed or open PR exists.
    6. main/master branch warning is retained.
    """
    body = SKILL_PATH.read_text()
    section = _section_body(body, BRANCH_SECTION_HEADING)

    assert section, f"Section '{BRANCH_SECTION_HEADING}' not found in SKILL.md"

    assert "AskUserQuestion" in section, (
        "Rename must be offered via AskUserQuestion — never silent or auto-renamed"
    )

    assert "git branch -m" in section, (
        "The rename command offered to the user must be 'git branch -m'"
    )

    assert re.search(r"upstream|@\{upstream\}", section), (
        "Must detect whether branch already has an upstream (pushed state)"
    )

    assert re.search(r"gh pr view", section), (
        "Must check for an open PR via 'gh pr view' before offering rename"
    )

    assert re.search(r"suggest.only", section, re.IGNORECASE), (
        "Must downgrade to suggest-only (print compliant name, no git branch -m) when pushed or open PR"
    )

    assert re.search(r"`main`|`master`|main.*warn|master.*warn", section), (
        "main/master branch warning must be retained in the branch-convention section"
    )


# ---------------------------------------------------------------------------
# (c) EnterWorktree-mangled pattern guard
# ---------------------------------------------------------------------------


def test_worktree_mangled_pattern_guard():
    """Branch section must recognise worktree-* mangled names and point to rimba.

    Asserts:
    1. 'worktree-' pattern is explicitly mentioned.
    2. 'rimba' is referenced as the canonical branch-creation tool.
    3. All six canonical rimba prefixes are listed: feature/, bugfix/, hotfix/, docs/, test/, chore/.
    """
    body = SKILL_PATH.read_text()
    section = _section_body(body, BRANCH_SECTION_HEADING)

    assert re.search(r"worktree-", section), (
        "Branch section must recognize the 'worktree-*' EnterWorktree-mangled pattern"
    )

    assert "rimba" in section, (
        "Branch section must point to rimba as the canonical branch-creation tool"
    )

    canonical_prefixes = ["feature/", "bugfix/", "hotfix/", "docs/", "test/", "chore/"]
    for prefix in canonical_prefixes:
        assert prefix in section, (
            f"Canonical rimba prefix '{prefix}' must be listed in the branch section"
        )


# ---------------------------------------------------------------------------
# (d) Concrete commit-format fallback
# ---------------------------------------------------------------------------


def test_commit_format_fallback_is_concrete():
    """Commit-format fallback (git log inference) must be concrete, not vague.

    Asserts:
    1. References 'git log --oneline' as the fallback probe command.
    2. Describes tally/parsing of leading prefix shapes ('prefix' or 'leading').
    3. Uses 'dominant' or 'plurality' to describe the selection algorithm.
    4. Mentions 'scope' detection (whether scopes are used).
    5. Defaults to Conventional Commits "only when no pattern dominates" (not unconditionally).
    """
    body = SKILL_PATH.read_text()
    section = _section_body(body, COMMIT_FORMAT_HEADING)

    assert section, f"Section '{COMMIT_FORMAT_HEADING}' not found in SKILL.md"

    assert "git log --oneline" in section, (
        "Commit fallback must specify 'git log --oneline' as the inference command"
    )

    assert re.search(r"prefix|leading", section, re.IGNORECASE), (
        "Commit fallback must describe parsing leading prefixes from log output"
    )

    assert re.search(r"dominant|plurality", section, re.IGNORECASE), (
        "Commit fallback must select the dominant/plurality shape, not just observe"
    )

    assert re.search(r"note\s+\*{0,2}scope\*{0,2}\s+usage|detect.*scope", section, re.IGNORECASE), (
        "Commit fallback must instruct to note/detect scope usage, not merely mention "
        "the word 'scope' in a format example"
    )

    assert re.search(
        r"only when no (shape|pattern) (reach|dominates|reaches)|no (shape|pattern) dominates",
        section,
        re.IGNORECASE,
    ), (
        "Commit fallback must default to Conventional Commits ONLY when no pattern dominates, "
        "not unconditionally — framing must be conditional"
    )
