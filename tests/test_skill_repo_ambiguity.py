"""Regression tests pinning the 'this repo' referential-ambiguity fix.

Background
----------
Skills are loaded by the dispatcher into sessions whose cwd is the *user's*
repo, not the swe-workbench plugin repo.  Any phrase like "this repo enforces
X" or "zero usage in this repo" is interpreted by the agent as a claim about
the user's workspace — causing incorrect commit-format rewriting, spurious
[no ci] warnings, and suppression of AskUserQuestion in every host repo.

These tests enforce:
1. workflow-commit-and-pr/SKILL.md has no unguarded "this repo" references
   outside fenced code blocks.
2. principle-version-control/SKILL.md attributes [type] Subject enforcement
   to "swe-workbench" explicitly, not to "this repo".
3. workflow-cleanup-merged/SKILL.md + sync-and-verify.sh resolve the default
   branch dynamically rather than hardcoding "main".
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
COMMIT_AND_PR_SKILL = ROOT / "skills" / "workflow-commit-and-pr" / "SKILL.md"
VERSION_CONTROL_SKILL = ROOT / "skills" / "principle-version-control" / "SKILL.md"
CLEANUP_MERGED_SKILL = ROOT / "skills" / "workflow-cleanup-merged" / "SKILL.md"
SYNC_SCRIPT = ROOT / "skills" / "workflow-cleanup-merged" / "scripts" / "sync-and-verify.sh"
PR_REVIEW_SKILL = ROOT / "skills" / "workflow-pr-review" / "SKILL.md"
PR_REVIEW_FOLLOWUP_SKILL = ROOT / "skills" / "workflow-pr-review-followup" / "SKILL.md"
POST_CORE_SKILL = ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md"

# Regex matching literal "main" used as a branch name in checkout/pull commands
_LITERAL_MAIN_IN_GIT_CMD = re.compile(
    r'git\s+(checkout|pull)\s+.*\bmain\b'
)
# Acceptable dynamic-resolution patterns
_DYNAMIC_BRANCH_PATTERNS = [
    re.compile(r'gh repo view.*defaultBranchRef'),
    re.compile(r'symbolic-ref refs/remotes/origin/HEAD'),
]


def _strip_fenced_code_blocks(text: str) -> str:
    """Return text with content inside fenced code blocks removed.

    Fenced blocks (``` or ~~~) may contain quoted examples; they are not
    subject to the prose-ambiguity constraint.

    Per CommonMark: a closing fence must be a bare sequence of the same
    fence character (no info string).  An opener like ```bash opens a block;
    only a line that is exactly the fence marker (e.g. ```) closes it.
    Storing the opener prefix length lets us match the closing fence correctly.
    """
    result = []
    in_fence = False
    fence_char: str | None = None  # ` or ~
    fence_len: int = 0

    for line in text.splitlines():
        stripped = line.strip()
        if not in_fence:
            # Detect opening fence: 3+ backticks or tildes, optional info string
            for fc in ("`", "~"):
                if stripped.startswith(fc * 3):
                    run = len(stripped) - len(stripped.lstrip(fc))
                    in_fence = True
                    fence_char = fc
                    fence_len = run
                    break
            else:
                result.append(line)
        else:
            # Closing fence: same character, at least fence_len long, no info string
            if (
                stripped.startswith(fence_char * fence_len)
                and all(c == fence_char for c in stripped)
            ):
                in_fence = False

    return "\n".join(result)


def test_workflow_commit_and_pr_has_no_unguarded_this_repo_refs():
    """No 'this repo'/'This repo' assertion may appear outside fenced code blocks.

    These phrases resolve deictic to the *user's* repo when the skill is loaded
    into a foreign workspace, causing the skill to impose swe-workbench
    conventions as if they were facts about the user's codebase.

    Fails today at (at least) lines 39, 97, 127, 166 of SKILL.md.
    """
    body = COMMIT_AND_PR_SKILL.read_text()
    outside_code_blocks = _strip_fenced_code_blocks(body)

    hits = []
    for lineno, line in enumerate(outside_code_blocks.splitlines(), 1):
        if re.search(r'\bthis repo\b', line, re.IGNORECASE):
            hits.append((lineno, line.strip()))

    assert not hits, (
        "Found unguarded 'this repo' reference(s) in "
        "skills/workflow-commit-and-pr/SKILL.md (outside fenced code blocks).\n"
        "These phrases must be replaced with runtime-detection steps or explicit\n"
        "'the swe-workbench plugin' naming so they do not mis-apply to host repos.\n\n"
        "Violations:\n"
        + "\n".join(f"  ~line {ln}: {txt}" for ln, txt in hits)
    )


def test_workflow_commit_and_pr_has_no_bare_issue_refs():
    """No bare #NNN issue references may appear in prose outside fenced/inline code.

    When a skill is loaded into a foreign repo, #181 resolves to *that repo's*
    issue #181, not swe-workbench's.  Explanatory cross-references must use
    descriptive language (e.g. "the PreToolUse Write/Edit hook") rather than
    a bare issue number.

    Inline code (backtick-quoted) is excluded — those are example placeholders,
    not claim-bearing references.
    """
    body = COMMIT_AND_PR_SKILL.read_text()
    # Strip fenced code blocks first
    outside_fences = _strip_fenced_code_blocks(body)
    # Strip inline code (backtick spans) — these are examples, not claims
    outside_inline = re.sub(r'`[^`\n]+`', '', outside_fences)

    hits = []
    for lineno, line in enumerate(outside_inline.splitlines(), 1):
        if re.search(r'#\d+', line):
            hits.append((lineno, line.strip()))

    assert not hits, (
        "Found bare #NNN issue reference(s) in "
        "skills/workflow-commit-and-pr/SKILL.md (outside fenced/inline code).\n"
        "Use descriptive language instead (e.g. 'the PreToolUse Write/Edit hook')\n"
        "so the reference does not resolve to the wrong issue in a foreign repo.\n\n"
        "Violations:\n"
        + "\n".join(f"  ~line {ln}: {txt}" for ln, txt in hits)
    )


def test_principle_version_control_attributes_type_format_to_swe_workbench():
    """The [type] Subject enforcement sentence must name 'swe-workbench' explicitly.

    Currently line 28 reads '**This repo enforces `[type] Subject`**', which
    is interpreted as a claim about the user's workspace.  After the fix it
    must read something like 'Example: the swe-workbench plugin repo enforces
    `[type] Subject` via `.githooks/commit-msg`'.

    Fails today because the line begins with '**This repo enforces'.
    """
    body = VERSION_CONTROL_SKILL.read_text()

    # Find all lines that mention [type] Subject AND enforcement
    enforcement_lines = [
        (i + 1, line)
        for i, line in enumerate(body.splitlines())
        if "[type] Subject" in line and re.search(r'\benforce', line, re.IGNORECASE)
    ]

    assert enforcement_lines, (
        "Expected at least one line in skills/principle-version-control/SKILL.md "
        "mentioning '[type] Subject' enforcement — none found."
    )

    for lineno, line in enforcement_lines:
        assert "swe-workbench" in line, (
            f"Line {lineno} mentions '[type] Subject' enforcement but does not name "
            f"'swe-workbench' explicitly as the example repo.\n"
            f"  Found: {line.strip()}\n"
            f"  Expected: 'swe-workbench' to appear in the same sentence so the "
            f"enforcement claim is scoped to the plugin, not to the host repo."
        )
        # The old "This repo enforces" pattern must be gone (anywhere in the line)
        assert not re.search(r"This repo enforces", line), (
            f"Line {lineno} still uses the ambiguous 'This repo enforces' phrasing.\n"
            f"  Found: {line.strip()}\n"
            f"  'This repo' resolves to the user's workspace when the skill is loaded "
            f"into a foreign repo. Use 'swe-workbench plugin repo' as the explicit subject."
        )


def test_cleanup_merged_resolves_default_branch_dynamically():
    """cleanup-merged SKILL.md and sync-and-verify.sh must not hardcode 'main'.

    The default branch of the host repo may be 'master', 'trunk', 'develop',
    or anything else.  Hardcoding 'main' silently checks out the wrong branch
    in every non-GitHub-default repo.

    Assertions:
    (a) SKILL.md contains a default-branch resolution step (gh repo view or
        symbolic-ref).
    (b) sync-and-verify.sh uses a variable (e.g. $DEFAULT_BRANCH) in every
        git checkout / git pull command; no bare literal 'main' as branch name.

    Fails today because sync-and-verify.sh line 17 has:
        git checkout main && git pull --ff-only origin main
    """
    skill_body = CLEANUP_MERGED_SKILL.read_text()
    script_body = SYNC_SCRIPT.read_text()

    # (a) SKILL.md has a dynamic resolution step
    has_resolution = any(
        pattern.search(skill_body) for pattern in _DYNAMIC_BRANCH_PATTERNS
    )
    assert has_resolution, (
        "skills/workflow-cleanup-merged/SKILL.md must contain a default-branch "
        "resolution step (e.g. 'gh repo view --json defaultBranchRef' or "
        "'symbolic-ref refs/remotes/origin/HEAD') so it works in repos whose "
        "default branch is not 'main'."
    )

    # (b) sync-and-verify.sh does not hardcode 'main' as a branch name in git commands
    offending_lines = []
    for lineno, line in enumerate(script_body.splitlines(), 1):
        if _LITERAL_MAIN_IN_GIT_CMD.search(line) and not line.strip().startswith("#"):
            offending_lines.append((lineno, line.strip()))

    assert not offending_lines, (
        "skills/workflow-cleanup-merged/scripts/sync-and-verify.sh hardcodes 'main' "
        "as the branch name in git checkout/pull commands.\n"
        "Use a variable resolved at script entry (e.g. DEFAULT_BRANCH) instead:\n\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in offending_lines)
    )


def test_pr_review_byline_and_summary_link_to_tool_repo():
    """BYLINE (both pr-review consumers) and SUMMARY (the shared posting core)
    must link to the tool repo, not the PR's own repo.

    The bug: BYLINE used https://github.com/${OWNER}/${REPO} — the PR's repo —
    instead of the constant https://github.com/lugassawan/swe-workbench. The
    fallback SUMMARY had no URL at all (bare parenthetical "(swe-workbench)").

    Since #499, BYLINE is authored by each consumer (workflow-pr-review,
    workflow-pr-review-followup) and handed to workflow-pr-review-post, which
    builds $SUMMARY from it. So the templated-URL / bare-paren / canonical-link
    checks apply to the consumers (they own BYLINE's content); the SUMMARY-
    references-BYLINE check applies to the core (it owns SUMMARY construction).

    Assertions:
    1. Templated URL ${OWNER}/${REPO} is gone — not present anywhere in any file.
    2. No BYLINE= or SUMMARY= assignment contains a bare "(swe-workbench)" without
       a markdown link.
    3. The canonical markdown link appears in each consumer's documented BYLINE.
    4. The core's SUMMARY construction reuses $BYLINE (via $BYLINE_FULL) by
       variable reference, not by repeating the URL string.
    """
    canonical = "[swe-workbench](https://github.com/lugassawan/swe-workbench)"
    buggy_url = "https://github.com/${OWNER}/${REPO}"
    bare_paren = re.compile(r'^(BYLINE|SUMMARY)=.*\(swe-workbench\)', re.MULTILINE)

    for skill_path in (PR_REVIEW_SKILL, PR_REVIEW_FOLLOWUP_SKILL, POST_CORE_SKILL):
        body = skill_path.read_text()
        skill_name = skill_path.parent.name

        # 1. Templated buggy URL must be gone
        assert buggy_url not in body, (
            f"{skill_name}/SKILL.md still contains the templated URL "
            f"'{buggy_url}' in the byline.\n"
            f"Replace with the hardcoded tool URL: https://github.com/lugassawan/swe-workbench"
        )

        # 2. No BYLINE= or SUMMARY= assignment with bare (swe-workbench) — no link
        bare_hits = bare_paren.findall(body)
        assert not bare_hits, (
            f"{skill_name}/SKILL.md has a BYLINE= or SUMMARY= assignment with bare "
            f"'(swe-workbench)' (no markdown link).\n"
            f"Replace with '[swe-workbench](https://github.com/lugassawan/swe-workbench)'."
        )

    # 3. Canonical link must appear in each consumer's documented BYLINE
    for skill_path in (PR_REVIEW_SKILL, PR_REVIEW_FOLLOWUP_SKILL):
        body = skill_path.read_text()
        assert canonical in body, (
            f"{skill_path.parent.name}/SKILL.md does not contain the canonical link '{canonical}'.\n"
            f"BYLINE must hardcode the tool URL, not interpolate the review-target repo."
        )

    # 4. The core's SUMMARY construction must reference $BYLINE via $BYLINE_FULL
    # (not duplicate the URL string)
    core_body = POST_CORE_SKILL.read_text()
    assert re.search(r'BYLINE_FULL="\$\{BYLINE\}', core_body), (
        f"{POST_CORE_SKILL.parent.name}/SKILL.md must derive BYLINE_FULL from \"${{BYLINE}}\" "
        f"so the caller-supplied byline (and its hardcoded URL) flows through unchanged."
    )
    assert re.search(r'SUMMARY=\$\(printf .+"\$BYLINE_FULL"', core_body, re.DOTALL), (
        f"{POST_CORE_SKILL.parent.name}/SKILL.md SUMMARY construction does not reference "
        f"\"$BYLINE_FULL\" in a printf call.\n"
        f"Expected: SUMMARY=$(printf '...' ... \"$BYLINE_FULL\" ...) so the URL lives in one place."
    )
