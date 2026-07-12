"""Tests for hooks/workflow_resume_hint.sh — SessionStart(startup|resume|compact) hook.

Each test invokes hooks/workflow_resume_hint.sh directly with a JSON payload on
stdin, mirroring how Claude Code calls the SessionStart hook on cold launch,
continuation, or auto-compaction. Exit 0 always (fail-open). Injection only when
a fresh, branch-matching v1 state file exists (or, for the standalone advisory,
when cwd is a linked worktree).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

HOOK = Path(__file__).parent.parent / "hooks" / "workflow_resume_hint.sh"
HOOKS_JSON = Path(__file__).parent.parent / "hooks" / "hooks.json"

_BRANCH = "feature/286-workflow-state-persistence"
_SAFE_BRANCH = _BRANCH.replace("/", "-")

VALID_STATE: dict = {
    "version": 1,
    "skill": "swe-workbench:workflow-development",
    "mode": "B",
    "phase": "3",
    "phase_label": "Verify",
    "completed_phases": ["1", "2"],
    "context": {
        "branch": _BRANCH,
        "worktree_root": None,
        "pr": None,
        "base": None,
        "head_sha": None,
        "decision": None,
        "notes": "initial checkpoint",
    },
    "updated_at": "2026-05-21T10:30:00Z",
}


@pytest.fixture(scope="module")
def hook_script():
    assert HOOK.exists(), f"missing {HOOK}"
    assert os.access(HOOK, os.X_OK), f"{HOOK} must be executable"
    return HOOK


@pytest.fixture
def git_repo(tmp_path):
    """Temp git repo on branch feature/286-workflow-state-persistence."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", _BRANCH],
        cwd=repo_dir, env=_CLEAN_ENV, check=True,
    )
    (repo_dir / "README").write_text("init")
    subprocess.run(["git", "add", "."], cwd=repo_dir, env=_CLEAN_ENV, check=True)
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null",
         "-c", "user.email=t@t.com", "-c", "user.name=T",
         "commit", "-qm", "init"],
        cwd=repo_dir, env=_CLEAN_ENV, check=True,
    )
    return repo_dir


def _state_path(repo_dir: Path, branch: str = _BRANCH) -> Path:
    safe = branch.replace("/", "-")
    return repo_dir / ".claude" / "cache" / "workflow-state" / f"{safe}.json"


def _write_state(repo_dir: Path, state: dict, branch: str = _BRANCH) -> Path:
    path = _state_path(repo_dir, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _run(script, cwd: str, source: str | None = None) -> subprocess.CompletedProcess:
    payload_dict = {"cwd": cwd}
    if source is not None:
        payload_dict["source"] = source
    payload = json.dumps(payload_dict)
    return subprocess.run(
        [str(script)],
        input=payload, text=True, capture_output=True,
        env=_CLEAN_ENV,
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

class TestHookWiring:
    """hooks.json has the right SessionStart entries; script exists and is executable."""

    def test_session_start_entry_present(self):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = data["hooks"].get("SessionStart", [])
        assert entries, "SessionStart event missing from hooks.json"

    @pytest.mark.parametrize("matcher", ["startup", "resume", "compact"])
    def test_matcher_present(self, matcher):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = data["hooks"].get("SessionStart", [])
        matched = [e for e in entries if e.get("matcher") == matcher]
        assert matched, f"No SessionStart entry with matcher='{matcher}' in hooks.json"

    @pytest.mark.parametrize("matcher", ["startup", "resume", "compact"])
    def test_hook_script_referenced(self, matcher):
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = data["hooks"].get("SessionStart", [])
        matched = [e for e in entries if e.get("matcher") == matcher]
        assert any(
            "workflow_resume_hint.sh" in hook["command"]
            for e in matched
            for hook in e.get("hooks", [])
        ), f"workflow_resume_hint.sh not referenced in SessionStart {matcher} entry"

    def test_hook_script_exists_and_executable(self):
        assert HOOK.exists(), f"Missing hook script: {HOOK}"
        assert os.access(HOOK, os.X_OK), f"Hook script not executable: {HOOK}"


# ---------------------------------------------------------------------------
# No-op cases — hook must emit nothing and exit 0
# ---------------------------------------------------------------------------

class TestNoOp:
    """Hook is silent when there is no state to resume."""

    def test_no_state_file_exits_clean(self, hook_script, git_repo):
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_stale_file_swept_and_no_injection(self, hook_script, git_repo):
        """State file >24h old is deleted; no preamble injected."""
        path = _write_state(git_repo, VALID_STATE)
        old_mtime = os.path.getmtime(path) - 1441 * 60
        os.utime(path, (old_mtime, old_mtime))

        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        assert result.stdout.strip() == ""
        assert not path.exists(), "Stale state file should be deleted"


# ---------------------------------------------------------------------------
# Fail-open cases — bad / mismatched state must not inject
# ---------------------------------------------------------------------------

class TestFailOpen:
    """Hook degrades to no-op rather than injecting a wrong resume."""

    def test_branch_mismatch_no_injection(self, hook_script, git_repo):
        state = {**VALID_STATE, "context": {**VALID_STATE["context"], "branch": "feature/other"}}
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_version_not_1_no_injection(self, hook_script, git_repo):
        state = {**VALID_STATE, "version": 2}
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_malformed_json_no_injection(self, hook_script, git_repo):
        path = _state_path(git_repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json }{", encoding="utf-8")
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_missing_version_field_no_injection(self, hook_script, git_repo):
        state = {k: v for k, v in VALID_STATE.items() if k != "version"}
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Resume injection — valid fresh branch-matching state must inject
# ---------------------------------------------------------------------------

class TestResumeInjection:
    """Hook injects a properly structured preamble for a valid state file."""

    def test_emits_hook_specific_output(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        assert result.stdout.strip(), "Expected non-empty stdout for valid state"
        data = json.loads(result.stdout)
        assert "hookSpecificOutput" in data

    def test_hook_event_name_is_session_start(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_additional_context_present(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        data = json.loads(result.stdout)
        assert "additionalContext" in data["hookSpecificOutput"]

    def test_preamble_contains_skill_name(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "swe-workbench:workflow-development" in ctx

    def test_preamble_contains_phase(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "3" in ctx

    def test_preamble_contains_phase_label(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "Verify" in ctx

    def test_preamble_contains_safety_gate(self, hook_script, git_repo):
        """Preamble must include the 'contradicts current repo reality' safety note."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "contradicts" in ctx or "reality" in ctx

    def test_preamble_contains_completed_phases(self, hook_script, git_repo):
        """Completed phases list must appear in the preamble (AC#2)."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "Completed phases" in ctx or "completed" in ctx.lower()
        # VALID_STATE.completed_phases = ["1", "2"]
        assert "1" in ctx and "2" in ctx

    def test_exit_0_on_valid_state(self, hook_script, git_repo):
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0

    def test_branch_with_percent_character(self, hook_script, tmp_path):
        """Branch names containing % must not corrupt the JSON envelope."""
        branch = "feature/100%-done"
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", branch],
            cwd=repo_dir, env=_CLEAN_ENV, check=True,
        )
        (repo_dir / "README").write_text("init")
        subprocess.run(["git", "add", "."], cwd=repo_dir, env=_CLEAN_ENV, check=True)
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null",
             "-c", "user.email=t@t.com", "-c", "user.name=T",
             "commit", "-qm", "init"],
            cwd=repo_dir, env=_CLEAN_ENV, check=True,
        )
        state = {**VALID_STATE, "context": {**VALID_STATE["context"], "branch": branch}}
        _write_state(repo_dir, state, branch)
        result = _run(hook_script, str(repo_dir))
        assert result.returncode == 0
        data = json.loads(result.stdout)  # must be valid JSON — raises if corrupted
        assert "hookSpecificOutput" in data


# ---------------------------------------------------------------------------
# worktree_root re-anchor nudge
# ---------------------------------------------------------------------------

class TestWorktreeRootReanchor:
    """Hook must emit a re-anchor nudge when worktree_root differs from live root.

    context.worktree_root records the worktree where the session was doing its
    work. If the session resumes from a different directory (live root ≠ recorded
    worktree_root), the hook appends an EnterWorktree(path=…) instruction so the
    executor moves into the correct worktree before resuming.
    """

    def test_reanchor_nudge_when_worktree_root_differs(self, hook_script, git_repo, tmp_path):
        """worktree_root ≠ live root → preamble contains EnterWorktree(path=…)."""
        # Use a path that exists but differs from git_repo (the live root).
        foreign_path = str(tmp_path / "some-other-worktree")
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": foreign_path},
        }
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        assert result.stdout.strip(), "Expected non-empty output for valid state"
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "EnterWorktree" in ctx, (
            "Preamble must contain 'EnterWorktree' when worktree_root differs from live root."
        )
        assert foreign_path in ctx, (
            "Preamble must include the recorded worktree_root path so the executor "
            "knows where to re-anchor."
        )

    def test_no_reanchor_nudge_when_worktree_root_matches_live_root(
        self, hook_script, git_repo
    ):
        """worktree_root == live root → no re-anchor line in the preamble."""
        # Set worktree_root to the same directory as git_repo (the live root).
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": str(git_repo)},
        }
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        # Re-anchor nudge must NOT appear when already in the right place.
        assert "WORKTREE RE-ANCHOR REQUIRED" not in ctx, (
            "Preamble must NOT emit a re-anchor nudge when worktree_root matches "
            "the live root — the session is already in the correct place."
        )

    def test_no_reanchor_nudge_when_worktree_root_absent(self, hook_script, git_repo):
        """worktree_root absent (null/empty) → no re-anchor nudge."""
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": None},
        }
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR REQUIRED" not in ctx, (
            "Preamble must not emit a re-anchor nudge when worktree_root is absent."
        )

    def test_no_reanchor_nudge_when_worktree_root_empty_string(
        self, hook_script, git_repo
    ):
        """worktree_root empty string → no re-anchor nudge."""
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": ""},
        }
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR REQUIRED" not in ctx, (
            "Preamble must not emit a re-anchor nudge when worktree_root is empty."
        )

    def test_no_reanchor_nudge_case_insensitive_same_path(self, hook_script, git_repo):
        """worktree_root same path, different casing → no re-anchor nudge (tr lowercasing guard).

        On macOS APFS (case-insensitive) os.path.realpath can return different-cased strings
        for the same directory, so the tr guard prevents a false positive there.  On Linux
        (case-sensitive) the mixed-case path is a different inode, so realpath returns the
        mixed-case string unchanged — but tr still equalises both strings to lowercase, which
        is what we are exercising here: the guard works on both platforms.
        """
        live_root = str(git_repo)
        # Flip the case of the last path component to simulate the APFS scenario on macOS
        # (where realpath may return different casing) and exercise the tr guard on Linux.
        parent, name = os.path.split(live_root)
        mixed_case_root = os.path.join(parent, name.upper() if name.islower() else name.lower())
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": mixed_case_root},
        }
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR REQUIRED" not in ctx, (
            "Preamble must NOT emit a re-anchor nudge when worktree_root is the same path "
            "as the live root with only casing differences (macOS APFS case-insensitive guard)."
        )

    def test_blank_line_after_reanchor_block(self, hook_script, git_repo, tmp_path):
        """Re-anchor block must be followed by a blank line before 'If the recorded state'."""
        foreign_path = str(tmp_path / "some-other-worktree")
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": foreign_path},
        }
        _write_state(git_repo, state)
        result = _run(hook_script, str(git_repo))

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR REQUIRED" in ctx
        # The re-anchor block must be separated from the next paragraph by a blank line.
        assert "do not cd-prefix.\n\nIf the recorded state" in ctx, (
            "Preamble must have a blank line between the re-anchor block and the "
            "'If the recorded state' safety gate."
        )


# ---------------------------------------------------------------------------
# Broadened prevention (#497): fire independent of the sidecar gate
# ---------------------------------------------------------------------------

class TestLinkedWorktreeReanchor:
    """EnterWorktree tracking can be dropped by compaction even when cwd never
    moved and there is no checkpoint to resume from. The hook must probe
    --git-dir vs --git-common-dir directly and nudge whenever cwd is a linked
    worktree — not only on a worktree_root path mismatch, and not only when a
    fresh sidecar exists.
    """

    @pytest.fixture
    def linked_worktree(self, tmp_path):
        """Main repo plus a linked worktree checked out on _BRANCH."""
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            cwd=main_dir, env=_CLEAN_ENV, check=True,
        )
        (main_dir / "README").write_text("init")
        subprocess.run(["git", "add", "."], cwd=main_dir, env=_CLEAN_ENV, check=True)
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null",
             "-c", "user.email=t@t.com", "-c", "user.name=T",
             "commit", "-qm", "init"],
            cwd=main_dir, env=_CLEAN_ENV, check=True,
        )
        wt_dir = tmp_path / "wt"
        subprocess.run(
            ["git", "worktree", "add", "-b", _BRANCH, str(wt_dir)],
            cwd=main_dir, env=_CLEAN_ENV, check=True,
        )
        return wt_dir

    def test_same_path_nudge_when_linked_worktree(self, hook_script, linked_worktree):
        """worktree_root == live root, cwd IS a linked worktree → nudge now fires.

        Previously silent: the old mismatch-only check saw worktree_root == root
        and skipped the nudge entirely, even though compaction can drop
        EnterWorktree tracking without moving cwd at all.
        """
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": str(linked_worktree)},
        }
        _write_state(linked_worktree, state)
        result = _run(hook_script, str(linked_worktree))

        assert result.returncode == 0
        assert result.stdout.strip(), "Expected non-empty output for a linked worktree"
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR" in ctx, (
            "Same-path resume inside a linked worktree must still get a defensive "
            "re-anchor nudge — compaction can drop EnterWorktree tracking even "
            "when cwd never moved."
        )
        assert "EnterWorktree" in ctx

    def test_standalone_nudge_when_no_sidecar(self, hook_script, linked_worktree):
        """No state file at all, cwd IS a linked worktree → standalone nudge emitted."""
        result = _run(hook_script, str(linked_worktree))

        assert result.returncode == 0
        assert result.stdout.strip(), (
            "Expected a standalone re-anchor nudge even with no workflow checkpoint"
        )
        data = json.loads(result.stdout)
        assert "hookSpecificOutput" in data
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR" in ctx
        assert "EnterWorktree" in ctx
        assert str(linked_worktree) in ctx

    def test_main_checkout_no_sidecar_stays_silent(self, hook_script, git_repo):
        """Regression: main checkout (not a linked worktree), no sidecar → still
        empty output, exit 0."""
        result = _run(hook_script, str(git_repo))
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_standalone_nudge_source_compact_wording(self, hook_script, linked_worktree):
        """No state file, cwd IS a linked worktree, source=compact → standalone
        nudge uses the compaction-specific advisory_lead wording."""
        result = _run(hook_script, str(linked_worktree), source="compact")

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "Compaction may have dropped EnterWorktree tracking" in ctx
        assert "not EnterWorktree-anchored" not in ctx

    def test_standalone_nudge_source_resume_wording(self, hook_script, linked_worktree):
        """No state file, cwd IS a linked worktree, source=resume → standalone
        nudge uses the resume-specific advisory_lead wording, not compaction's."""
        result = _run(hook_script, str(linked_worktree), source="resume")

        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "Resuming this session may have dropped EnterWorktree tracking" in ctx
        assert "Compaction may have dropped" not in ctx

    def test_standalone_nudge_when_sidecar_stale(self, hook_script, linked_worktree):
        """Stale (>24h) same-branch sidecar in a linked worktree → still nudge.

        A stale sidecar is "no usable checkpoint," the same situation as no
        sidecar at all — it must not silently swallow the linked-worktree signal.
        """
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "worktree_root": str(linked_worktree)},
        }
        path = _write_state(linked_worktree, state)
        old_mtime = os.path.getmtime(path) - 1441 * 60
        os.utime(path, (old_mtime, old_mtime))

        result = _run(hook_script, str(linked_worktree))

        assert result.returncode == 0
        assert not path.exists(), "Stale state file should still be deleted"
        assert result.stdout.strip(), "Expected a nudge despite the stale sidecar"
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR" in ctx

    def test_standalone_nudge_when_sidecar_wrong_version(self, hook_script, linked_worktree):
        """Sidecar with an unsupported schema version in a linked worktree → still nudge."""
        state = {
            **VALID_STATE,
            "version": 2,
            "context": {**VALID_STATE["context"], "worktree_root": str(linked_worktree)},
        }
        _write_state(linked_worktree, state)
        result = _run(hook_script, str(linked_worktree))

        assert result.returncode == 0
        assert result.stdout.strip(), "Expected a nudge despite the unsupported version"
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR" in ctx

    def test_standalone_nudge_when_sidecar_branch_mismatch(self, hook_script, linked_worktree):
        """Sidecar recorded for a different branch in a linked worktree → still nudge."""
        state = {
            **VALID_STATE,
            "context": {**VALID_STATE["context"], "branch": "feature/other", "worktree_root": str(linked_worktree)},
        }
        _write_state(linked_worktree, state)
        result = _run(hook_script, str(linked_worktree))

        assert result.returncode == 0
        assert result.stdout.strip(), "Expected a nudge despite the branch mismatch"
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR" in ctx

    def test_standalone_nudge_source_startup_no_dropped_claim(self, hook_script, linked_worktree):
        """source=startup, no sidecar, linked worktree → standalone nudge fires but
        must not claim tracking was 'dropped' or that the session was 'compacted' —
        a fresh cold-launch process never had a prior EnterWorktree session to lose."""
        result = _run(hook_script, str(linked_worktree), source="startup")

        assert result.returncode == 0
        assert result.stdout.strip(), "Expected a standalone nudge on cold startup"
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "WORKTREE RE-ANCHOR" in ctx
        assert "dropped" not in ctx.lower()
        assert "compacted" not in ctx.lower()
        assert "not EnterWorktree-anchored" in ctx


# ---------------------------------------------------------------------------
# Source-aware framing (#524): startup/resume never falsely claim compaction
# ---------------------------------------------------------------------------

class TestSourceAwareFraming:
    """The full resume preamble's wording is conditioned on SessionStart's
    `.source` field so a non-compaction resume never claims 'this session was
    compacted'."""

    def test_source_compact_wording_unchanged(self, hook_script, git_repo):
        """source=compact must preserve the original compaction wording exactly."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo), source="compact")
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[Workflow auto-resume after compaction]" in ctx
        assert "This session was compacted." in ctx

    def test_source_resume_wording(self, hook_script, git_repo):
        """source=resume (--continue/--resume) must say 'resumed/continued', never
        claim compaction happened."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo), source="resume")
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[Workflow auto-resume after continuation]" in ctx
        assert "This session was resumed/continued." in ctx
        assert "compacted" not in ctx.lower()

    def test_source_startup_wording(self, hook_script, git_repo):
        """source=startup (cold launch) must not claim compaction or a dropped
        session — there was no prior session to drop. `git_repo` is a plain
        checkout, not a linked worktree, so the intro must not assert
        worktree-specific facts either (that claim belongs to the separately
        is_linked_worktree-gated reanchor_line/format_advisory, not the intro)."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo), source="startup")
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[Workflow auto-resume on startup]" in ctx
        assert "This is a fresh session start." in ctx
        assert "compacted" not in ctx.lower()
        assert "linked worktree" not in ctx.lower()

    def test_absent_source_neutral_wording(self, hook_script, git_repo):
        """No `.source` field at all (older harness payload) must default to
        neutral wording, never asserting compaction happened."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo))
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[Workflow auto-resume]" in ctx
        assert "This session resumed." in ctx
        assert "compacted" not in ctx.lower()

    def test_unknown_source_value_falls_back_to_neutral(self, hook_script, git_repo):
        """An unrecognized `.source` value must degrade to the neutral framing
        rather than crashing or leaking the raw value into the preamble."""
        _write_state(git_repo, VALID_STATE)
        result = _run(hook_script, str(git_repo), source="some-future-source")
        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[Workflow auto-resume]" in ctx
        assert "This session resumed." in ctx
        assert "compacted" not in ctx.lower()

    def test_non_scalar_source_falls_back_to_neutral(self, hook_script, git_repo):
        """A `.source` that is a JSON object/array (malformed payload) must still
        degrade to neutral wording, not crash or leak raw JSON into the preamble."""
        _write_state(git_repo, VALID_STATE)
        payload = json.dumps({"cwd": str(git_repo), "source": {"a": 1}})
        result = subprocess.run(
            [str(hook_script)], input=payload, text=True, capture_output=True, env=_CLEAN_ENV,
        )
        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "[Workflow auto-resume]" in ctx
        assert "This session resumed." in ctx
        assert "compacted" not in ctx.lower()
        assert '{"a"' not in ctx
