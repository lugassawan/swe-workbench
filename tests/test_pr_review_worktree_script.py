"""Tests for bin/swe-workbench-pr-review-worktree.

Single source of the ephemeral PR-review worktree naming/lifecycle contract shared by
workflow-pr-review (first-pass + followup) and the PR-mode specialist sub-flow in
commands/review.md. Three subcommands: `acquire`, `release`, `names`.

Mirrors tests/test_sweep_residuals.py's harness conventions (_build_repo, _unique_n,
_rimba_absent_env, try/finally worktree cleanup, real git — no mocking of git itself).
The rimba-present path is exercised via a PATH-scoped fake `rimba` binary
(_write_rimba_stub), modeled on tests/test_pr_review_submit_script.py's _write_gh_stub,
so CI never depends on a real rimba install. Unlike the gh stub (a canned-response
responder), the rimba stub is stateful — it performs real `git worktree add/remove`
calls against the same repo under test, because swe-workbench-pr-review-worktree
resolves the worktree's absolute path by cross-referencing `rimba list --json` against
real `git worktree list --porcelain` output, not by trusting anything the stub merely
claims.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-pr-review-worktree"
SWEEP_RESIDUALS = ROOT / "bin" / "swe-workbench-sweep-residuals"

SPECIALIST_MODES = ["security", "accessibility", "dependency", "performance", "tests", "ux"]
ALL_MODES = ["first-pass", "followup", *SPECIALIST_MODES]


def _unique_n() -> str:
    """A large, effectively-unique PR number so /tmp fixtures never collide."""
    return str(20_000_000 + int.from_bytes(os.urandom(3), "big"))


def _run(*args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True, env=_CLEAN_ENV,
    )


def _build_repo(base: Path) -> Path:
    """A minimal git repo with one commit and no remote (names/arg-validation tests)."""
    repo = base / "main_repo"
    _run("git", "init", "-b", "main", str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _run("git", "add", "README.md", cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    return repo


def _build_repo_with_pr_ref(base: Path, pr_num: str) -> Path:
    """A repo with an 'origin' remote carrying refs/pull/<pr_num>/head (simulates a
    GitHub PR) so the git-fallback acquire path's
    `git fetch origin pull/<N>/head:<branch>` call has something real to fetch."""
    origin = base / "origin_src"
    _run("git", "init", "-b", "main", str(origin), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=origin)
    _run("git", "config", "user.name", "Test", cwd=origin)
    no_hooks = base / ".nohooks"
    no_hooks.mkdir(exist_ok=True)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=origin)
    (origin / "README.md").write_text("hello\n")
    _run("git", "add", "README.md", cwd=origin)
    _run("git", "commit", "-m", "init", cwd=origin)

    repo = base / "main_repo"
    _run("git", "clone", "-q", str(origin), str(repo), cwd=base)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test", cwd=repo)
    _run("git", "config", "core.hooksPath", str(no_hooks), cwd=repo)
    branch = f"pr-src-{pr_num}"
    _run("git", "checkout", "-b", branch, cwd=repo)
    (repo / f"pr_file_{pr_num}.txt").write_text("pr content\n")
    _run("git", "add", f"pr_file_{pr_num}.txt", cwd=repo)
    _run("git", "commit", "-m", "pr commit", cwd=repo)
    _run("git", "push", "-q", "origin", f"{branch}:refs/pull/{pr_num}/head", cwd=repo)
    _run("git", "checkout", "-q", "main", cwd=repo)
    _run("git", "branch", "-D", branch, cwd=repo)
    return repo


def _rimba_absent_env(fake_home: Path) -> dict:
    """Environment in which resolve-rimba.sh resolves to nothing — see
    tests/test_sweep_residuals.py's identical fixture for the rationale."""
    git_path = shutil.which("git")
    assert git_path, "git must be resolvable to build/run test fixtures"
    git_dir = os.path.dirname(git_path)
    env = dict(_CLEAN_ENV)
    env["PATH"] = ":".join([git_dir, "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    env["HOME"] = str(fake_home)
    return env


RIMBA_STUB_BODY = '''#!/usr/bin/env python3
"""Minimal stateful rimba emulator for tests. Supports exactly the subcommands
swe-workbench-pr-review-worktree needs: add pr:<n> --task <label> --skip-deps
--skip-hooks, list --json, remove <label> --force. Performs real `git worktree`
operations against $RIMBA_STUB_MAIN_REPO so the script under test's own
`git worktree list --porcelain` calls see genuine state, not a fabrication.

Known fidelity gap: the real `rimba add pr:<N>` resolves the PR head via `gh pr
view` and fetches by branch name, not by reading refs/pull/<N>/head directly (as
this stub does). This stub proves swe-workbench-pr-review-worktree's own logic
(rimba list --json .task cross-referenced against git worktree list --porcelain,
self-heal, removal) is correct regardless of how rimba itself resolves a PR --
it does not prove rimba's gh-based resolution step integrates correctly, since
that step is entirely rimba's own internal responsibility, not this script's."""
import json
import os
import subprocess
import sys

MAIN_REPO = os.environ["RIMBA_STUB_MAIN_REPO"]
WT_ROOT = os.environ["RIMBA_STUB_WORKTREES_DIR"]
os.makedirs(WT_ROOT, exist_ok=True)


def git(args):
    return subprocess.run(["git", "-C", MAIN_REPO, *args], capture_output=True, text=True)


argv = sys.argv[1:]
if not argv:
    sys.exit(1)
cmd = argv[0]

if cmd == "add":
    rest = argv[1:]
    task = None
    pr_num = None
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--task":
            task = rest[i + 1]
            i += 2
        elif a in ("--skip-deps", "--skip-hooks"):
            i += 1
        elif a.startswith("pr:"):
            pr_num = a[len("pr:"):]
            i += 1
        else:
            i += 1
    if not task:
        print("rimba-stub: --task required in pr: mode", file=sys.stderr)
        sys.exit(1)
    wt = os.path.join(WT_ROOT, task)
    if os.path.isdir(wt):
        print(f"rimba-stub: worktree already exists: {task}", file=sys.stderr)
        sys.exit(1)
    r = git(["fetch", "origin", f"pull/{pr_num}/head:{task}", "--force"])
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(1)
    r = git(["worktree", "add", wt, task])
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(1)
    print(f'Created worktree for task "{task}"')
    print(f"  Path:   {wt}")
    sys.exit(0)

elif cmd == "list":
    r = git(["worktree", "list", "--porcelain"])
    entries = []
    cur = {}
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            cur["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    if cur:
        entries.append(cur)
    data = []
    for e in entries:
        path = e["path"]
        base = os.path.basename(path)
        if os.path.abspath(os.path.dirname(path)) == os.path.abspath(WT_ROOT):
            data.append({
                "task": base, "type": "", "branch": e.get("branch", base),
                "path": path, "is_current": False, "status": {},
            })
    print(json.dumps({"version": "stub", "command": "list", "data": data}))
    sys.exit(0)

elif cmd == "remove":
    rest = [a for a in argv[1:] if not a.startswith("-")]
    if not rest:
        print("rimba-stub: remove requires <task>", file=sys.stderr)
        sys.exit(1)
    task = rest[0]
    wt = os.path.join(WT_ROOT, task)
    r1 = git(["worktree", "remove", "--force", wt])
    r2 = git(["branch", "-D", task])
    if r1.returncode != 0 and os.path.isdir(wt):
        sys.stderr.write(r1.stderr)
        sys.exit(1)
    sys.exit(0)

elif cmd == "version":
    print("rimba-stub 0.0.0")
    sys.exit(0)

else:
    print(f"rimba-stub: unsupported subcommand: {cmd}", file=sys.stderr)
    sys.exit(1)
'''


def _write_rimba_stub(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "rimba_stub_bin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "rimba"
    stub.write_text(RIMBA_STUB_BODY)
    stub.chmod(0o755)
    return stub_dir


def _rimba_present_env(fake_home: Path, stub_dir: Path, main_repo: Path, wt_root: Path) -> dict:
    git_path = shutil.which("git")
    python_path = shutil.which("python3") or sys.executable
    assert git_path, "git must be resolvable to build/run test fixtures"
    assert python_path, "python3 must be resolvable to run the rimba stub"
    env = dict(_CLEAN_ENV)
    env["PATH"] = ":".join([
        str(stub_dir), os.path.dirname(git_path), os.path.dirname(python_path),
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ])
    env["HOME"] = str(fake_home)
    env["RIMBA_STUB_MAIN_REPO"] = str(main_repo)
    env["RIMBA_STUB_WORKTREES_DIR"] = str(wt_root)
    return env


def _run_script(repo: Path, args: list, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=str(repo), capture_output=True, text=True, env=env,
    )


def _kv(result: subprocess.CompletedProcess) -> dict:
    """Parse a Tier Q `KEY=%q-quoted-value` stdout into a plain dict via a throwaway
    eval in a fresh bash subprocess (never eval'd in the test's own process)."""
    script = result.stdout + '\nfor v in ' + " ".join(
        re.findall(r"^([A-Z_]+)=", result.stdout, re.MULTILINE)
    ) + '; do printf "%s\\x1f%s\\x1e" "$v" "${!v}"; done\n'
    parsed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert parsed.returncode == 0, f"eval of KEY=VALUE output failed: {parsed.stderr}\nstdout was: {result.stdout!r}"
    out = {}
    for chunk in parsed.stdout.split("\x1e"):
        if not chunk:
            continue
        k, _, v = chunk.partition("\x1f")
        out[k] = v
    return out


def _cleanup_worktree(repo: Path, wt_path: Path, branch: str | None) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)],
                    cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV)
    if branch:
        subprocess.run(["git", "branch", "-D", branch],
                        cwd=str(repo), capture_output=True, text=True, env=_CLEAN_ENV)
    shutil.rmtree(wt_path, ignore_errors=True)


# ── existence / syntax ───────────────────────────────────────────────────────


def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable (chmod +x)"


def test_bash_syntax_check():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, env=_CLEAN_ENV)
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"


# ── names ─────────────────────────────────────────────────────────────────────


def test_names_requires_pr_arg():
    result = subprocess.run(["bash", str(SCRIPT), "names"], capture_output=True, text=True, env=dict(_CLEAN_ENV))
    assert result.returncode != 0


@pytest.mark.parametrize("bad_pr", ["", "abc", "-5", "12.3"])
def test_names_rejects_non_integer_pr(bad_pr):
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", bad_pr],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_names_covers_all_eight_modes_with_expected_shape():
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n], capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert {item["mode"] for item in data} == set(ALL_MODES)
    assert len(data) == len(ALL_MODES)
    for item in data:
        assert set(item) == {"mode", "label", "fallback_path", "legacy_fallback_path", "delete_branch"}
        assert item["delete_branch"] is True
        assert n in item["label"]
        assert n in item["fallback_path"]
        assert n in item["legacy_fallback_path"]


def test_names_first_pass_and_followup_labels():
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n, "--repo", "octocat/widgets"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    data = {item["mode"]: item for item in json.loads(result.stdout)}
    assert data["first-pass"]["label"] == f"pr-review-{n}"
    assert data["first-pass"]["fallback_path"] == f"/tmp/swe-workbench-pr-review/octocat-widgets-{n}"
    assert data["first-pass"]["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/{n}"
    assert data["followup"]["label"] == f"pr-followup-{n}"
    assert data["followup"]["fallback_path"] == f"/tmp/swe-workbench-pr-review/octocat-widgets-{n}-followup"
    assert data["followup"]["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/{n}-followup"


@pytest.mark.parametrize("mode", SPECIALIST_MODES)
def test_names_specialist_labels(mode):
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n, "--repo", "octocat/widgets"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    data = {item["mode"]: item for item in json.loads(result.stdout)}
    assert data[mode]["label"] == f"review-{mode}-{n}"
    assert data[mode]["fallback_path"] == f"/tmp/swe-workbench-pr-review/octocat-widgets-{mode}-{n}"
    assert data[mode]["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/{mode}-{n}"


def _sweep_residuals_worktree_contract(n: str) -> set:
    """Ground truth extracted from swe-workbench-sweep-residuals' own hardcoded
    WT_LABELS/WT_FALLBACKS/WT_DELETE_BRANCH arrays -- the backstop this ratchet
    guards against silently drifting away from."""
    text = SWEEP_RESIDUALS.read_text()

    specialist_match = re.search(r"SPECIALIST_MODES=\(([^)]*)\)", text)
    assert specialist_match, "SPECIALIST_MODES=(...) not found in sweep-residuals"
    specialist_modes = specialist_match.group(1).split()

    labels_match = re.search(r"WT_LABELS=\(([^)]*)\)", text)
    fallbacks_match = re.search(r"WT_FALLBACKS=\(([^)]*)\)", text)
    delete_match = re.search(r"WT_DELETE_BRANCH=\(([^)]*)\)", text)
    assert labels_match and fallbacks_match and delete_match, "WT_* arrays not found in sweep-residuals"

    labels = [s.replace("$N", n) for s in re.findall(r'"([^"]*)"', labels_match.group(1))]
    fallbacks = [s.replace("$N", n) for s in re.findall(r'"([^"]*)"', fallbacks_match.group(1))]
    delete_branch = re.findall(r"\d+", delete_match.group(1))
    assert len(labels) == len(fallbacks) == len(delete_branch)

    for mode in specialist_modes:
        labels.append(f"review-{mode}-{n}")
        fallbacks.append(f"/tmp/swe-workbench-pr-review/{mode}-{n}")
        delete_branch.append("1")

    return {(l, f, d) for l, f, d in zip(labels, fallbacks, delete_branch)}


def test_names_matches_sweep_residuals_worktree_contract():
    """Golden-ratchet, not a runtime dependency (see the script's own header comment
    for why sweep-residuals must never shell out to this command at runtime). The
    `names` output, unioned with one explicit address-feedback-<N> row (owned by
    workflow-address-feedback's own worktree lifecycle, not this command -- its
    worktree has the opposite branch-deletion invariant), must equal sweep-residuals' own
    hardcoded triples for the same PR number. The union is asserted explicitly here,
    not silently -- deleting this line would not make the test pass."""
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n], capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, result.stderr
    names_data = json.loads(result.stdout)
    # The ratchet compares the LEGACY triple until sweep-residuals grows its own
    # scoped+legacy pair (issue #713) — legacy_fallback_path is the stable join
    # key between the two contracts.
    names_triples = {
        (item["label"], item["legacy_fallback_path"], "1" if item["delete_branch"] else "0")
        for item in names_data
    }
    names_triples.add((f"address-feedback-{n}", "", "0"))

    expected = _sweep_residuals_worktree_contract(n)
    assert names_triples == expected


# ── acquire / release argument validation ────────────────────────────────────


def test_acquire_rejects_unrecognized_mode(tmp_path):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    result = _run_script(repo, ["acquire", "--mode", "bogus", "--pr", _unique_n()], env)
    assert result.returncode != 0
    assert result.stdout == ""


def test_acquire_requires_both_flags(tmp_path):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    result = _run_script(repo, ["acquire", "--mode", "first-pass"], env)
    assert result.returncode != 0


def test_release_rejects_missing_intent(tmp_path):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    result = _run_script(repo, ["release", "--mode", "first-pass", "--pr", _unique_n()], env)
    assert result.returncode != 0
    assert result.stdout == ""


def test_release_rejects_unrecognized_intent(tmp_path):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    result = _run_script(
        repo, ["release", "--mode", "first-pass", "--pr", _unique_n(), "--intent", "bogus"], env,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_release_rejects_unrecognized_mode(tmp_path):
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    result = _run_script(
        repo, ["release", "--mode", "bogus", "--pr", _unique_n(), "--intent", "completed"], env,
    )
    assert result.returncode != 0


def test_release_no_worktree_found_is_not_an_error(tmp_path):
    """Releasing a (mode, pr) that was never acquired must not crash the caller's
    cleanup chain -- exits 0 and reports honestly, mirroring sweep-residuals'
    own philosophy of never aborting a cleanup step over 'nothing to do'."""
    repo = _build_repo(tmp_path)
    env = _rimba_absent_env(tmp_path / "fake_home")
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    result = _run_script(
        repo, ["release", "--mode", "first-pass", "--pr", _unique_n(), "--intent", "completed"], env,
    )
    assert result.returncode == 0, result.stderr
    kv = _kv(result)
    assert kv["WORKTREE_REMOVED"] == "0"
    assert kv["PRESERVED"] == "0"
    assert "not found" in kv["REASON"] or "no worktree" in kv["REASON"]


# ── acquire / release: git-fallback path (rimba absent) ──────────────────────


class TestGitFallbackRoundtrip:
    def test_acquire_then_release_completed_removes_everything(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr
            kv = _kv(acquired)
            assert kv["TASK"] == branch
            assert kv["BRANCH"] == branch
            assert kv["PROVIDER"] == "git"
            assert kv["CREATED"] == "1"
            assert Path(kv["WT"]).resolve() == expected_wt.resolve()
            assert expected_wt.is_dir()

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["WORKTREE_REMOVED"] == "1"
            assert rkv["BRANCH_DELETED"] == "1"
            assert rkv["PRESERVED"] == "0"
            assert rkv["PROVIDER"] == "git"
            assert not expected_wt.exists()
            assert subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
                cwd=str(repo), capture_output=True, env=_CLEAN_ENV,
            ).returncode != 0
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_acquire_then_release_declined_removes_everything(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "declined"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["WORKTREE_REMOVED"] == "1"
            assert not expected_wt.exists()
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_release_failed_intent_preserves(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "failed"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["WORKTREE_REMOVED"] == "0"
            assert rkv["PRESERVED"] == "1"
            assert "failed" in rkv["REASON"]
            assert expected_wt.is_dir(), "a failed-intent release must preserve the worktree for inspection"
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_release_completed_preserves_dirty_worktree(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr
            (expected_wt / "uncommitted.txt").write_text("local-only work\n")

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["WORKTREE_REMOVED"] == "0"
            assert rkv["PRESERVED"] == "1"
            assert "uncommitted" in rkv["REASON"]
            assert (expected_wt / "uncommitted.txt").exists(), (
                "a dirty worktree must never be force-removed on a completed/declined intent"
            )
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_release_completed_removal_failure_reports_preserved(self, tmp_path):
        """A genuinely-attempted-but-failed removal (not a deliberate dirty-skip) must still
        report PRESERVED=1 -- WORKTREE_REMOVED/PRESERVED must stay an exhaustive pair whenever
        a worktree was found, so a caller checking only the booleans (not REASON text) can't
        mistake 'removal failed, still on disk' for 'nothing was ever found'."""
        if os.geteuid() == 0:
            pytest.skip("permission-denial is not enforceable when running as root")

        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr
            os.chmod(expected_wt, 0o555)

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"], env)
            os.chmod(expected_wt, 0o755)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["WORKTREE_REMOVED"] == "0"
            assert rkv["PRESERVED"] == "1"
            assert "removal failed" in rkv["REASON"]
            assert expected_wt.exists(), "removal must have genuinely failed for this test to be meaningful"
        finally:
            if expected_wt.exists():
                os.chmod(expected_wt, 0o755)
            _cleanup_worktree(repo, expected_wt, branch)

    def test_mode_scoped_no_collision_between_concurrent_modes(self, tmp_path):
        """first-pass and followup acquired for the same PR must never collide --
        distinct paths, distinct branches, independently releasable."""
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        wt_first = Path("/tmp/swe-workbench-pr-review") / n
        wt_followup = Path("/tmp/swe-workbench-pr-review") / f"{n}-followup"

        try:
            a1 = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            a2 = _run_script(repo, ["acquire", "--mode", "followup", "--pr", n], env)
            assert a1.returncode == 0, a1.stderr
            assert a2.returncode == 0, a2.stderr
            kv1, kv2 = _kv(a1), _kv(a2)
            assert kv1["WT"] != kv2["WT"]
            assert kv1["TASK"] != kv2["TASK"]
            assert wt_first.is_dir() and wt_followup.is_dir()

            r1 = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"], env)
            assert r1.returncode == 0
            assert not wt_first.exists()
            assert wt_followup.is_dir(), "releasing first-pass must not touch the followup worktree"

            r2 = _run_script(repo, ["release", "--mode", "followup", "--pr", n, "--intent", "completed"], env)
            assert r2.returncode == 0
            assert not wt_followup.exists()
        finally:
            _cleanup_worktree(repo, wt_first, f"pr-review-{n}")
            _cleanup_worktree(repo, wt_followup, f"pr-followup-{n}")

    def test_acquire_self_heals_stale_clean_collision(self, tmp_path):
        """A clean, stale worktree left at the same (mode, pr) label must be torn
        down and replaced, not left in place or fatally collided with."""
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            first = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert first.returncode == 0, first.stderr
            marker = expected_wt / "stale-marker.txt"
            marker.write_text("from the first acquire\n")
            _run("git", "add", "stale-marker.txt", cwd=expected_wt)
            _run("git", "commit", "-m", "stale commit", cwd=expected_wt)

            second = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert second.returncode == 0, second.stderr
            assert expected_wt.is_dir()
            assert not marker.exists(), "self-heal must replace the stale worktree, not leave it in place"
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_acquire_refuses_dirty_stale_collision(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        env = _rimba_absent_env(tmp_path / "fake_home")
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        expected_wt = Path("/tmp/swe-workbench-pr-review") / n
        branch = f"pr-review-{n}"

        try:
            first = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert first.returncode == 0, first.stderr
            dirty_file = expected_wt / "dirty.txt"
            dirty_file.write_text("uncommitted\n")

            second = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert second.returncode != 0
            assert second.stdout == ""
            assert "uncommitted changes" in second.stderr
            assert dirty_file.exists(), "acquire must never silently discard uncommitted local-only work"
        finally:
            _cleanup_worktree(repo, expected_wt, branch)


# ── acquire / release: rimba path (via stub) ──────────────────────────────────


class TestRimbaPath:
    def test_acquire_then_release_completed_removes_everything(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        stub_dir = _write_rimba_stub(tmp_path)
        wt_root = tmp_path / "rimba_worktrees"
        env = _rimba_present_env(tmp_path / "fake_home", stub_dir, repo, wt_root)
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        branch = f"pr-review-{n}"
        expected_wt = wt_root / branch

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr
            kv = _kv(acquired)
            assert kv["TASK"] == branch
            assert kv["PROVIDER"] == "rimba"
            assert Path(kv["WT"]).resolve() == expected_wt.resolve()
            assert expected_wt.is_dir()

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["WORKTREE_REMOVED"] == "1"
            assert rkv["BRANCH_DELETED"] == "1"
            assert rkv["PROVIDER"] == "rimba"
            assert not expected_wt.exists()
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_release_failed_intent_preserves(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        stub_dir = _write_rimba_stub(tmp_path)
        wt_root = tmp_path / "rimba_worktrees"
        env = _rimba_present_env(tmp_path / "fake_home", stub_dir, repo, wt_root)
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        branch = f"pr-review-{n}"
        expected_wt = wt_root / branch

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "failed"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["PRESERVED"] == "1"
            assert expected_wt.is_dir()
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_release_completed_preserves_dirty_worktree(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        stub_dir = _write_rimba_stub(tmp_path)
        wt_root = tmp_path / "rimba_worktrees"
        env = _rimba_present_env(tmp_path / "fake_home", stub_dir, repo, wt_root)
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        branch = f"pr-review-{n}"
        expected_wt = wt_root / branch

        try:
            acquired = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert acquired.returncode == 0, acquired.stderr
            (expected_wt / "uncommitted.txt").write_text("local-only work\n")

            released = _run_script(repo, ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"], env)
            assert released.returncode == 0, released.stderr
            rkv = _kv(released)
            assert rkv["PRESERVED"] == "1"
            assert (expected_wt / "uncommitted.txt").exists()
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_acquire_self_heals_stale_clean_collision(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        stub_dir = _write_rimba_stub(tmp_path)
        wt_root = tmp_path / "rimba_worktrees"
        env = _rimba_present_env(tmp_path / "fake_home", stub_dir, repo, wt_root)
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        branch = f"pr-review-{n}"
        expected_wt = wt_root / branch

        try:
            first = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert first.returncode == 0, first.stderr
            marker = expected_wt / "stale-marker.txt"
            marker.write_text("from the first acquire\n")
            _run("git", "add", "stale-marker.txt", cwd=expected_wt)
            _run("git", "commit", "-m", "stale commit", cwd=expected_wt)

            second = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert second.returncode == 0, second.stderr
            assert not marker.exists()
        finally:
            _cleanup_worktree(repo, expected_wt, branch)

    def test_acquire_refuses_dirty_stale_collision(self, tmp_path):
        n = _unique_n()
        repo = _build_repo_with_pr_ref(tmp_path, n)
        stub_dir = _write_rimba_stub(tmp_path)
        wt_root = tmp_path / "rimba_worktrees"
        env = _rimba_present_env(tmp_path / "fake_home", stub_dir, repo, wt_root)
        (tmp_path / "fake_home").mkdir(exist_ok=True)
        branch = f"pr-review-{n}"
        expected_wt = wt_root / branch

        try:
            first = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert first.returncode == 0, first.stderr
            dirty_file = expected_wt / "dirty.txt"
            dirty_file.write_text("uncommitted\n")

            second = _run_script(repo, ["acquire", "--mode", "first-pass", "--pr", n], env)
            assert second.returncode != 0
            assert second.stdout == ""
            assert "uncommitted changes" in second.stderr
            assert dirty_file.exists(), "acquire must never silently discard uncommitted local-only work"
        finally:
            _cleanup_worktree(repo, expected_wt, branch)


# ── repo-scoped fallbacks (issue #713) ───────────────────────────────────────


def test_names_scoped_fallbacks_with_explicit_repo():
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n, "--repo", "octocat/widgets"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode == 0, result.stderr
    data = {item["mode"]: item for item in json.loads(result.stdout)}
    assert data["first-pass"]["fallback_path"] == f"/tmp/swe-workbench-pr-review/octocat-widgets-{n}"
    assert data["first-pass"]["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/{n}"
    assert data["followup"]["fallback_path"] == f"/tmp/swe-workbench-pr-review/octocat-widgets-{n}-followup"
    assert data["followup"]["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/{n}-followup"
    assert data["security"]["fallback_path"] == f"/tmp/swe-workbench-pr-review/octocat-widgets-security-{n}"
    assert data["security"]["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/security-{n}"
    # Rimba task/branch labels are per-repo git objects already — unchanged.
    assert data["first-pass"]["label"] == f"pr-review-{n}"
    assert data["security"]["label"] == f"review-security-{n}"


def test_names_legacy_when_origin_unresolvable(tmp_path):
    """No remote at all -> empty slug -> legacy names, legacy == scoped."""
    repo = _build_repo(tmp_path)
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n],
        capture_output=True, text=True, env=dict(_CLEAN_ENV), cwd=str(repo),
    )
    assert result.returncode == 0, result.stderr
    data = {item["mode"]: item for item in json.loads(result.stdout)}
    fp = data["first-pass"]
    assert fp["fallback_path"] == fp["legacy_fallback_path"] == f"/tmp/swe-workbench-pr-review/{n}"


def test_names_rejects_invalid_repo_value():
    n = _unique_n()
    result = subprocess.run(
        ["bash", str(SCRIPT), "names", "--pr", n, "--repo", "bogus"],
        capture_output=True, text=True, env=dict(_CLEAN_ENV),
    )
    assert result.returncode != 0


def test_release_finds_legacy_fallback_worktree_dual_read(tmp_path):
    """Pre-upgrade acquire / post-upgrade release: the worktree sits at the
    legacy un-scoped fallback path; release must still find and remove it."""
    repo = _build_repo(tmp_path)
    _run("git", "remote", "add", "origin", "https://github.com/octocat/widgets.git", cwd=repo)
    (tmp_path / "fake_home").mkdir(exist_ok=True)
    env = _rimba_absent_env(tmp_path / "fake_home")
    n = _unique_n()
    legacy = Path("/tmp/swe-workbench-pr-review") / n
    branch = f"pr-review-{n}"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _run("git", "worktree", "add", "--detach", str(legacy), "main", cwd=repo)
    try:
        result = _run_script(
            repo,
            ["release", "--mode", "first-pass", "--pr", n, "--intent", "completed"],
            env,
        )
        assert result.returncode == 0, result.stderr
        kv = _kv(result)
        assert kv["WORKTREE_REMOVED"] == "1"
        assert not legacy.exists()
    finally:
        _cleanup_worktree(repo, legacy, branch)
