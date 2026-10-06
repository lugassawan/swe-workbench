"""Tests for the /swe-workbench:design --pr flag and the workflow-redesign skill."""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import validate

ROOT = Path(__file__).parent.parent
DESIGN_CMD = ROOT / "commands" / "design.md"
SKILL_DIR = ROOT / "skills" / "workflow-redesign"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS_TXT = SKILL_DIR / "triggers.txt"
SUPERSEDE_MD = SKILL_DIR / "reference" / "supersede-pr.md"
FETCH_MD = SKILL_DIR / "reference" / "pr-context-fetch.md"
WORKFLOWS_MD = ROOT / "shared" / "agents" / "workflows.md"
CATALOG_MD = ROOT / "docs" / "catalog.md"

ORCHESTRATOR_CAP = 300
ASK_USER_QUESTION_MAX_OPTIONS = 4


def _skill_text() -> str:
    return SKILL_MD.read_text()


def _skill_bundle() -> str:
    """SKILL.md plus its reference/ companions — the full text of the flow."""
    parts = [_skill_text()]
    parts += [p.read_text() for p in sorted((SKILL_DIR / "reference").glob("*.md"))]
    return "\n".join(parts)


def _before(text: str, first: str, second: str) -> bool:
    a, b = text.find(first), text.find(second)
    assert a != -1, f"{first!r} not found"
    assert b != -1, f"{second!r} not found"
    return a < b


def _bash_block(text: str, marker: str) -> str:
    """Return the first fenced bash block that contains `marker`."""
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        if marker in block:
            return block
    raise AssertionError(f"no bash block containing {marker!r}")


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


# ── command ──────────────────────────────────────────────────


def test_argument_hint_documents_pr_and_new_pr():
    fm = validate.parse_frontmatter(DESIGN_CMD, text=DESIGN_CMD.read_text())
    assert fm is not None
    hint = fm["argument-hint"]
    assert "--pr" in hint and "--new-pr" in hint, hint


def test_design_command_dispatches_to_workflow_redesign():
    assert "swe-workbench:workflow-redesign" in DESIGN_CMD.read_text()


def test_pr_paragraph_precedes_the_unconditional_senior_engineer_delegation():
    text = DESIGN_CMD.read_text()
    assert _before(text, "**PR redesign (`--pr`).**", "Otherwise, delegate to the")
    assert "`--new-pr` requires `--pr`" in text
    assert "^#?[0-9]+$" in text


# ── skill structure ──────────────────────────────────────────


def test_skill_frontmatter_and_line_cap():
    text = _skill_text()
    fm = validate.parse_frontmatter(SKILL_MD, text=text)
    assert fm is not None
    assert fm.get("name") == "workflow-redesign"
    assert fm.get("orchestrator", "").lower() == "true"
    assert len(text.splitlines()) <= ORCHESTRATOR_CAP


def test_skill_has_triggers():
    lines = [
        ln.strip()
        for ln in TRIGGERS_TXT.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 2
    assert all(len(ln) <= 200 for ln in lines)


def test_catalog_and_workflows_entries_exist():
    assert "`swe-workbench:workflow-redesign`" in WORKFLOWS_MD.read_text()
    catalog = CATALOG_MD.read_text()
    assert "`swe-workbench:workflow-redesign`" in catalog
    design_row = next(
        ln for ln in catalog.splitlines() if "`/swe-workbench:design <question>`" in ln
    )
    assert "--pr" in design_row and "--new-pr" in design_row


def test_every_flow_variable_is_bound():
    """Variables the snippets rely on must be assigned somewhere in the flow."""
    text = _skill_bundle()
    for var in (
        "PR",
        "PR_BRANCH",
        "BASE_BRANCH",
        "PR_URL",
        "RUN_DIR",
        "WT",
        "CREATED_WT",
        "NEW_BRANCH",
        "FIX_SHA",
    ):
        assert re.search(rf"^\s*{var}=", text, re.MULTILINE) or f"`{var}=" in text, (
            f"{var} is used but never assigned"
        )
    assert "DELIVERED=false" in text and "DELIVERED=true" in text


def test_preflight_covers_every_command_the_flow_calls():
    text = _skill_text()
    for cmd in (
        "gh",
        "jq",
        "swe-workbench-new-run-dir",
        "swe-workbench-reap-run-dir",
        "swe-workbench-address-feedback-worktree",
        "swe-workbench-sync-pr-metadata",
        "swe-workbench-pr-title-drift",
        "swe-workbench-result-check",
    ):
        assert f"command -v {cmd} >/dev/null 2>&1" in text, cmd


def test_gh_pr_diff_is_not_called_with_nonexistent_stat_flag():
    assert not re.search(r"gh pr diff[^\n]*--stat", _skill_bundle())


# ── safety gates ─────────────────────────────────────────────


@pytest.fixture
def gate_env(tmp_path):
    """Run the real ownership-gate snippet with `gh` stubbed on PATH."""
    gate = _bash_block(FETCH_MD.read_text(), "gh api /user")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "gh",
        'case "$1" in\n'
        '  auth) exit "${GH_AUTH_RC:-0}" ;;\n'
        '  api) [ "${GH_USER_RC:-0}" -eq 0 ] || exit "$GH_USER_RC"; printf "%s\\n" "$GH_USER" ;;\n'
        "esac\n",
    )

    def run(*, author_json, **env):
        full = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "PR": "7",
            "PR_JSON": author_json,
            **env,
        }
        return subprocess.run(
            ["bash", "-c", gate], env=full, capture_output=True, text=True
        )

    return run


MINE = '{"author":{"login":"me"}}'


def test_ownership_gate_allows_the_author(gate_env):
    assert gate_env(author_json=MINE, GH_USER="me").returncode == 0


@pytest.mark.parametrize(
    "case",
    [
        {"author_json": MINE, "GH_USER": "someone-else"},
        {"author_json": MINE, "GH_USER": "me", "GH_AUTH_RC": "1"},
        {"author_json": MINE, "GH_USER": "me", "GH_USER_RC": "1"},
        {"author_json": MINE, "GH_USER": ""},
        {"author_json": '{"author":null}', "GH_USER": "me"},
        {"author_json": '{"author":{"login":null}}', "GH_USER": "null"},
    ],
    ids=[
        "mismatch",
        "auth-fails",
        "user-lookup-fails",
        "empty-user",
        "null-author",
        "null-login",
    ],
)
def test_ownership_gate_fails_closed(gate_env, case):
    result = gate_env(**case)
    assert result.returncode != 0, result.stdout + result.stderr


def test_open_check_and_fork_refusal_present():
    text = _skill_bundle()
    assert "`OPEN`" in text
    assert "isCrossRepository" in text
    assert "Fork PRs are not supported" in text
    assert "must be digits" in text  # URLs / branch names are refused


def test_ownership_gate_runs_before_senior_engineer_dispatch():
    text = _skill_text()
    assert _before(text, "Run Part 1 of", "Dispatch `swe-workbench:senior-engineer`")
    assert _before(
        text,
        "fails closed on any `gh` error",
        "Dispatch `swe-workbench:senior-engineer`",
    )


def test_gates_come_before_worktree_acquire():
    text = _skill_text()
    acquire = text.index("swe-workbench-address-feedback-worktree acquire")
    for gate in ("**Gate 1.**", "**Gate 2.**"):
        assert text.index(gate) < acquire, f"{gate} must precede worktree acquire"
    assert _before(text, "**Gate 1.**", "**Gate 2.**")
    gate2 = text.split("**Gate 2.**")[1].split("## Phase 3")[0]
    assert "ExitPlanMode" in gate2
    # Fallback keeps the gate hard when ExitPlanMode is unavailable.
    assert "unavailable or errors" in gate2 and "fail closed" in gate2


def test_gate1_fits_ask_user_question_option_cap():
    gate1 = _skill_text().split("**Gate 1.**")[1].split("## Phase 2")[0]
    assert "**Keep current approach**" in gate1
    assert "at most 3" in gate1
    max_alternatives = 3
    assert max_alternatives + 1 <= ASK_USER_QUESTION_MAX_OPTIONS
    assert "No worktree is created, nothing is edited" in gate1


def test_plan_overrides_embedded_branch_and_deliver_phases():
    plan = _skill_text().split("## Phase 2")[1].split("## Phase 3")[0]
    assert "never `gh pr create`" in plan
    assert "distinct from `$PR_BRANCH`" in plan


# ── no force-push, no branch deletion ────────────────────────


def test_no_force_push_or_branch_delete_in_commands():
    text = _skill_bundle()
    pushes = [ln for ln in text.splitlines() if re.search(r"\bgit\b.*\bpush\b", ln)]
    assert pushes, "expected at least one git push line"
    for ln in pushes:
        assert not re.search(r"--force|--force-with-lease|\s-f\b|\s\+\S", ln), ln
    assert "--delete-branch" not in text


# ── --new-pr isolation and supersede ordering ────────────────


def test_new_pr_branch_must_differ_from_old_and_base_branch():
    text = _skill_text()
    check = _bash_block(text, "NEW_BRANCH=")
    assert '"$NEW_BRANCH" != "$PR_BRANCH"' in check
    assert '"$NEW_BRANCH" != "$BASE_BRANCH"' in check
    assert "do not resume an existing worktree or promote existing work" in text
    assert text.count("NEW_BRANCH") >= 4  # defined, checked, re-checked before push


def test_new_pr_creation_goes_through_commit_and_pr_and_carries_trailer():
    text = SUPERSEDE_MD.read_text()
    assert "swe-workbench:workflow-commit-and-pr" in text
    assert "closingIssuesReferences" in text
    assert "gh pr create" not in text


def test_supersede_close_comes_after_new_pr_verification():
    text = SUPERSEDE_MD.read_text()
    assert _before(
        text, "gh pr view <new> --json state,url,body", "gh pr close N --comment"
    )
    assert _before(text, "Reply `yes`", "gh pr close N --comment")
    assert "Supersedes #N" in text
    assert "^Supersedes #N( |$)" in text  # `#12` must not match `#123`


# ── cleanup guard (executed, not just grepped) ───────────────


@pytest.fixture
def cleanup_env(tmp_path):
    """Run the real Phase 6 snippet with git and the worktree helper stubbed."""
    block = _bash_block(
        _skill_text(), "swe-workbench-address-feedback-worktree release"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    _stub(
        bin_dir,
        "git",
        '[ "${GIT_STATUS_RC:-0}" -eq 0 ] || exit "$GIT_STATUS_RC"\nprintf "%s" "$GIT_STATUS_OUT"\n',
    )
    _stub(
        bin_dir,
        "swe-workbench-address-feedback-worktree",
        f'echo "$@" >> "{calls}"\n'
        'echo \'{"schema":"swb.address-feedback-worktree-release/1","status":"ok","data":{"removed":true}}\'\n',
    )
    _stub(bin_dir, "swe-workbench-result-check", "cat\n")

    def run(**env):
        full = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "PR": "7",
            "PR_BRANCH": "feature/x",
            "WT": str(tmp_path / "wt"),
            "CREATED_WT": "true",
            **env,
        }
        result = subprocess.run(
            ["bash", "-c", block], env=full, capture_output=True, text=True
        )
        released = calls.exists() and calls.read_text().strip() != ""
        return result, released

    return run


def test_release_runs_only_when_delivered_and_clean(cleanup_env):
    result, released = cleanup_env(DELIVERED="true", GIT_STATUS_OUT="")
    assert result.returncode == 0 and released


@pytest.mark.parametrize(
    "env",
    [
        {"DELIVERED": "false", "GIT_STATUS_OUT": ""},
        {"DELIVERED": "true", "GIT_STATUS_OUT": " M file.py\n"},
        {"DELIVERED": "true", "GIT_STATUS_OUT": "", "GIT_STATUS_RC": "128"},
    ],
    ids=["not-delivered", "dirty-tree", "git-status-fails"],
)
def test_release_is_skipped_when_unsafe(cleanup_env, env):
    result, released = cleanup_env(**env)
    assert not released, result.stdout + result.stderr
    assert "Worktree kept at" in result.stdout


# ── metadata sync ────────────────────────────────────────────


def test_skill_references_sync_pr_metadata():
    text = _skill_text()
    assert "skills/workflow-address-feedback/reference/sync-pr-metadata.md" in text
    assert (
        ROOT
        / "skills"
        / "workflow-address-feedback"
        / "reference"
        / "sync-pr-metadata.md"
    ).exists()
    assert "swe-workbench-sync-pr-metadata" in text


def test_skill_uses_update_existing_pr_path():
    text = _skill_text()
    assert "Update existing PR" in text
    assert "skip-phase-1" in text
