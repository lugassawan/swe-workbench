"""Existence, executability, and skill-reference checks for runtime/ scripts."""

import os
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
RUNTIME = ROOT / "runtime"

RUNTIME_SCRIPTS = [
    "clean-ephemeral.sh",
    "clean-state-files.sh",
    "doctor.sh",
    "fetch-pr.sh",
    "reply-and-resolve.sh",
]


def test_all_runtime_scripts_exist_and_executable():
    """Every script in RUNTIME_SCRIPTS must exist under runtime/ and be executable."""
    for name in RUNTIME_SCRIPTS:
        path = RUNTIME / name
        assert path.exists(), f"runtime/{name} must exist"
        assert os.access(path, os.X_OK), f"runtime/{name} must be executable (chmod +x)"


def test_all_runtime_sh_files_are_tracked():
    """Every *.sh in runtime/ must be listed in RUNTIME_SCRIPTS (prevents silent coverage gaps)."""
    on_disk = {p.name for p in RUNTIME.glob("*.sh")}
    tracked = set(RUNTIME_SCRIPTS)
    missing = on_disk - tracked
    assert not missing, (
        f"runtime/ contains untracked scripts not in RUNTIME_SCRIPTS: {sorted(missing)}. "
        "Add them to RUNTIME_SCRIPTS so they get existence, executable, and syntax checks."
    )


def test_runtime_scripts_pass_bash_syntax_check():
    """bash -n must pass for every runtime script (no syntax errors)."""
    for name in RUNTIME_SCRIPTS:
        path = RUNTIME / name
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True, text=True,
            env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 0, (
            f"bash -n {name} failed:\n{result.stderr}"
        )


def test_fetch_pr_referenced_in_pr_review_skill():
    """workflow-pr-review SKILL.md must invoke runtime/fetch-pr.sh in Step 1."""
    text = (ROOT / "skills" / "workflow-pr-review" / "SKILL.md").read_text()
    assert "runtime/fetch-pr.sh" in text, (
        "workflow-pr-review SKILL.md Step 1 must invoke runtime/fetch-pr.sh"
    )


def test_fetch_pr_referenced_in_pr_review_followup_skill():
    """workflow-pr-review-followup SKILL.md must invoke runtime/fetch-pr.sh in Step 1."""
    text = (ROOT / "skills" / "workflow-pr-review-followup" / "SKILL.md").read_text()
    assert "runtime/fetch-pr.sh" in text, (
        "workflow-pr-review-followup SKILL.md Step 1 must invoke runtime/fetch-pr.sh"
    )


def test_fetch_pr_referenced_in_address_feedback_skill():
    """workflow-address-feedback SKILL.md must invoke runtime/fetch-pr.sh in Phase 1."""
    text = (ROOT / "skills" / "workflow-address-feedback" / "SKILL.md").read_text()
    assert "runtime/fetch-pr.sh" in text, (
        "workflow-address-feedback SKILL.md Phase 1 must invoke runtime/fetch-pr.sh"
    )


def test_reply_and_resolve_referenced_in_address_feedback_skill():
    """workflow-address-feedback SKILL.md must invoke runtime/reply-and-resolve.sh in Phase 5."""
    text = (ROOT / "skills" / "workflow-address-feedback" / "SKILL.md").read_text()
    assert "runtime/reply-and-resolve.sh" in text, (
        "workflow-address-feedback SKILL.md Phase 5 must invoke runtime/reply-and-resolve.sh"
    )
