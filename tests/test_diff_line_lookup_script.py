"""Tests for bin/swe-workbench-diff-line-lookup — post-diff line resolver (issue #551).

Resolves the exact post-diff line number for a literal code snippet, so review-comment
posting no longer hand-counts the offset from a hunk header (`@@ -a,b +c,d @@`).

Behavioral paths under test:
  - Usage surface: exit 64 on missing args, conflicting source flags, unknown flags,
    a newline embedded in the pattern
  - Core scan (--stdin): single hunk, non-zero hunk start, multi-hunk offset correctness,
    multi-file isolation, "\\ No newline at end of file" handling
  - Not-found paths (exit 1): absent entirely, found on a context line, found on a removed line
  - Ambiguity (exit 2): multiple matching `+` lines, stdout empty, all candidates on stderr
  - Git-internal modes: default (git diff HEAD), --staged, --range=<rev>
  - Wiring: SCRIPTS dict, shellcheck auto-discovery contract, --help output,
    agents/reviewer.md, workflow-pr-review-post/SKILL.md
"""

import os
import subprocess
from pathlib import Path
from shutil import which

from conftest import _CLEAN_ENV

SCRIPT = Path(__file__).parent.parent / "bin" / "swe-workbench-diff-line-lookup"
ROOT = Path(__file__).parent.parent

BASH_BIN = which("bash") or "/bin/bash"


def _run(args, *, stdin: str | None = None, cwd: Path = ROOT, extra_env: dict | None = None):
    env = dict(_CLEAN_ENV)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [BASH_BIN, str(SCRIPT), *args],
        input=stdin,
        capture_output=True, text=True,
        cwd=str(cwd),
        env=env,
    )


def _git(args, *, cwd: Path):
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(cwd), env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(tmp_path: Path) -> Path:
    """A throwaway repo with one commit on 'main', mirroring test_setup_sh.py's git init precedent."""
    _git(["init", "-b", "main", str(tmp_path)], cwd=tmp_path)
    (tmp_path / "src.txt").write_text("line1\nline2\nline3\n")
    _git(["add", "src.txt"], cwd=tmp_path)
    _git(["commit", "-m", "initial"], cwd=tmp_path)
    return tmp_path


# ── Existence ────────────────────────────────────────────────────────────────

def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-diff-line-lookup must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-diff-line-lookup must be executable (chmod +x)"


# ── Unit 1: usage surface (exit 64) ────────────────────────────────────────────

def test_missing_all_args_exits_64():
    result = _run([])
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_missing_pattern_arg_exits_64():
    result = _run(["src/Foo.java"])
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_two_source_flags_together_exits_64():
    result = _run(["src/Foo.java", "pattern", "--staged", "--range=HEAD~1"])
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_unknown_flag_exits_64():
    result = _run(["src/Foo.java", "pattern", "--bogus"])
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_newline_in_pattern_exits_64():
    result = _run(["src/Foo.java", "line one\nline two"])
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_empty_range_value_exits_64():
    result = _run(["src/Foo.java", "pattern", "--range="])
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_empty_pattern_exits_64_instead_of_matching_everything():
    """An empty pattern must not silently match every `+` line (index(s, "") is always > 0 in awk)."""
    diff = (
        "diff --git a/x b/x\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+something\n"
    )
    result = _run(["x", "", "--stdin"], stdin=diff)
    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_invalid_range_exits_64_not_a_raw_git_exit_code(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(["src.txt", "pattern", "--range=totally-bogus-rev"], cwd=repo)
    assert result.returncode == 64, (
        f"a bad --range must map to the documented usage-error exit code, not leak git's own "
        f"exit code (got {result.returncode}): {result.stderr!r}"
    )
    assert "Usage:" in result.stderr


# ── Unit 2: core scan via --stdin ──────────────────────────────────────────────

def test_single_hunk_resolves_added_line():
    diff = (
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -1,2 +1,3 @@\n"
        " context line\n"
        "+if (opts.retries > 0) {\n"
        " another context\n"
    )
    result = _run(["src/Foo.java", "if (opts.retries > 0) {", "--stdin"], stdin=diff)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src/Foo.java:2\n"
    assert result.stderr == ""


def test_nonzero_hunk_start_offsets_correctly():
    diff = (
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -10,3 +10,4 @@\n"
        " ctx a\n"
        "+ADDED_PATTERN\n"
        " ctx b\n"
        " ctx c\n"
    )
    result = _run(["src/Foo.java", "ADDED_PATTERN", "--stdin"], stdin=diff)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src/Foo.java:11\n"


def test_multi_hunk_later_hunk_offset_correct():
    diff = (
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -1,2 +1,2 @@\n"
        " ctx1\n"
        " ctx2\n"
        "@@ -20,2 +21,3 @@\n"
        " ctx20\n"
        "+MULTI_HUNK_PATTERN\n"
        " ctx21\n"
    )
    result = _run(["src/Foo.java", "MULTI_HUNK_PATTERN", "--stdin"], stdin=diff)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src/Foo.java:22\n"


def test_multi_file_diff_ignores_other_file_match():
    diff = (
        "diff --git a/other.txt b/other.txt\n"
        "--- a/other.txt\n"
        "+++ b/other.txt\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+SHARED_PATTERN\n"
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+SHARED_PATTERN\n"
    )
    result = _run(["src/Foo.java", "SHARED_PATTERN", "--stdin"], stdin=diff)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src/Foo.java:2\n", (
        "match must resolve only within src/Foo.java's own hunk, not other.txt's"
    )


def test_added_line_starting_with_plusplus_is_not_mistaken_for_header():
    """An added line whose content begins with '++' (raw line '+++...') must not be
    mistaken for a '+++ b/<path>' file header — only account lines while inside a hunk."""
    diff = (
        "diff --git a/x b/x\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+++PLUSPLUS_MARKER\n"
    )
    result = _run(["x", "++PLUSPLUS_MARKER", "--stdin"], stdin=diff)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "x:2\n"


def test_no_newline_at_eof_marker_handled():
    diff = (
        "diff --git a/src/Foo.java b/src/Foo.java\n"
        "--- a/src/Foo.java\n"
        "+++ b/src/Foo.java\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+FINAL_PATTERN\n"
        "\\ No newline at end of file\n"
    )
    result = _run(["src/Foo.java", "FINAL_PATTERN", "--stdin"], stdin=diff)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src/Foo.java:2\n", (
        "the no-newline marker must not shift the line counter"
    )


# ── Unit 3: not-found paths (exit 1) ───────────────────────────────────────────

def test_path_absent_entirely_exits_1():
    diff = (
        "diff --git a/other.txt b/other.txt\n"
        "--- a/other.txt\n"
        "+++ b/other.txt\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+something\n"
    )
    result = _run(["src/Foo.java", "something", "--stdin"], stdin=diff)
    assert result.returncode == 1
    assert result.stdout == ""


def test_found_on_context_line_exits_1_with_diagnostic():
    diff = (
        "diff --git a/x b/x\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,2 +1,2 @@\n"
        " FIXME here\n"
        " unrelated\n"
    )
    result = _run(["x", "FIXME", "--stdin"], stdin=diff)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "context line" in result.stderr
    assert "x:1" in result.stderr


def test_found_on_removed_line_exits_1_with_diagnostic():
    diff = (
        "diff --git a/x b/x\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,2 +1,1 @@\n"
        "-DOOMED_LINE\n"
        " survivor\n"
    )
    result = _run(["x", "DOOMED_LINE", "--stdin"], stdin=diff)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "removed line" in result.stderr
    assert "x:1" in result.stderr


# ── Unit 4: ambiguity (exit 2) ─────────────────────────────────────────────────

def test_ambiguous_match_exits_2_with_all_candidates_on_stderr():
    diff = (
        "diff --git a/x b/x\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,1 +1,5 @@\n"
        " ctx\n"
        "+return null; // A\n"
        "+something else\n"
        "+return null; // B\n"
        "+return null; // C\n"
    )
    result = _run(["x", "return null", "--stdin"], stdin=diff)
    assert result.returncode == 2
    assert result.stdout == "", "stdout must be empty on ambiguity"
    assert "x:2" in result.stderr
    assert "x:4" in result.stderr
    assert "x:5" in result.stderr
    assert "3" in result.stderr


# ── Unit 5: git-internal modes (real repo fixture) ─────────────────────────────

def test_default_mode_picks_up_uncommitted_work(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "src.txt").write_text("line1\nUNCOMMITTED_PATTERN\nline2\nline3\n")
    result = _run(["src.txt", "UNCOMMITTED_PATTERN"], cwd=repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src.txt:2\n"


def test_staged_mode_sees_index_not_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "src.txt").write_text("line1\nSTAGED_PATTERN\nline2\nline3\n")
    _git(["add", "src.txt"], cwd=repo)
    (repo / "src.txt").write_text("line1\nSTAGED_PATTERN\nline2\nWORKTREE_ONLY_PATTERN\nline3\n")

    staged_result = _run(["src.txt", "STAGED_PATTERN", "--staged"], cwd=repo)
    assert staged_result.returncode == 0, staged_result.stderr
    assert staged_result.stdout == "src.txt:2\n"

    worktree_only_result = _run(["src.txt", "WORKTREE_ONLY_PATTERN", "--staged"], cwd=repo)
    assert worktree_only_result.returncode == 1, (
        "--staged must not see a change that was never staged"
    )


def test_range_head_tilde_1_sees_last_commit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "src.txt").write_text("line1\nLAST_COMMIT_PATTERN\nline2\nline3\n")
    _git(["add", "src.txt"], cwd=repo)
    _git(["commit", "-m", "second"], cwd=repo)

    result = _run(["src.txt", "LAST_COMMIT_PATTERN", "--range=HEAD~1"], cwd=repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "src.txt:2\n"


def test_range_main_dotdotdot_head_spans_multiple_commits(tmp_path):
    repo = _init_repo(tmp_path)
    _git(["checkout", "-b", "feature"], cwd=repo)
    (repo / "src.txt").write_text("line1\nFIRST_FEATURE_PATTERN\nline2\nline3\n")
    _git(["add", "src.txt"], cwd=repo)
    _git(["commit", "-m", "feature commit 1"], cwd=repo)
    (repo / "src.txt").write_text("line1\nFIRST_FEATURE_PATTERN\nline2\nSECOND_FEATURE_PATTERN\nline3\n")
    _git(["add", "src.txt"], cwd=repo)
    _git(["commit", "-m", "feature commit 2"], cwd=repo)

    first = _run(["src.txt", "FIRST_FEATURE_PATTERN", "--range=main...HEAD"], cwd=repo)
    assert first.returncode == 0, first.stderr
    assert first.stdout == "src.txt:2\n"

    second = _run(["src.txt", "SECOND_FEATURE_PATTERN", "--range=main...HEAD"], cwd=repo)
    assert second.returncode == 0, second.stderr
    assert second.stdout == "src.txt:4\n"


def test_mnemonic_prefix_config_does_not_break_header_matching(tmp_path):
    """git config diff.mnemonicPrefix rewrites +++ headers to i/ and w/ instead of a/ and b/ —
    the script forces --src-prefix=a/ --dst-prefix=b/ so header matching stays correct
    regardless of this local config, across default/--staged/--range modes."""
    repo = _init_repo(tmp_path)
    _git(["config", "diff.mnemonicPrefix", "true"], cwd=repo)

    (repo / "src.txt").write_text("line1\nMNEMONIC_HEAD_PATTERN\nline2\nline3\n")
    default_result = _run(["src.txt", "MNEMONIC_HEAD_PATTERN"], cwd=repo)
    assert default_result.returncode == 0, default_result.stderr
    assert default_result.stdout == "src.txt:2\n"

    _git(["add", "src.txt"], cwd=repo)
    (repo / "src.txt").write_text("line1\nMNEMONIC_HEAD_PATTERN\nline2\nMNEMONIC_STAGED_PATTERN\nline3\n")
    staged_result = _run(["src.txt", "MNEMONIC_HEAD_PATTERN", "--staged"], cwd=repo)
    assert staged_result.returncode == 0, staged_result.stderr
    assert staged_result.stdout == "src.txt:2\n"

    _git(["add", "src.txt"], cwd=repo)
    _git(["commit", "-m", "mnemonic commit"], cwd=repo)
    range_result = _run(["src.txt", "MNEMONIC_STAGED_PATTERN", "--range=HEAD~1"], cwd=repo)
    assert range_result.returncode == 0, range_result.stderr
    assert range_result.stdout == "src.txt:4\n"


# ── Unit 6: wiring assertions ───────────────────────────────────────────────────

def test_bin_scripts_dict_contains_diff_line_lookup():
    text = (ROOT / "tests" / "test_bin_scripts.py").read_text()
    assert '"swe-workbench-diff-line-lookup"' in text, (
        "tests/test_bin_scripts.py SCRIPTS must include swe-workbench-diff-line-lookup"
    )


def test_shellcheck_coverage_contract_contains_wrapper():
    """Assert the auto-discovery contract behaviorally covers every SCRIPTS entry."""
    import test_shellcheck_coverage as coverage
    from test_bin_scripts import SCRIPTS

    covered = {path.name for path, _ in coverage.CANDIDATES}
    assert set(SCRIPTS) <= covered, (
        "every test_bin_scripts.SCRIPTS entry must feed the auto-discovery contract — "
        "together with test_bin_scripts_dict_contains_diff_line_lookup above, that transitively "
        "proves swe-workbench-diff-line-lookup stays lint-covered after the #641 list removal"
    )


def test_help_flag_names_the_script():
    result = subprocess.run(
        [str(SCRIPT), "--help"], capture_output=True, text=True, env=dict(_CLEAN_ENV)
    )
    assert result.returncode == 0
    assert "swe-workbench-diff-line-lookup" in result.stdout


def test_reviewer_agent_references_helper():
    text = (ROOT / "agents" / "reviewer.md").read_text()
    assert "swe-workbench-diff-line-lookup" in text, (
        "agents/reviewer.md must reference swe-workbench-diff-line-lookup for deriving File:Line"
    )


def test_pr_review_submit_script_calls_helper():
    """Since #550, the pre-validate check moved from workflow-pr-review-post/SKILL.md prose
    into bin/swe-workbench-pr-review-submit, which shells out to this helper as a sibling."""
    text = (ROOT / "bin" / "swe-workbench-pr-review-submit").read_text()
    assert "swe-workbench-diff-line-lookup" in text, (
        "bin/swe-workbench-pr-review-submit must call swe-workbench-diff-line-lookup "
        "for the +-line pre-validate check"
    )
