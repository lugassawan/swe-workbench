"""Tests for bin/swe-workbench-pr-title-drift.

Behavioral tests drive the script as a subprocess against a throwaway git repo
(test_preflight_commit_script.py's `_init_repo`/`_CLEAN_ENV` precedents). The
`--title`/`--base` overrides keep every test hermetic — no `gh` call, no network.
Diff scope is read via merge-base against the resolved base ref, mirroring what
the calling skills do after a sync.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "swe-workbench-pr-title-drift"


# ── Behavioral test harness ─────────────────────────────────────────────────


def _git(args, *, cwd: Path):
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(cwd), env=dict(_CLEAN_ENV)
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(tmp_path: Path) -> Path:
    _git(["init", "-b", "main", str(tmp_path)], cwd=tmp_path)
    _git(["config", "user.email", "test@example.com"], cwd=tmp_path)
    _git(["config", "user.name", "Test Fixture"], cwd=tmp_path)
    return tmp_path


def _commit(cwd: Path, files: dict, msg: str):
    for rel, content in files.items():
        path = cwd / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(["add", "-A"], cwd=cwd)
    _git(["commit", "-m", msg], cwd=cwd)


def _feature_repo(tmp_path: Path, feature_files: dict, *, base_files: dict | None = None):
    """main carries `base_files` (may be empty); feature carries `feature_files`.

    Returns the repo path. The script is invoked with `--base main` so the
    local-branch fallback of base resolution is what the fixture exercises.
    """
    repo = _init_repo(tmp_path)
    if base_files:
        _commit(repo, base_files, "base state")
    else:
        # An unborn main would make `--base main` unresolvable; anchor it.
        _commit(repo, {"anchor.txt": "anchor"}, "anchor")
    _git(["checkout", "-b", "feature"], cwd=repo)
    if feature_files:
        _commit(repo, feature_files, "feature work")
    return repo


def _run(args=(), *, cwd: Path, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env if env is not None else dict(_CLEAN_ENV),
    )


def _envelope(result) -> dict:
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)


def _drift(cwd: Path, title: str, *, base: str = "main", pr: int | None = None):
    args = ["--title", title, "--base", base]
    if pr is not None:
        args = ["--pr", str(pr), *args]
    return _envelope(_run(args, cwd=cwd))["data"]


# ── Existence ────────────────────────────────────────────────────────────────


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "bin/swe-workbench-pr-title-drift must exist"
    assert os.access(SCRIPT, os.X_OK), "bin/swe-workbench-pr-title-drift must be executable (chmod +x)"


# ── Classification and verdicts ──────────────────────────────────────────────


def test_type_vs_scope_classification(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[feat][service-x] Add X")
    assert data["type_tags"] == ["feat"]
    assert data["scope_tags"] == ["service-x"]


def test_clean_verdict(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[feat][service-x] Add X")
    assert data["verdict"] == "clean"
    assert data["extra_tags"] == []
    assert data["missing_scopes"] == []
    assert data["suggested_title"] == "[feat][service-x] Add X"


def test_pure_extra_trim(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[feat][service-x][service-y] Harden parsers")
    assert data["extra_tags"] == ["service-y"]
    assert data["missing_scopes"] == []
    assert data["verdict"] == "pure_extra"
    assert data["suggested_title"] == "[feat][service-x] Harden parsers"


def test_deeper_component_not_trimmable(tmp_path):
    # A tag matching NO first component but SOME deeper path component is not
    # drift: the layout just buries the module. It must not become trimmable.
    repo = _feature_repo(tmp_path, {"core/service-y/f.py": "y"})
    data = _drift(repo, "[feat][service-y] Move parser")
    assert data["extra_tags"] == []
    assert data["missing_scopes"] == []
    assert data["verdict"] == "clean"
    assert data["suggested_title"] == "[feat][service-y] Move parser"


def test_mixed_verdict_rebuilds_kept_then_missing_tags(tmp_path):
    repo = _feature_repo(
        tmp_path,
        {"service-y/src/a.py": "y", "service-z/src/b.py": "z"},
    )
    data = _drift(repo, "[feat][service-y][obsolete] Support modules")
    assert data["extra_tags"] == ["obsolete"]
    assert data["missing_scopes"] == ["service-z"]
    assert data["verdict"] == "mixed"
    assert data["suggested_title"] == "[feat][service-y][service-z] Support modules"


def test_component_prefix_not_trimmable(tmp_path):
    repo = _feature_repo(tmp_path, {"server/api_v2/routes.py": "x"})
    title = "[feat][server][api] Add endpoint"
    data = _drift(repo, title)
    assert data["extra_tags"] == []
    assert data["verdict"] == "clean"
    assert data["suggested_title"] == title


def test_missing_direction(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x", "service-z/src/b.py": "z"})
    data = _drift(repo, "[feat][service-x] Add X")
    assert data["missing_scopes"] == ["service-z"]
    assert data["extra_tags"] == []
    assert data["verdict"] == "missing"
    assert data["suggested_title"] == "[feat][service-x][service-z] Add X"


def test_docs_only_paths_excluded_from_missing(tmp_path):
    # A docs-only diff carries no code scope: docs scopes never go missing, and
    # the extra-direction is suppressed too (trimming tags off a docs-only PR
    # on the diff's silence would fire the auto-trim on noise).
    repo = _feature_repo(tmp_path, {"docs/foo.md": "d", "README.md": "r"})
    data = _drift(repo, "[feat][core] Refactor core")
    assert data["diff_scopes"] == ["docs"]
    assert data["missing_scopes"] == []
    assert data["extra_tags"] == []
    assert data["verdict"] == "clean"


def test_no_scope_tags_noop(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[feat] plain conventional title")
    assert data["verdict"] == "no_scope_tags"
    assert data["scope_tags"] == []
    assert data["suggested_title"] == "[feat] plain conventional title"


def test_no_diff_verdict(tmp_path):
    # Base at HEAD: empty diff range.
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[feat][service-x] Add X", base="HEAD")
    assert data["verdict"] == "no_diff"


def test_no_diff_on_unrelated_histories(tmp_path):
    # An orphan base has no merge-base with HEAD — verdict no_diff, never a crash.
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    _git(["checkout", "--orphan", "unrelated"], cwd=repo)
    _git(["rm", "-rf", "--quiet", "."], cwd=repo)
    _commit(repo, {"other.txt": "o"}, "unrelated root")
    _git(["checkout", "feature"], cwd=repo)
    data = _drift(repo, "[feat][service-x] Add X", base="unrelated")
    assert data["verdict"] == "no_diff"


def test_sole_extra_tag_suggested_title(tmp_path):
    # One extra tag + a root-level code file (no first component → no missing
    # scope): pure_extra whose suggested title retains zero scope tags. The
    # auto-apply gate is policy-side (skills), not the script's.
    repo = _feature_repo(tmp_path, {"build.sh": "echo hi"})
    data = _drift(repo, "[feat][service-x] Add X")
    assert data["extra_tags"] == ["service-x"]
    assert data["missing_scopes"] == []
    assert data["verdict"] == "pure_extra"
    assert data["suggested_title"] == "[feat] Add X"


def test_kebab_normalization(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[feat][Service_X] Add X")
    assert data["verdict"] == "clean"
    assert data["scope_tags"] == ["Service_X"]  # original casing preserved in output


def test_subject_brackets_are_not_scope_tags(tmp_path):
    repo = _feature_repo(tmp_path, {"core/src/a.py": "x"})
    title = "[feat][core] Support [v2] endpoint"
    data = _drift(repo, title)
    assert data["scope_tags"] == ["core"]
    assert data["verdict"] == "clean"
    assert data["suggested_title"] == title


def test_type_vocabulary_case_insensitive(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    data = _drift(repo, "[Feat][service-x] Add X")
    assert data["type_tags"] == ["Feat"]
    assert data["scope_tags"] == ["service-x"]
    assert data["verdict"] == "clean"
    # Superset vocabulary: conventional-commit extras are types, not scopes.
    data = _drift(repo, "[build] tweak pipeline")
    assert data["type_tags"] == ["build"]
    assert data["scope_tags"] == []
    assert data["verdict"] == "no_scope_tags"


def test_fail_closed_empty_stdout(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    # (a) unresolvable base ref
    result = _run(["--title", "[feat][service-x] t", "--base", "no-such-ref"], cwd=repo)
    assert result.returncode != 0
    assert result.stdout == ""
    # (b) gh unreachable: --title without --base needs `gh pr view`; PATH holds
    # only a git symlink so gh cannot be found.
    bin_only_git = tmp_path / "bin-only-git"
    bin_only_git.mkdir()
    git_real = shutil.which("git")
    assert git_real, "git must be on PATH for the fixture"
    os.symlink(git_real, bin_only_git / "git")
    result = _run(["--title", "[feat][service-x] t"], cwd=repo,
                  env={**_CLEAN_ENV, "PATH": str(bin_only_git)})
    assert result.returncode != 0
    assert result.stdout == ""


def test_merge_base_operational_failure_fails_closed(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    wrapper_dir = tmp_path / "git-wrapper"
    wrapper_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git, "git must be on PATH for the fixture"
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = merge-base ]; then\n"
        "  echo 'simulated git failure' >&2\n"
        "  exit 128\n"
        "fi\n"
        f"exec {real_git} \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = _run(
        ["--title", "[feat][service-x] Add X", "--base", "main"],
        cwd=repo,
        env={**_CLEAN_ENV, "PATH": f"{wrapper_dir}{os.pathsep}{_CLEAN_ENV['PATH']}"},
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_envelope_shape(tmp_path):
    repo = _feature_repo(tmp_path, {"service-x/src/a.py": "x"})
    result = _run(["--pr", "42", "--title", "[feat][service-x] Add X", "--base", "main"], cwd=repo)
    env = _envelope(result)
    assert env["schema"] == "swb.pr-title-drift/1"
    assert env["status"] == "ok"
    assert env["warnings"] == []
    assert set(env["data"].keys()) == {
        "pr", "title", "base", "diff_scopes", "type_tags", "scope_tags",
        "extra_tags", "missing_scopes", "verdict", "suggested_title",
    }
    assert env["data"]["pr"] == 42
    assert isinstance(env["data"]["pr"], int)
