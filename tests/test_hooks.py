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
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

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
        "true;\nrm -Rf $HOME",
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


# ──────────────────────────────────────────────
# implicit-branch force-push — branch-aware (requires temp git repo)
# ──────────────────────────────────────────────

class TestImplicitForcePushBlocker:
    """git push --force/-f with NO explicit refspec, relying on
    push.default/upstream, from a protected branch (issue #501 Block 2).
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

    def test_explicit_nonprotected_refspec_still_allowed(self, guard_script, repo_on):
        """An explicit non-protected refspec must not regress — Block 1
        already owns explicit protected refspecs, Block 2 only fires when
        no refspec is present at all.
        """
        repo = repo_on("main")
        result = run_guard(guard_script, "git push --force origin feat", cwd=str(repo))
        assert result.returncode == 0, (
            f"Expected ALLOWED, got exit {result.returncode}\n"
            f"stderr: {result.stderr!r}"
        )

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
        must not cause Block 2 to inspect the wrong invocation and miss the
        dangerous one.
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

    @pytest.mark.parametrize("cmd", ["ls .", "cat foo.txt", "echo hello", "make build"])
    def test_no_grep_for_safe_commands(self, guard_script, cmd, tmp_path):
        trace = self._run_with_shims(guard_script, cmd, tmp_path)
        assert "jq" in trace, f"Expected jq to run for {cmd!r}"
        assert "grep" not in trace, f"Expected grep to be skipped for {cmd!r}"

    @pytest.mark.parametrize("cmd", ["rm -rf /tmp/foo", "git status"])
    def test_grep_runs_for_rm_and_git(self, guard_script, cmd, tmp_path):
        trace = self._run_with_shims(guard_script, cmd, tmp_path)
        assert "jq" in trace, f"Expected jq to run for {cmd!r}"
        assert "grep" in trace, f"Expected grep to run for {cmd!r}"


# ──────────────────────────────────────────────
# pre-push hook — unchanged
# ──────────────────────────────────────────────

class TestPrePushHook:
    """Verify .githooks/pre-push contains the expected invocations."""

    PRE_PUSH = Path(__file__).parent.parent / ".githooks" / "pre-push"

    def test_pre_push_runs_validate(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "validate.sh" in content, "pre-push hook must invoke validate.sh"

    def test_pre_push_runs_pytest(self):
        content = self.PRE_PUSH.read_text(encoding="utf-8")
        assert "pytest" in content and "tests/" in content, (
            "pre-push hook must invoke pytest against the tests/ directory"
        )


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
