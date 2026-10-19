"""Tests for hooks/bash_guard.sh — end-to-end guard invocation (issue #233).

Each test class invokes hooks/bash_guard.sh directly with a JSON payload on
stdin, mirroring exactly how Claude Code calls the PreToolUse:Bash hook.
Exit code 2 + "BLOCKED" in stderr → command was blocked.
Exit code 0, empty stderr              → command was allowed.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV
from pi_guard_fixtures import (
    BASH_GUARD_BRANCH_FIXTURES,
    BASH_GUARD_FIXTURES,
    SHARED_FIXTURE_BRANCHES,
    make_branch_repo,
)

GUARD = Path(__file__).parent.parent / "hooks" / "bash_guard.sh"


@pytest.fixture(scope="module")
def guard_script():
    assert GUARD.exists(), f"missing {GUARD}"
    assert os.access(GUARD, os.X_OK), f"{GUARD} must be executable"
    return GUARD


def run_guard(script, cmd, *, cwd=None, env=None):
    payload = json.dumps({"tool_input": {"command": cmd}})
    merged_env = dict(_CLEAN_ENV)
    if env is not None:
        merged_env.update(env)
    return subprocess.run(
        [str(script)],
        input=payload, text=True, capture_output=True,
        cwd=cwd, env=merged_env,
    )


# ──────────────────────────────────────────────
# rm -rf against root or home
# ──────────────────────────────────────────────

class TestRmRfBlocker:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        'rm -rf "$HOME"',
        "sudo rm -rf /",
        "rm -rf /Users/foo",
        "rm -rf /Users/foo/Documents",
        "rm -rf /Users/foo/a/b/c",
        "rm -rf /home/foo",
        "rm -rf /home/foo/.config",
        "rm -rf $HOME/Documents",
        "rm -rf ~/.config",
        "rm -rf /Users",
        "rm -rf /home",
        'rm -rf "/Users/foo"',
        "rm -rf '/home/foo'",
        "rm -Rf /Users/foo",
        "rm -RF /Users/foo",
        "(rm -rf /)",
        "((rm -rf /))",
        "rm -rf /[U]sers/foo",
        "rm -rf /[h]ome/foo",
        "rm -rf /[h]ome",
        "ls;rm -rf /",
        "ls;rm -rf /Users/foo",
        "ls&&rm -rf /home/foo",
        # newline/tab-separated rm — the fast-exit case gate must fold the
        # same separator alphabet as the grep detector (issue #501)
        "echo hi\nrm -rf ~",
        "echo hi\trm -rf /",
        "true\trm -rf /",
        "true;\nrm -Rf $HOME",
        # backslash-continuation join must be parity-aware: an EVEN trailing-backslash
        # count is literal escaped backslashes, not a continuation — treating it as one
        # anyway joins two genuinely separate commands with zero characters between them
        # and erases the word boundary, hiding the rm on the second line
        "echo hi\\\\\nrm -rf ~",
        # a trailing backslash INSIDE a comment has no continuation meaning in real bash —
        # the comment ends at the physical newline regardless. Joining before stripping
        # comments would let the comment absorb a real command on the next line
        "echo a # note \\\nrm -rf ~",
        # comment-strip must run BEFORE the newline fold, else an early
        # comment on line 1 would swallow a destructive rm on line 2
        "git push --force  # note\nrm -rf /",
        # a trailing comment on the SAME line as rm must not hide it —
        # the rm precedes the comment marker
        "rm -rf / # cleanup",
        # a '#' INSIDE a quoted string is not a real shell comment — the
        # comment-strip must be quote-aware, or it silently truncates real
        # command text after it (issue #501 review finding)
        'echo "note # nope" && rm -rf ~',
        # quote state must persist ACROSS an embedded newline inside a still-
        # open quoted string (e.g. a multi-line -m commit message) — resetting
        # quote tracking per-line would let a '#'-starting continuation line
        # swallow real command text that follows on the SAME physical line
        # (issue #501 re-review finding)
        'git commit -m "line one\n# note" && rm -rf ~',
        # backtick and $(...) subshells previously slipped past both the fast-gate and the
        # anchor regex
        "`rm -rf /`",
        "var=`rm -rf /`",
        "$(rm -rf /)",
        "var=$(rm -rf /)",
        "echo `rm -rf /`",
        "echo $(rm -rf /)",
    ])
    def test_blocked(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2, (
            f"Expected exit 2 (BLOCKED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr, (
            f"Expected 'BLOCKED' in stderr for {cmd!r}\nstderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("cmd", [
        "rm -rf ./build",
        "rm -rf node_modules",
        "rm -rf /tmp/foo",
        "rm -rf /var/log",
        "rm -f somefile",
        "rm -r ./dist",
        "rm -rf /UsersHome",
        "rm -rf /homestead",
        "echo hi\nrm -rf ./build",
        "true\trm -rf ./build",
        # legitimate backtick/$(...) subshells with no rm inside must stay allowed
        "echo `ls`",
        "x=$(date)",
        "echo $(pwd)",
    ])
    def test_allowed(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 0, (
            f"Expected exit 0 (ALLOWED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == "", (
            f"Expected empty stderr for {cmd!r}\nstderr: {result.stderr!r}"
        )


# ──────────────────────────────────────────────
# force-push to main/master
# ──────────────────────────────────────────────

class TestForcePushBlocker:
    @pytest.mark.parametrize("cmd", [
        "git push --force origin main",
        "git push -f origin master",
        "git push --force origin main:main",
        "git push --force origin master:master",
        "git push --force origin refs/heads/main",
        "git push --force origin refs/heads/master",
        "git push --force origin HEAD:main",
        "git push --force origin feature:main",
        "git push --force origin HEAD:master",
        "git push origin main --force",
        # release/* cases (issue #341)
        "git push --force origin release/1.2",
        "git push -f origin release/2025-01",
        "git push --force origin HEAD:release/1.2",
        "git push --force origin release/1.2:release/1.2",
        "git push --force origin release/x:main",
        # quote state spanning an embedded newline inside an open quote must
        # not let a '#'-starting continuation line swallow the real force-push
        # that follows on the same physical line (issue #501 re-review finding)
        'git commit -m "line one\n# note" && git push --force origin main',
        # Direct-hook-only prefix and attached-option spellings; shared
        # direct/Pi vectors belong in BASH_GUARD_FIXTURES.
        "GIT_DIR=.git git push --force origin main",
        "time git push --force origin main",
        "command git push --force origin main",
        "git push -oci.skip --force origin main",
        "git push -uorigin --force origin main",
    ])
    def test_blocked(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2, (
            f"Expected exit 2 (BLOCKED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push origin main",
        "git push --force origin feature/x",
        "git push --force origin mainline",
        "git push --force origin my-master",
        "git push --force-with-lease origin main",
        "git push --force-with-lease origin master",
        "git push --force-if-includes origin main",
        "git push --force-with-lease=origin/main origin main",
        # A quoted prose mention of a global-option push must not become a command match.
        'echo "git -c x=y push --force origin main"',
        # no false positives for similar-looking branch names (issue #341)
        "git push --force origin prerelease/x",
        "git push --force-with-lease origin release/1.2",
    ])
    def test_allowed(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 0, (
            f"Expected exit 0 (ALLOWED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("cmd", [
        r"\git push --force origin main",
        r"g\it push --force origin main",
        '"git" push --force origin main',
        "git\tpush --force origin main",
        "(git push --force origin main)",
        "$(git push --force origin main)",
        "OUT=`git push --force origin main`",
        "OUT=`git push -f origin main`",
        "/usr/bin/git push --force origin main",
        "/usr/bin/git push -f origin main",
        "bin/git push --force origin main",
    ])
    def test_wrapped_force_push_to_protected_ref_is_blocked(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2, (
            f"Expected exit 2 (BLOCKED) for {cmd!r}, got {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr


# ──────────────────────────────────────────────
# implicit-branch force-push — branch-aware (requires temp git repo)
# ──────────────────────────────────────────────

class TestImplicitForcePushBlocker:
    """Force push with no explicit refspec, relying on push.default or an
    upstream, from a protected branch.
    """

    @pytest.mark.parametrize("branch", ["main", "master", "release/2025-01"])
    @pytest.mark.parametrize("cmd", ["git push --force", "git push -f"])
    def test_blocked_on_protected_branch(self, guard_script, repo_on, branch, cmd):
        repo = repo_on(branch)
        result = run_guard(guard_script, cmd, cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {cmd!r} on branch {branch!r}, got exit "
            f"{result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", ["git push --force", "git push -f"])
    def test_allowed_on_feature_branch(self, guard_script, repo_on, cmd):
        repo = repo_on("feature/x")
        result = run_guard(guard_script, cmd, cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED for {cmd!r} on feature/x, got exit "
            f"{result.returncode}\nstderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("cmd", [
        "git push --force --all origin",
        "git push --mirror origin",
    ])
    def test_all_or_mirror_push_is_blocked_on_feature_branch(self, guard_script, repo_on, cmd):
        """These modes can update protected remote refs regardless of the current branch."""
        repo = repo_on("feature/x")
        result = run_guard(guard_script, cmd, cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_explicit_nonprotected_refspec_still_allowed(self, guard_script, repo_on):
        """An explicit non-protected refspec must not regress — the
        protected-refspec scan owns explicit protected destinations, while
        the implicit-branch heuristic applies only without a refspec.
        """
        repo = repo_on("main")
        result = run_guard(guard_script, "git push --force origin feat", cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("cmd", [
        "git push origin --force 2>&1",
        "git push --force origin > /dev/null",
        "git push --force origin >/dev/null",
        "git push --force origin 2>guard.log",
        "git push --force origin &>guard.log",
    ])
    def test_redirect_syntax_does_not_hide_implicit_force_push(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push --force origin feature/x 2>&1",
        "git push --force origin feature/x > /dev/null",
        "git push --force origin feature/x >/dev/null",
        "git push --force origin feature/x 2>guard.log",
        "git push --force origin feature/x &>guard.log",
    ])
    def test_redirected_explicit_feature_refspec_stays_allowed(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0, (
            f"Expected ALLOWED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == ""

    @pytest.mark.parametrize("cmd", ["git -C '' push --force", 'git -C "" push --force'])
    def test_empty_git_global_option_value_does_not_hide_push(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git -C '' push --force origin feature/x",
        'git -C "" push --force origin feature/x',
    ])
    def test_empty_git_global_option_with_feature_refspec_stays_allowed(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0, (
            f"Expected ALLOWED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == ""

    @pytest.mark.parametrize("branch,blocked", [("main", True), ("feature/x", False)])
    @pytest.mark.parametrize("cmd", [
        "git push --force origin $(git branch --show-current)",
        "git push --force origin `git branch --show-current`",
    ])
    def test_current_branch_query_is_the_current_branch(
        self, guard_script, repo_on, branch, blocked, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on(branch)))
        assert (result.returncode == 2) is blocked, (
            f"{cmd!r} on {branch}: exit {result.returncode}, stderr {result.stderr!r}"
        )

    @pytest.mark.parametrize("branch", ["main", "feature/x"])
    @pytest.mark.parametrize("cmd", [
        "git push --force origin refs/heads/$(git branch --show-current)",
        "git push --force origin $(git branch --show-current)x",
        "git -C other push --force origin $(git branch --show-current)",
    ])
    def test_dynamic_refspec_fails_closed(self, guard_script, repo_on, branch, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on(branch)))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push --force-with-lease origin $(git branch --show-current)",
        "git push --force-with-lease origin `git branch --show-current`",
    ])
    def test_dynamic_refspec_with_lease_stays_allowed(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0, (
            f"Expected ALLOWED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == ""

    def test_shell_code_operand_is_rescanned(self, guard_script, repo_on):
        result = run_guard(
            guard_script, "bash -c 'git push --force && cd x'", cwd=str(repo_on("main"))
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_shell_code_operand_with_feature_refspec_stays_allowed(self, guard_script, repo_on):
        result = run_guard(
            guard_script,
            "bash -c 'git push --force origin feature/x && cd x'",
            cwd=str(repo_on("main")),
        )
        assert result.returncode == 0, (
            f"Expected ALLOWED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == ""

    def test_quoted_push_prose_stays_allowed(self, guard_script):
        result = run_guard(guard_script, 'echo "git push --force origin main && cd x"')
        assert result.returncode == 0, (
            f"Expected ALLOWED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert result.stderr == ""

    def test_nested_eval_force_push_stays_fail_closed(self, guard_script, repo_on):
        result = run_guard(
            guard_script, "eval eval eval eval eval git push --force", cwd=str(repo_on("main"))
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git -C /tmp push --force",
        "git --git-dir=/tmp/other.git push --force",
        "git --work-tree=/tmp/other push --force",
    ])
    def test_nonempty_git_context_blocks_implicit_force_push(self, guard_script, repo_on, cmd):
        """Run from a non-protected branch: the hook's cwd cannot be attributed
        to the target repo, so only the context-option rule can block this.
        """
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "sudo bash -c 'git push --force origin main'",
        "env bash -c 'git push --force origin main'",
        "ssh host 'git push --force origin main' harmless",
    ])
    def test_transparent_prefix_and_ssh_arguments_do_not_hide_wrapper_push(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_shell_wrapper_does_not_scan_zero_argument_as_code(self, guard_script):
        result = run_guard(
            guard_script, "bash -c 'echo ok' 'ignored; git push --force origin main'"
        )
        assert result.returncode == 0 and result.stderr == ""

    def test_substitution_option_does_not_taint_explicit_feature_refspec(self, guard_script, repo_on):
        result = run_guard(
            guard_script,
            "git push --force --push-option=$(date) origin feature/x",
            cwd=str(repo_on("main")),
        )
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "git push --force --push-option=$(date)x origin",
        "git push --force --push-option=x$(date) origin",
        "git push --force --push-option=pre$(date)post origin",
        "git push --force --push-option=`date`x origin",
        "git push --force --push-option=$(date)$(whoami) origin",
    ])
    def test_substitution_with_literal_stays_one_option_value_word(
        self, guard_script, repo_on, cmd
    ):
        """A substitution glued to literal text is ONE shell word. Splitting it
        into SUB + a trailing WORD makes the literal count as the remote and
        `origin` as a refspec, hiding an implicit force-push from main.
        """
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_substitution_with_literal_option_does_not_taint_explicit_feature_refspec(
        self, guard_script, repo_on
    ):
        result = run_guard(
            guard_script,
            "git push --force --push-option=$(date)x origin feature/x",
            cwd=str(repo_on("main")),
        )
        assert result.returncode == 0 and result.stderr == ""

    def test_substitution_glued_to_destination_fails_closed(self, guard_script, repo_on):
        result = run_guard(
            guard_script,
            "git push --force origin feature/$(date)",
            cwd=str(repo_on("feature")),
        )
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        'git push --force origin "$(echo main)"',
        'git push --force origin "feature/$(date)"',
        'git push --force origin "`echo main`"',
        'git push --force origin "$(echo "main")"',
        'echo "$(git push --force origin main)"',
    ])
    def test_double_quoted_substitution_is_live_not_literal(
        self, guard_script, repo_on, cmd
    ):
        """Substitutions run inside double quotes, so a destination (or a whole
        push) hidden in one must fail closed instead of lexing as plain text.
        """
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push --force origin '$(echo main)'",
        "git push --force --push-option=\"$(date)\" origin feature/x",
        'git push --force origin "\\$(echo main)"',
    ])
    def test_single_quoted_or_escaped_substitution_stays_literal(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "git push -f origin +main",
        "git push origin +main",
        "git push origin +refs/heads/main",
        "git push origin HEAD:+main",
        "git push --force-with-lease origin +main",
    ])
    def test_plus_refspec_is_a_force_push_to_protected_ref(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push $(echo --force) origin main",
        'git push "$(echo -f)" origin main',
        "git push -$(echo f) origin main",
        "git push --forc$(echo e) origin main",
        "git push `echo -f` origin main",
    ])
    def test_dynamic_force_flag_fails_closed_for_protected_ref(self, guard_script, repo_on, cmd):
        """A substitution can expand to the force flag itself, so a push whose
        flags are indeterminate must not be treated as non-force.
        """
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_dynamic_force_flag_fails_closed_for_implicit_protected_branch(
        self, guard_script, repo_on
    ):
        result = run_guard(guard_script, "git push -$(echo f)", cwd=str(repo_on("main")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("branch,cmd", [
        ("feature", "git push origin +feature/x"),
        ("feature", 'git push origin "$(git rev-parse HEAD)":main'),
        ("main", 'git push origin "$(git branch --show-current)"'),
        ("main", 'git push -u origin "$(git branch --show-current)"'),
        ("main", 'git push -f -o "$(date)" origin feature/x'),
        ("main", 'git push --push-option="$(date)" origin main'),
        ("feature", "git push -$(echo f)"),
    ])
    def test_dynamic_and_plus_shapes_do_not_over_block(
        self, guard_script, repo_on, branch, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on(branch)))
        assert result.returncode == 0 and result.stderr == ""

    def test_trailing_comment_false_positive_still_allowed(self, guard_script):
        """A protected token in a trailing shell comment must not over-block
        (no repo fixture needed — this never reaches the branch check).
        """
        result = run_guard(guard_script, "git push -f origin feat # rebased onto main")
        assert result.returncode == 0, (
            f"Expected ALLOWED, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

    def test_quoted_hash_does_not_hide_implicit_force_push(self, guard_script, repo_on):
        """A '#' inside a quoted string (e.g. a commit message referencing an
        issue number) must not be treated as a comment — it must not hide a
        chained implicit force-push from a protected branch.
        """
        repo = repo_on("main")
        result = run_guard(
            guard_script, 'echo "see issue #501" && git push --force', cwd=str(repo)
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_chained_nonforce_push_does_not_hide_forced_push(self, guard_script, repo_on):
        """An explicit, innocuous push chained BEFORE an implicit force-push
        must not cause the implicit-branch heuristic to inspect the wrong
        invocation and miss the dangerous one.
        """
        repo = repo_on("main")
        result = run_guard(
            guard_script, "git push origin feature && git push --force", cwd=str(repo)
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_tab_separated_prefix_does_not_hide_forced_push(self, guard_script, repo_on):
        """A tab-separated command prefix before the force-push must not leak
        into the isolated push invocation and miscount positionals.
        """
        repo = repo_on("main")
        result = run_guard(guard_script, "echo hi\tgit push --force", cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_separate_word_push_option_does_not_hide_implicit_force_push(
        self, guard_script, repo_on
    ):
        """A separate-word push option (`-o ci.skip`) must not be miscounted
        as the first positional (remote) — that would let the real remote
        token flip has_refspec and silently allow the implicit force-push
        (senior-engineer consult, issue #501).
        """
        repo = repo_on("main")
        result = run_guard(guard_script, "git push -o ci.skip --force origin", cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_separate_word_push_option_repeated_still_blocked(self, guard_script, repo_on):
        """Multiple unrecognized separate-word flags must each consume their
        own value token, not accumulate into a false explicit-refspec read.
        """
        repo = repo_on("main")
        result = run_guard(
            guard_script,
            "git push -o ci.skip -o merge_request.create --force origin",
            cwd=str(repo),
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_separate_word_push_option_with_explicit_branch_still_allowed(
        self, guard_script, repo_on
    ):
        """An explicit remote+branch after a separate-word option must still
        count as an explicit refspec — the consume-next fix must not
        over-block a genuinely explicit, non-protected destination.
        """
        repo = repo_on("main")
        result = run_guard(
            guard_script,
            "git push -o ci.skip --force origin feat-branch",
            cwd=str(repo),
        )
        assert result.returncode == 0, (
            f"Expected ALLOWED, got exit {result.returncode}\nstderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("flag", ["-u", "--set-upstream", "-d", "--delete"])
    def test_known_boolean_push_flag_does_not_over_block_explicit_refspec(
        self, guard_script, repo_on, flag
    ):
        """A common boolean-only push flag (-u/--set-upstream/-d/--delete)
        must not be mistaken for a value-taking flag — that would swallow the
        real remote token and misclassify an explicit, non-protected refspec
        as implicit, over-blocking legitimate work (re-review finding).
        """
        repo = repo_on("main")
        result = run_guard(
            guard_script, f"git push {flag} origin feature-branch --force", cwd=str(repo)
        )
        assert result.returncode == 0, (
            f"Expected ALLOWED for flag {flag!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("prefix", ["git", "rtk git"])
    def test_nonforce_push_with_later_cleanup_flag_is_allowed(
        self, guard_script, repo_on, prefix
    ):
        repo = repo_on("main")
        command = (
            f"{prefix} push -u origin feature/x && TMP=$(mktemp) "
            "&& trap 'rm -f \"$TMP\"' EXIT"
        )
        result = run_guard(guard_script, command, cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED for {command!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == ""

    def test_every_force_push_segment_is_checked(self, guard_script, repo_on):
        repo = repo_on("main")
        result = run_guard(
            guard_script,
            "git push --force origin feature/x && git push --force",
            cwd=str(repo),
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("command", [
        "rtk git push --force",
        "rtk git push -f",
        "rtk git push --force origin",
        "rtk git push -f origin",
    ])
    def test_rtk_implicit_force_push_still_blocked(self, guard_script, repo_on, command):
        repo = repo_on("main")
        result = run_guard(guard_script, command, cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {command!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("command", [
        "bash -c 'git push --force'",
        "git push -o ci.skip origin --force",
    ])
    def test_transparent_prefix_implicit_force_push_is_blocked(
        self, guard_script, repo_on, command
    ):
        repo = repo_on("main")
        result = run_guard(guard_script, command, cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED for {command!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_inline_cd_before_implicit_force_push_remains_blocked(self, guard_script, repo_on):
        repo = repo_on("main")
        result = run_guard(
            guard_script,
            "cd /tmp/feature-worktree && rtk git push --force",
            cwd=str(repo),
        )
        assert result.returncode == 2, (
            f"Expected BLOCKED, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr


# ──────────────────────────────────────────────
# hard reset — branch-aware (requires temp git repo)
# ──────────────────────────────────────────────

@pytest.fixture
def repo_on(tmp_path):
    """Factory for temp git repos on a given branch."""
    def _make(branch: str) -> Path:
        # Use a named subdirectory so stale .git dirs from previous pytest
        # sessions never cause re-init or branch contamination.
        repo_dir = tmp_path / "repo"
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.mkdir()
        subprocess.run(["git", "init", "-q", "-b", branch], cwd=repo_dir,
                       env=_CLEAN_ENV, check=True)
        (repo_dir / "README").write_text("init")
        subprocess.run(["git", "add", "."], cwd=repo_dir, env=_CLEAN_ENV, check=True)
        # Disable hooks so the host repo's commit-msg hook (which enforces
        # [type] format) does not reject the plain "init" fixture message.
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null",
             "-c", "user.email=t@t.com", "-c", "user.name=T",
             "commit", "-qm", "init"],
            cwd=repo_dir, env=_CLEAN_ENV, check=True,
        )
        return repo_dir
    return _make


class TestWrapperAndSubstitutionCoverage:
    """Shapes that execute a force push to a protected ref and must stay blocked,
    however a wrapper, a substitution or a quoted string carries them.
    """

    @pytest.mark.parametrize("cmd", [
        "cat <(git push --force origin main)",
        "true >(git push --force origin main)",
        "diff <(git push --force origin main) /dev/null",
    ], ids=["procsub-in", "procsub-out", "procsub-operand"])
    def test_process_substitution_body_is_scanned(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "bash -lc 'git push --force origin main'",
        "sh -ec 'git push --force origin main'",
        "bash -ic 'git push --force origin main'",
        'zsh -xc "git push --force origin main"',
        "bash -c -- 'git push --force origin main'",
        "sudo bash -lc 'git push --force origin main'",
        "timeout 5 bash -lc 'git push --force origin main'",
        "env -S 'git push --force origin main'",
    ])
    def test_shell_string_operand_is_scanned(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "out=$(git push --force origin main |\n tail -1)",
        "x=$(git push --force origin main\n)",
        "for b in a; do out=$(git push --force origin main\n); done",
        'echo "$(\ngit push --force origin main\n)"',
    ], ids=["pipe-continues", "closer-on-next-line", "loop-body", "double-quoted"])
    def test_multiline_substitution_body_is_scanned(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "bash -c 'echo \\\"hi; git push --force origin main'",
        "bash -c 'printf \"%s\\n\" \"a\\\"b\"; git push --force origin main'",
    ], ids=["odd-escaped-quote", "balanced-escaped-quote"])
    def test_backslash_inside_single_quotes_is_literal(self, guard_script, repo_on, cmd):
        """Dropping the backslash flips quote parity when the body is re-lexed."""
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "bash <<< 'git push --force origin main'",
        'sh <<< "git push --force origin main"',
    ])
    def test_here_string_operand_is_scanned(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "$(true) git push --force origin main",
        "`true` git push --force origin main",
    ])
    def test_leading_substitution_does_not_hide_git(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "echo $(echo $(echo $(echo $(git -C /tmp push -f origin main))))",
        "echo $(echo $(echo $(echo $(git push --mirror))))",
    ])
    def test_depth_bound_fallback_fails_closed(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_depth_bound_fallback_leaves_nonforce_push_allowed(self, guard_script, repo_on):
        result = run_guard(
            guard_script,
            "echo $(echo $(echo $(echo $(git push origin feature/x))))",
            cwd=str(repo_on("feature")),
        )
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "git push --force -- $(echo origin main)",
        "git push --force --no-thin $(echo origin main)",
        "git push --force -4 $(echo origin main)",
    ])
    def test_boolean_flag_does_not_consume_dynamic_destination(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_redirect_with_pipe_operator_is_syntax_not_argv(self, guard_script, repo_on):
        result = run_guard(
            guard_script, "git push --force origin >| /dev/null main", cwd=str(repo_on("feature"))
        )
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "bash -lc 'echo ok'",
        "git commit -m 'document git push --force origin main'",
        "bash -c 'echo ok' 'ignored; git push --force origin main'",
        "env GIT_TRACE=1 git push -u origin feature/x",
        "cat <(echo hi) /dev/null",
    ])
    def test_wrapper_and_substitution_scans_do_not_over_block(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 0 and result.stderr == ""

    # Everything after a wrapper prefix is code. These pin that class:
    # any wrapper that runs a string, crossed with the ways a script body can be spelled.
    _WRAPPERS = [
        "bash -c {q}", "bash -lc {q}", "bash -ce {q}", "bash -c -e {q}", "/bin/sh -c {q}",
        "sudo bash -c {q}", "sudo /bin/bash -c {q}", "env X=1 bash -c {q}", "env -S {q}",
        "env -iS {q}", "timeout 5 sh -c {q}", "nohup bash -c {q}", "xargs -I{{}} sh -c {q}",
        "kubectl exec p -- sh -c {q}", "docker exec c bash -c {q}", "ssh host {q}",
        "ssh -L 80:x:80 host {q}", "watch -n 1 {q}", "sudo -s {q}", "script -qc {q} /dev/null",
        "flock lock -c {q}", "eval {q}", "su -c {q}", "su --command={q}",
    ]
    _BODIES = [
        "git push --force origin main",
        "X=1 git push --force origin main",
        "cd /repo\ngit push --force origin main",
        "direnv exec . git push --force origin main",
    ]

    @pytest.mark.parametrize(
        "body", _BODIES, ids=["plain", "single-letter-assign", "newline", "runner"]
    )
    @pytest.mark.parametrize("wrapper", _WRAPPERS)
    def test_wrapper_string_is_code_for_every_body_shape(
        self, guard_script, repo_on, wrapper, body
    ):
        cmd = wrapper.replace("{q}", "'" + body + "'")
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "sudo python3 -c \"import os; os.system('git push --force origin main')\"",
        "env perl -e 'system(\"git push --force origin main\")'",
        "bash -c \"echo 'git push --force origin main'\"",
    ])
    def test_quoted_string_inside_wrapper_body_is_code(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "eval \"$(echo 'git push --force origin main')\"",
        "bash -c \"$(echo 'git push --force origin main')\"",
        "sudo eval \"`echo 'git push --force origin main'`\"",
        "ssh host \"$(echo 'git push --force origin main')\"",
    ])
    def test_substitution_producing_wrapper_script_is_code(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git rebase --exec='git push --force origin main' HEAD~1",
        "git rebase -x 'git push --force origin main' HEAD~1",
        "git submodule foreach 'git push --force origin main'",
        "git -c alias.x='!git push --force origin main' x",
        "git filter-branch --tree-filter 'git push --force origin main' HEAD",
    ])
    def test_git_command_runner_string_is_code(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "X=1 git push --force origin main",
        "a=1 b=2 git push --force origin main",
        "/usr/bin/env git push --force origin main",
        "/usr/bin/sudo git push --force origin main",
        "if true; then :; else git push --force origin main; fi",
        ">/dev/null git push --force origin main",
        "2>&1 git push --force origin main",
    ])
    def test_prefix_forms_do_not_hide_git(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "echo $(echo $(echo $(echo $(git push origin main --force; echo ok))))",
        "echo $(echo $(echo $(echo $(echo $(git push --force)))))",
    ])
    def test_depth_fallback_accepts_separator_after_flag(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git add docs/r\u00e9sum\u00e9.md",
        "git commit -m r\u00e9sum\u00e9",
        "git push origin feature/\u00e9",
        "echo \u0434; git status",
    ])
    def test_non_ascii_arguments_do_not_break_the_scan(self, guard_script, repo_on, cmd):
        """BSD awk aborts on a lone multibyte byte under a UTF-8 locale; the
        lexer must not turn that into a block on every git command.
        """
        result = run_guard(
            guard_script, cmd, cwd=str(repo_on("feature")),
            env={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
        )
        assert result.returncode == 0 and result.stderr == ""

    def test_non_ascii_argument_does_not_hide_force_push(self, guard_script, repo_on):
        result = run_guard(
            guard_script, "git push --force origin main \u00e9", cwd=str(repo_on("feature")),
            env={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
        )
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "cat <<< 'git push --force origin main'",
        "git commit -m 'document git push --force origin main'",
        "rtk git commit -m 'document git push --force origin main'",
        "env X=1 git commit -m 'document git push --force origin main'",
        "docker exec c git commit -m 'document git push --force origin main'",
        "git log --grep='git push --force origin main'",
        "sudo apt-get install -y 'a b'",
        "ssh host 'ls -la /tmp'",
    ])
    def test_quoted_text_that_is_data_stays_allowed(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "git push --force --branches origin",
        "git -C/tmp push --force",
        "git --git-dir /tmp/x.git push --force",
        "git --work-tree /tmp/x push --force",
    ])
    def test_all_refs_and_context_options_fail_closed(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_large_wrapper_operand_scans_in_linear_time(self, guard_script, repo_on):
        """bash 3.2's pattern substitution is superlinear in match count, so
        converting quoted-newline markers there took minutes for a long
        script operand; the hook must stay well inside its timeout.
        """
        body = "\n".join(["echo hello world; git status | grep foo"] * 600)
        started = time.monotonic()
        result = run_guard(
            guard_script, f"sudo sh -c '{body}'", cwd=str(repo_on("feature"))
        )
        elapsed = time.monotonic() - started
        assert result.returncode == 0 and result.stderr == ""
        assert elapsed < 15, f"scan took {elapsed:.1f}s"

    @pytest.mark.parametrize("cmd", [
        "sudo -u git bash -lc 'git push -f origin main'",
        "ssh -i ~/.ssh/git host 'git push -f origin main'",
        "docker exec -w /srv/git ctr bash -lc 'git push --force origin main'",
        "docker exec -u git ctr sh -ec 'git push --force origin master'",
        "ssh -l git host \"bash -lc 'git push -f origin main'\"",
    ])
    def test_option_value_named_git_is_not_the_git_command(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "bash -c 'git push -f origin \"$1\"' _ main",
        "sh -c 'git push \"$@\"' _ --force origin main",
        "sudo bash -c 'git push -f origin $0' main",
        "bash -lc 'git push --force \"$1\" \"$2\"' _ origin master",
    ])
    def test_script_positional_arguments_reach_the_scan(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "$(echo)git push -f origin main",
        "sudo $(true)git push --force origin main",
        "env \"$(echo)\"git push -f origin main",
    ])
    def test_substitution_glued_to_git_does_not_hide_it(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "FOO=1 python3 -c 'import os; os.system(\"git push -f origin main\")'",
        "CI=true perl -e 'system(\"git push --force origin master\")'",
        "GIT_TERMINAL_PROMPT=0 node -e 'require(\"child_process\").execSync(\"git push -f origin main\")'",
        "FOO=1 find . -maxdepth 0 -exec sh -c 'git push -f origin main' \\;",
        "FOO=1 awk 'BEGIN{system(\"git push -f origin main\")}'",
        "python3\t-c 'import os; os.system(\"git push -f origin main\")'",
        "python3 -c \"import os; os.system('git\tpush\t-f\torigin\tmain')\"",
    ], ids=["python", "perl", "node", "find-exec", "awk", "tab", "quoted-tabs"])
    def test_assignment_or_tab_prefix_unlocks_interpreter_strings(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git fetch --upload-pack 'git push -f origin main' /tmp/x",
        "git push --receive-pack='git push -f origin main' /tmp/x",
        "git grep -O'git push -f origin main' foo",
        "git bisect run sh -c 'git push -f origin main'",
        "git difftool --extcmd='git push -f origin main'",
    ])
    def test_git_options_that_run_a_command_string_are_scanned(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push -f origin HEAD",
        "git push --force origin @",
        "printf 'x\\n' | xargs -I '{}' git push -f origin '{}'",
    ])
    def test_symbolic_destination_checks_the_current_branch(self, guard_script, repo_on, cmd):
        blocked = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert blocked.returncode == 2 and "BLOCKED" in blocked.stderr
        allowed = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert allowed.returncode == 0 and allowed.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "gh pr create --title t --body \"$(cat <<'EOF'\nUse `git push --force origin main` with care.\nEOF\n)\"",
        "gh pr create --body \"$(cat <<'EOF'\ngit push --force origin main\nEOF\n)\"",
        "git commit -m \"$(cat <<-'EOF'\n\tgit push --force origin main\n\tEOF\n)\"",
    ], ids=["inline-code", "line-starts-with-push", "tab-stripped"])
    def test_quoted_heredoc_in_substitution_is_data(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "bash -c \"$(cat <<'EOF'\ngit push --force origin main\nEOF\n)\"",
        "eval \"$(cat <<'EOF'\ngit push --force origin main\nEOF\n)\"",
        "echo \"$(bash <<'EOF'\ngit push --force origin main\nEOF\n)\"",
        "cat <<EOF\n$(git push --force origin main)\nEOF",
    ], ids=["bash-c", "eval", "shell-consumer", "unquoted-expands"])
    def test_heredoc_that_feeds_a_shell_is_still_code(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    # Behaviours that no other test in this class pins.
    @pytest.mark.parametrize("cmd", [
        "git push &>/dev/null --force origin main",
        "echo `echo a\ngit push --force origin main`",
        "{ git push --force origin main; }",
        "fish -c 'git push --force origin main'",
        "ksh -c 'git push --force origin main'",
        "ssh host <<< 'git push --force origin main'",
        "echo $(echo $(echo $(echo $(git push origin +main))))",
        "echo $(echo $(echo $(echo $(git push '--force' origin feature/x))))",
        "bash -c 'echo hi' \"$(git push --force origin main)\"",
    ], ids=[
        "amp-redirect", "backtick-newline", "brace-group", "fish", "ksh", "here-string-ssh",
        "depth-plus-refspec", "depth-quoted-flag", "restored-after-operand",
    ])
    def test_additional_blocked_shapes(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push --force --push-option=`date`x origin feature/x",
        "grep sudo 'git push --force origin main' f",
        ">$(date +%s).log; git status",
        "sudo sh -c 'echo ok' && echo 'git push --force origin main'",
    ], ids=["backtick-glued", "grep-not-wrapper", "empty-array-guard", "data-after-and"])
    def test_additional_allowed_shapes(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0 and result.stderr == ""

    def test_empty_context_option_value_is_not_a_context(self, guard_script, repo_on):
        """`-C ''` names no other repo, so the implicit push checks the current branch."""
        allowed = run_guard(guard_script, "git -C '' push --force", cwd=str(repo_on("feature")))
        assert allowed.returncode == 0 and allowed.stderr == ""
        blocked = run_guard(guard_script, "git -C '' push --force", cwd=str(repo_on("main")))
        assert blocked.returncode == 2 and "BLOCKED" in blocked.stderr

    def test_scanner_failure_fails_closed(self, guard_script, repo_on, tmp_path):
        """An internal scan error must block, not silently disable the guard."""
        real_awk = shutil.which("awk")
        shim_dir = tmp_path / "shim"
        shim_dir.mkdir()
        shim = shim_dir / "awk"
        shim.write_text(
            '#!/bin/sh\ncase "$*" in *redirect_target*) exit 1 ;; esac\n'
            f'exec {real_awk} "$@"\n'
        )
        shim.chmod(0o755)
        env = {"PATH": f"{shim_dir}:{os.environ['PATH']}"}
        result = run_guard(
            guard_script, "git push origin feature/x", cwd=str(repo_on("feature")), env=env
        )
        assert result.returncode == 2 and "BLOCKED" in result.stderr


class TestSubstitutionAndFlagHardening:
    """Heredoc skip, depth-cap fallback, dynamic flags and consumed slots in the push lexer."""

    @pytest.mark.parametrize("cmd", [
        "git commit -m \"$(cat <<'EOT' | sh -s\ngit push --force origin main\nEOT\n)\"",
        "git commit -m \"$(echo ' cat <<\"EOT\"'\ngit push --force origin main\nEOT\n)\"",
        "git commit -m \"$(cat <<'EOT' | xargs -I{} sh -c {}\ngit push --force origin main\nEOT\n)\"",
        "gh pr create --body \"$(cat <<'EOT' | sh -s\ngit push --force origin main\nEOT\n)\"",
    ], ids=["piped-to-sh", "quoted-lookalike", "piped-to-xargs", "pr-body-piped"])
    def test_heredoc_that_is_piped_or_only_looks_like_one_is_code(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "echo $(echo $(echo $(echo $(g\\it push --force origin main))))",
        "echo $(echo $(echo $(echo $(git push \\-\\-force origin main))))",
        "echo $(echo $(echo $(echo $(git push -\\f origin main))))",
    ], ids=["split-word", "escaped-long-flag", "escaped-short-flag"])
    def test_depth_cap_fallback_normalises_backslashes(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "git push $(echo -)f origin main",
        "git push $(echo --)force origin main",
    ])
    def test_glued_substitution_spelling_of_a_force_flag_is_dynamic(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_glued_dynamic_flag_with_implicit_destination_checks_the_current_branch(
        self, guard_script, repo_on
    ):
        cmd = "git push $(echo -)f origin"
        blocked = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert blocked.returncode == 2 and "BLOCKED" in blocked.stderr
        allowed = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert allowed.returncode == 0 and allowed.stderr == ""

    @pytest.mark.parametrize("cmd", [
        'git push origin "v$(cat VERSION)"',
        'git push origin "release-$(date +%F)"',
        'git push origin "$(git rev-parse HEAD)":main',
        'git push origin "$(git branch --show-current)"',
    ])
    def test_dynamic_word_that_cannot_be_a_flag_stays_allowed_for_a_plain_push(
        self, guard_script, repo_on, cmd
    ):
        """A flag starts with a dash, so a literal prefix or a refspec colon rules it out."""
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("flag", [
        "--no-follow-tags", "--no-tags", "--no-prune", "--no-set-upstream", "--no-delete",
        "--some-unknown-flag",
    ])
    def test_boolean_or_unknown_flag_does_not_hide_a_dynamic_destination(
        self, guard_script, repo_on, flag
    ):
        cmd = f"git push --force {flag} $(echo origin main)"
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_value_taking_flag_may_carry_a_dynamic_value(self, guard_script, repo_on):
        result = run_guard(
            guard_script,
            "git push --force --push-option \"$(date)\" origin feature/x",
            cwd=str(repo_on("main")),
        )
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "if false; then :; elif git push --force origin main; then :; fi",
        "coproc git push --force origin main",
        "find . -maxdepth 0 -exec git push --force origin main \\;",
        "git push --force origin $\"main\"",
        "git push --force origin $'main'",
    ], ids=["elif", "coproc", "find-exec", "locale-string", "ansi-c-string"])
    def test_command_position_and_dollar_quote_forms_are_classified(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_dynamic_destination_block_explains_itself(self, guard_script, repo_on):
        result = run_guard(
            guard_script, "git push --force origin $(echo feature)", cwd=str(repo_on("feature"))
        )
        assert result.returncode == 2
        assert "protected branch" not in result.stderr
        assert "dynamic" in result.stderr and "--force-with-lease" in result.stderr

    def test_depth_cap_block_explains_itself(self, guard_script, repo_on):
        cmd = "echo $(echo $(echo $(echo $(git push --force origin feature/x))))"
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2
        assert "protected branch" not in result.stderr
        assert "too deeply" in result.stderr

    def test_lexer_awk_uses_no_posix_bracket_classes(self):
        """mawk before 1.3.4 lacks bracket classes; there the class never matches and
        words stop splitting, so the lexer must spell its whitespace set out.
        """
        text = GUARD.read_text()
        start = text.index("_push_token_awk='")
        end = text.index("\n'\n", start)
        assert "[[:" not in text[start:end]

    @pytest.mark.parametrize("cmd", [
        "pi -p r\u00e9sum\u00e9",
        "echo caf\u00e9; pi -p x",
    ])
    def test_nested_pi_detector_survives_non_ascii_arguments(self, guard_script, repo_on, cmd):
        result = run_guard(
            guard_script, cmd, cwd=str(repo_on("feature")),
            env={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
        )
        assert result.returncode == 2 and "BLOCKED" in result.stderr


class TestHeredocAndCandidateEdges:
    """Heredoc delimiter handling, dynamic-flag candidates and find -exec boundaries."""

    @pytest.mark.parametrize("cmd", [
        "git commit -m \"$(cat <<'EOF'\nbody\nEOF \n)\" && git push --force origin main",
        "git commit -m \"$(cat <<'EOF'\nbody\n)\" && git push --force origin main",
    ], ids=["trailing-space-delimiter", "missing-delimiter"])
    def test_unmatched_heredoc_delimiter_leaves_the_rest_as_code(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_terminated_heredoc_substitution_without_a_push_stays_allowed(
        self, guard_script, repo_on
    ):
        cmd = "git commit -m \"$(cat <<'EOF'\nbody\nEOF\n)\" && git status"
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "git commit -F - <<'EOF'\nfix: don't crash\nEOF\ngit push --force origin main",
        "git commit -F - <<'EOF'\nit's fine\nEOF\ngit push -f origin main",
        "cat > notes.txt <<'EOF'\ndon't\nEOF\ngit push --force origin main",
    ], ids=["commit-file", "apostrophe-again", "redirect-before"])
    def test_apostrophe_in_quoted_top_level_heredoc_does_not_hide_a_later_push(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "cat <<'EOF'\ngit push --force origin main\nEOF",
        "git commit -F - <<'EOF'\nnote: git push --force origin main\nEOF",
    ], ids=["cat-body", "commit-body"])
    def test_quoted_top_level_heredoc_body_is_data_for_a_plain_consumer(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "bash <<'EOF'\ngit push --force origin main\nEOF",
        "cat <<'EOF' | sh\ngit push --force origin main\nEOF",
        "ssh host <<'EOF'\ngit push --force origin main\nEOF",
        "bash <<'EOF' && echo done\ngit push --force origin main\nEOF",
    ], ids=["shell-consumer", "piped-to-shell", "wrapper-consumer", "owner-before-and"])
    def test_quoted_top_level_heredoc_feeding_a_shell_is_code(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        'git push origin "$(date +%F)-snapshot"',
        'git push --force-with-lease origin "$(date +%F)-x"',
        'git push origin "$(git rev-parse --short HEAD)-backup"',
    ])
    def test_substitution_led_word_that_cannot_finish_a_flag_is_not_a_force_candidate(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "git push $(echo -)f origin main",
        "git push $(echo --)force origin main",
        "git push $(echo --)orce origin main",
        "git push $(echo -)uf origin main",
    ])
    def test_substitution_led_word_that_can_finish_a_flag_is_still_a_candidate(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    def test_glued_candidate_block_says_it_may_be_a_force_push(self, guard_script, repo_on):
        result = run_guard(guard_script, "git push $(echo -)f origin", cwd=str(repo_on("main")))
        assert result.returncode == 2
        assert "may be a force push" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "find . -name '*.md' -exec grep -ln 'git push --force' {} +",
        "find docs -type f -execdir grep -l 'git push --force origin main' {} \\;",
        "find . -ok grep 'git push --force' {} \\;",
    ], ids=["exec-grep", "execdir-grep", "ok-grep"])
    def test_find_exec_of_a_search_is_data(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("main")))
        assert result.returncode == 0 and result.stderr == ""

    @pytest.mark.parametrize("cmd", [
        "find . -maxdepth 0 -exec git push --force origin main \\;",
        "find . -maxdepth 0 -execdir git push -f origin main {} +",
        "find . -maxdepth 0 -exec sh -c 'git push --force origin main' \\;",
        "find . -name '*.md' -ok git push --force origin main \\;",
    ], ids=["exec-git", "execdir-git", "exec-sh-c", "ok-git"])
    def test_find_exec_of_a_push_is_code(self, guard_script, repo_on, cmd):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        "$(cat <<'EOT'\ngit push --force origin main\nEOT\n)",
        "X=1 $(cat <<'EOT'\ngit push --force origin main\nEOT\n)",
    ], ids=["command-word", "after-assignment"])
    def test_substitution_used_as_the_command_word_runs_its_output(
        self, guard_script, repo_on, cmd
    ):
        result = run_guard(guard_script, cmd, cwd=str(repo_on("feature")))
        assert result.returncode == 2 and "BLOCKED" in result.stderr


class TestHardResetBlocker:
    @pytest.mark.parametrize("branch", ["main", "master", "release/2025-01"])
    def test_blocked_on_protected_branch(self, guard_script, repo_on, branch):
        repo = repo_on(branch)
        result = run_guard(guard_script, "git reset --hard HEAD~1", cwd=str(repo))
        assert result.returncode == 2, (
            f"Expected BLOCKED on branch {branch!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    def test_allowed_on_feature_branch(self, guard_script, repo_on):
        repo = repo_on("feature/x")
        result = run_guard(guard_script, "git reset --hard HEAD~1", cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED on feature/x, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

    def test_soft_reset_always_allowed(self, guard_script, repo_on):
        repo = repo_on("main")
        result = run_guard(guard_script, "git reset --soft HEAD~1", cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED for --soft on main, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )


# ──────────────────────────────────────────────
# nested non-interactive `pi` session — bash escape hatch around the
# subagent dispatcher's --exclude-tools recursion guard
# ──────────────────────────────────────────────

class TestNestedPiSessionBlocker:
    @pytest.mark.parametrize("cmd", [
        # blocked: direct -p/--print invocations
        'pi -p "review this"',
        "pi --print \"x\"",
        # blocked: tab / backslash-continuation segment vectors
        "pi\t-p x",
        "pi \\\n-p \"hello\"",
        # blocked: backtick / $(...) substitution boundaries
        "`pi -p x`",
        "$(pi -p y)",
        "echo $(pi -p x)",
        # blocked: quoted / path-qualified / prefixed forms
        '"pi" -p x',
        'bash -c "pi -p x"',
        "/usr/local/bin/pi -p x",
        "npx pi -p hello",
        "PI_OFFLINE=1 pi -p x",
        "cd /tmp && pi -p x",
        "pi --model foo/bar -p prompt",
        # a separator character embedded inside a QUOTED pi argument must not be treated as
        # a segment break — the vector that defeated the segmenter's first version
        'pi -m ";" -p file.txt',
        'pi --system-prompt "a;b" --print',
        # a backslash-continuation split mid-token must still resolve to a single "pi" word,
        # not two separate tokens
        "p\\\ni -p x",
        # parity boundary: an EVEN trailing-backslash count is not a continuation — it must
        # not swallow a separate, genuinely recursive pi invocation on the next line
        "echo hi\\\\\npi -p x",
        # a backslash-ESCAPED separator between the pi token and the flag must not be
        # treated as a real segment break — bash consumes it as a literal argument byte
        'pi \\; -p "review this"',
        "pi --model a\\&b -p hi",
        # a trailing backslash INSIDE a comment has no continuation meaning in real bash —
        # must not let the comment absorb a real recursive pi call on the next line
        "echo a # note \\\npi -p x",
        # a REAL (unescaped) newline INSIDE a quoted argument is a literal argument byte in
        # bash, not a segment break — a multi-line -m message is the natural shape a
        # dispatched subagent would actually write
        'pi -m "a\nb" -p x',
        'pi "a\nb" --print',
        # case-insensitive command-name resolution: on a case-insensitive filesystem (macOS
        # default), "Pi"/"PI" resolve to the same binary as "pi" — the command-NAME token
        # must be matched case-insensitively even though flags stay case-sensitive
        "Pi -p x",
        "PI -p x",
        "pI --print x",
    ])
    def test_blocked(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 2, (
            f"Expected BLOCKED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert "BLOCKED" in result.stderr

    @pytest.mark.parametrize("cmd", [
        # allowed: non-recursive pi subcommands
        "pi --version",
        "pi list",
        "pi auth check",
        "pi update self",
        "pi",
        # allowed: git -p is unrelated to the pi CLI
        "git log -p",
        "git diff -p -- foo",
        "git log -p && pi list",
        "git log -p; pi --version",
        # allowed: pi-shaped substrings that aren't the pi command token
        "pip install foo",
        "python -p",
        "mkdir -p src/api",
        "docker run -p 8080:80 img",
        "ls /opt/pi",
        "grep -rn pi docs/",
        "cat notes.md # pi -p x",
        # command-name case-insensitivity must not extend to flags — real CLI parsers are
        # case-sensitive for flag spellings, so "--PRINT" is not "--print"
        "Pi --PRINT x",
        "Pi --version",
        "PI list",
    ])
    def test_allowed(self, guard_script, cmd):
        result = run_guard(guard_script, cmd)
        assert result.returncode == 0, (
            f"Expected ALLOWED for {cmd!r}, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )
        assert result.stderr == ""


# ──────────────────────────────────────────────
# short-circuit: non-rm/non-git commands skip grep
# ──────────────────────────────────────────────

class TestShortCircuit:
    def _run_with_shims(self, script, cmd, tmp_path):
        trace = tmp_path / "trace"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        real_jq = shutil.which("jq")
        real_grep = shutil.which("grep")
        for tool, real in [("jq", real_jq), ("grep", real_grep)]:
            shim = bin_dir / tool
            shim.write_text(
                f'#!/bin/sh\necho "{tool}" >> "{trace}"\nexec "{real}" "$@"\n'
            )
            shim.chmod(0o755)
        env = dict(_CLEAN_ENV)
        env["PATH"] = f"{bin_dir}:{_CLEAN_ENV.get('PATH', '')}"
        run_guard(script, cmd, env=env)
        return trace.read_text() if trace.exists() else ""

    @pytest.mark.parametrize("cmd", [
        "ls .", "cat foo.txt", "echo hello", "make build",
        "pip install foo", "mkdir -p src/api", "python -m pytest",
    ])
    def test_no_grep_for_safe_commands(self, guard_script, cmd, tmp_path):
        trace = self._run_with_shims(guard_script, cmd, tmp_path)
        assert "jq" in trace, f"Expected jq to run for {cmd!r}"
        assert "grep" not in trace, f"Expected grep to be skipped for {cmd!r}"

    @pytest.mark.parametrize("cmd", ["rm -rf /tmp/foo", "git status"])
    def test_grep_runs_for_rm_and_git(self, guard_script, cmd, tmp_path):
        trace = self._run_with_shims(guard_script, cmd, tmp_path)
        assert "jq" in trace, f"Expected jq to run for {cmd!r}"
        assert "grep" in trace, f"Expected grep to run for {cmd!r}"

    def test_grep_runs_for_pi(self, guard_script, tmp_path):
        trace = self._run_with_shims(guard_script, "pi -p x", tmp_path)
        assert "jq" in trace, "Expected jq to run for 'pi -p x'"
        assert "grep" in trace, "Expected grep to run for 'pi -p x'"


# ──────────────────────────────────────────────
# pre-push hook — validate + the covering tests (behaviour: test_test_selection_scripts.py)
# ──────────────────────────────────────────────

class TestPrePushHook:
    """Verify .githooks/pre-push contains the expected invocations."""

    PRE_PUSH = Path(__file__).parent.parent / ".githooks" / "pre-push"

    def test_pre_push_runs_validate(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "validate.sh" in content, "pre-push hook must invoke validate.sh"

    def test_pre_push_still_requires_pytest_and_names_the_tests_dir(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "import pytest" in content and "tests/" in content, (
            "pre-push hook must keep failing fast when pytest is missing"
        )

    def test_pre_push_runs_the_selected_tests_through_the_runner(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "scripts/select-tests.sh" in content
        assert "scripts/test-all.sh" in content
        assert "SWE_WORKBENCH_PREPUSH_BUDGET" in content


# ──────────────────────────────────────────────
# worktree permission-grant hook — wiring
# ──────────────────────────────────────────────

class TestWorktreePermissionHookWiring:
    """Verify the Read|Edit|Write PreToolUse entry is present and correctly wired."""

    HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"

    def test_rw_entry_present(self):
        data = json.loads(self.HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [
            e for e in data["hooks"]["PreToolUse"]
            if e.get("matcher") == "Read|Edit|Write"
        ]
        assert entries, "Read|Edit|Write PreToolUse entry missing from hooks.json"
        assert any(
            "worktree_permission_grant.sh" in e["hooks"][0]["command"] for e in entries
        ), f"No entry references worktree_permission_grant.sh; entries: {entries}"

    def test_hook_script_exists(self):
        script = Path(__file__).parent.parent / "hooks" / "worktree_permission_grant.sh"
        assert script.exists(), f"Missing hook script: {script}"
        assert os.access(script, os.X_OK), f"Hook script not executable: {script}"


# ──────────────────────────────────────────────
# skill autoload hint hook — wiring (T3)
# ──────────────────────────────────────────────


class TestSkillAutoloadHookWiring:
    """T3 — PostToolUse Read|Edit|Write skill-autoload hint hook is registered
    and non-blocking (always exit 0).
    """

    HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"
    SCRIPT = Path(__file__).parent.parent / "hooks" / "skill_autoload_hint.sh"

    def test_posttooluse_entry_present(self):
        data = json.loads(self.HOOKS_JSON.read_text(encoding="utf-8"))
        post_entries = data["hooks"].get("PostToolUse", [])
        entries = [
            e for e in post_entries
            if e.get("matcher") == "Read|Edit|Write"
        ]
        assert entries, (
            "PostToolUse Read|Edit|Write entry missing from hooks.json — "
            "skill_autoload_hint.sh must be registered there."
        )
        assert any(
            "skill_autoload_hint.sh" in e["hooks"][0]["command"] for e in entries
        ), f"No entry references skill_autoload_hint.sh; entries: {entries}"

    def test_hook_script_exists_and_executable(self):
        assert self.SCRIPT.exists(), f"Missing hook script: {self.SCRIPT}"
        assert os.access(self.SCRIPT, os.X_OK), (
            f"Hook script not executable: {self.SCRIPT}"
        )

    def test_hook_is_nonblocking(self, tmp_path):
        """Script must exit 0 for well-formed input with a session_id."""
        import subprocess
        from conftest import _CLEAN_ENV

        env = dict(_CLEAN_ENV)
        env["TMPDIR"] = str(tmp_path)  # isolate sentinel to this test run
        result = subprocess.run(
            [str(self.SCRIPT)],
            input='{"session_id": "test-session-abc-123", "tool_input": {"file_path": "/tmp/foo.py"}}',
            text=True,
            capture_output=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"skill_autoload_hint.sh exited {result.returncode} — must be "
            f"non-blocking (exit 0 always). stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("payload", [
        "",                                                # empty stdin
        "not json at all",                                 # malformed JSON
        '{"tool_input": {}}',                              # missing file_path
        '{"tool_input": {"file_path": "/tmp/noext"}}',     # no extension
        '{"tool_input": {"file_path": "/tmp/.hidden"}}',   # dotfile (no real ext)
    ])
    def test_hook_is_nonblocking_adversarial(self, payload):
        """Script must exit 0 for any malformed or edge-case input."""
        import subprocess
        from conftest import _CLEAN_ENV

        result = subprocess.run(
            [str(self.SCRIPT)],
            input=payload,
            text=True,
            capture_output=True,
            env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 0, (
            f"skill_autoload_hint.sh exited {result.returncode} for payload "
            f"{payload!r}. stderr: {result.stderr!r}"
        )

    def test_hook_deduplicates_within_session(self, tmp_path):
        """Same session+extension emits output on first call, silent on second."""
        import subprocess
        from conftest import _CLEAN_ENV

        env = dict(_CLEAN_ENV)
        env["TMPDIR"] = str(tmp_path)  # isolate sentinel dir to this test run
        payload = '{"session_id": "dedup-test-session", "tool_input": {"file_path": "/src/app.py"}}'

        first = subprocess.run(
            [str(self.SCRIPT)], input=payload, text=True, capture_output=True, env=env,
        )
        second = subprocess.run(
            [str(self.SCRIPT)], input=payload, text=True, capture_output=True, env=env,
        )
        assert first.returncode == 0, f"First call failed: {first.stderr!r}"
        assert second.returncode == 0, f"Second call failed: {second.stderr!r}"
        assert first.stdout.strip(), "First call should emit a hint but produced no output"
        assert not second.stdout.strip(), (
            "Second call for the same session+skill should be a silent no-op, "
            f"but produced: {second.stdout!r}"
        )

    def test_hook_different_skills_both_emit(self, tmp_path):
        """Different extensions in the same session each get one hint."""
        import subprocess
        from conftest import _CLEAN_ENV

        env = dict(_CLEAN_ENV)
        env["TMPDIR"] = str(tmp_path)
        py_payload = '{"session_id": "multi-skill-session", "tool_input": {"file_path": "/src/app.py"}}'
        go_payload = '{"session_id": "multi-skill-session", "tool_input": {"file_path": "/src/main.go"}}'

        py_result = subprocess.run(
            [str(self.SCRIPT)], input=py_payload, text=True, capture_output=True, env=env,
        )
        go_result = subprocess.run(
            [str(self.SCRIPT)], input=go_payload, text=True, capture_output=True, env=env,
        )
        assert py_result.returncode == 0 and go_result.returncode == 0
        assert py_result.stdout.strip(), "Python hint should have been emitted"
        assert go_result.stdout.strip(), "Go hint should have been emitted"
        assert "language-python" in py_result.stdout
        assert "language-go" in go_result.stdout


# ──────────────────────────────────────────────
# Differential acceptance criterion — direct-invocation half. tests/test_pi_extension.py
# runs the SAME BASH_GUARD_FIXTURES set through pi/extensions/guards.ts and asserts an
# identical verdict; a future guard-semantics change has to update pi_guard_fixtures.py and
# both suites re-verify against it.
# ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def branch_repos(tmp_path_factory):
    """One committed temp repo per branch the fixtures run under."""
    branches = set(SHARED_FIXTURE_BRANCHES) | set(BASH_GUARD_BRANCH_FIXTURES)
    return {
        branch: make_branch_repo(
            tmp_path_factory.mktemp("fixture-repo") / "repo", branch, _CLEAN_ENV
        )
        for branch in sorted(branches)
    }


def _assert_verdict(result, cmd, expect_blocked, where):
    if expect_blocked:
        assert result.returncode == 2 and "BLOCKED" in result.stderr, (
            f"expected BLOCKED for {cmd!r} on {where}, got exit {result.returncode}: {result.stderr!r}"
        )
    else:
        assert result.returncode == 0 and result.stderr == "", (
            f"expected ALLOWED for {cmd!r} on {where}, got exit {result.returncode}: {result.stderr!r}"
        )


class TestDifferentialFixtures:
    @pytest.mark.parametrize("cmd,expect_blocked", BASH_GUARD_FIXTURES)
    def test_direct_invocation_matches_expected_verdict(self, guard_script, cmd, expect_blocked):
        result = run_guard(guard_script, cmd)
        _assert_verdict(result, cmd, expect_blocked, "the default cwd")

    @pytest.mark.parametrize("branch", SHARED_FIXTURE_BRANCHES)
    @pytest.mark.parametrize("cmd,expect_blocked", BASH_GUARD_FIXTURES)
    def test_shared_verdict_holds_on_every_branch(
        self, guard_script, branch_repos, branch, cmd, expect_blocked
    ):
        result = run_guard(guard_script, cmd, cwd=str(branch_repos[branch]))
        _assert_verdict(result, cmd, expect_blocked, branch)

    @pytest.mark.parametrize(
        "branch,cmd,expect_blocked",
        [(b, c, e) for b, rows in BASH_GUARD_BRANCH_FIXTURES.items() for c, e in rows],
    )
    def test_branch_fixture_verdict(self, guard_script, branch_repos, branch, cmd, expect_blocked):
        result = run_guard(guard_script, cmd, cwd=str(branch_repos[branch]))
        _assert_verdict(result, cmd, expect_blocked, branch)


# ──────────────────────────────────────────────
# Scan infrastructure — tool failure policy and the oversize cap. These cannot be shared
# fixture rows: the payloads are larger than the Pi driver's argv allows, and the tests
# change which programs the guard can run.
# ──────────────────────────────────────────────

_OVERSIZE_FILLER = "a" * 200_000


@pytest.fixture
def awkless_path(tmp_path):
    """A PATH holding everything the guard runs except awk."""
    shim = tmp_path / "awkless-bin"
    shim.mkdir()
    for tool in ("jq", "tr", "grep", "git", "bash", "env", "cat"):
        found = shutil.which(tool)
        assert found, f"{tool} must exist to build the shim"
        (shim / tool).symlink_to(found)
    assert not (shim / "awk").exists()
    return str(shim)


class TestScanToolFailure:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "git push --force origin main",
        "ls -la",
    ])
    def test_missing_awk_blocks_instead_of_allowing(self, guard_script, awkless_path, cmd):
        result = run_guard(guard_script, cmd, env={"PATH": awkless_path})
        assert result.returncode == 2 and "BLOCKED" in result.stderr, (
            f"a guard that cannot run awk must fail closed for {cmd!r}: "
            f"exit {result.returncode}: {result.stderr!r}"
        )


class TestOversizeCommand:
    def _timed(self, guard_script, cmd):
        start = time.monotonic()
        result = run_guard(guard_script, cmd)
        return result, time.monotonic() - start

    def test_oversize_benign_command_is_allowed_quickly(self, guard_script):
        result, elapsed = self._timed(guard_script, f"echo {_OVERSIZE_FILLER}")
        assert result.returncode == 0 and result.stderr == ""
        assert elapsed < 2, f"oversize command took {elapsed:.2f}s"

    def test_oversize_command_with_unrelated_git_is_allowed(self, guard_script):
        result, elapsed = self._timed(guard_script, f"echo {_OVERSIZE_FILLER}; git status")
        assert result.returncode == 0 and result.stderr == ""
        assert elapsed < 2, f"oversize command took {elapsed:.2f}s"

    @pytest.mark.parametrize("tail", [
        "git push --force origin main",
        "git push -f origin feature/x",
        "git push origin +main",
    ])
    def test_oversize_force_push_blocks_on_any_branch(self, guard_script, tail):
        result, elapsed = self._timed(guard_script, f"echo {_OVERSIZE_FILLER}; {tail}")
        assert result.returncode == 2 and "BLOCKED" in result.stderr
        assert "too large" in result.stderr
        assert elapsed < 2, f"oversize command took {elapsed:.2f}s"

    def test_oversize_rm_is_still_blocked(self, guard_script):
        result, elapsed = self._timed(guard_script, f"echo {_OVERSIZE_FILLER}; rm -rf /")
        assert result.returncode == 2 and "BLOCKED" in result.stderr
        assert elapsed < 2, f"oversize command took {elapsed:.2f}s"

    @pytest.mark.parametrize("tail", ["pi -p x", "pi --print x"])
    def test_oversize_pi_print_is_blocked(self, guard_script, tail):
        result, elapsed = self._timed(guard_script, f"echo {_OVERSIZE_FILLER}; {tail}")
        assert result.returncode == 2 and "BLOCKED" in result.stderr
        assert elapsed < 2, f"oversize command took {elapsed:.2f}s"

    def test_command_under_the_cap_still_uses_the_exact_scan(self, guard_script):
        # 60 KB stays below the cap, so the full lexer decides and a feature-branch force push passes.
        result = run_guard(guard_script, f"echo {'a' * 60_000}; git push --force origin feature/x")
        assert result.returncode == 0, result.stderr


class TestAwkImplementation:
    def test_awk_is_mawk_when_the_mawk_leg_requires_it(self):
        # The CI mawk leg sets SWB_REQUIRE_MAWK=1 and shims `awk` to mawk; if the shim ever
        # stops applying, the guard tests would silently run on whatever awk the runner ships.
        if os.environ.get("SWB_REQUIRE_MAWK") != "1":
            pytest.skip("SWB_REQUIRE_MAWK is not set; the guard tests run on the system awk")
        result = subprocess.run(
            ["awk", "-W", "version"], capture_output=True, text=True, env=_CLEAN_ENV, timeout=10
        )
        assert "mawk" in (result.stdout + result.stderr).lower(), (
            f"awk on PATH is not mawk: {result.stdout!r} {result.stderr!r}"
        )
