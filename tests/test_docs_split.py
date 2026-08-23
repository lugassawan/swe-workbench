"""Guard tests for the docs/ split: repo-governance vs skill-operational.

docs/ is repo-governance only (never shipped — the npm `files` allowlist excludes it).
Skill-operational-knowledge docs — gotcha material a skill's executor reads at runtime,
on any harness — live in shared/docs/ and ship via the `shared` allowlist entry.
"""

import json
import re

import pytest

from validate import ROOT

MOVED = {
    "shell-echo-vs-printf.md",
    "gh-api-field-flags.md",
    "workflow-state.md",
}

SHIPPED_TREES = ("skills", "commands", "agents", "shared", "hooks", "bin", "pi", ".claude-plugin")


@pytest.mark.parametrize("name", sorted(MOVED))
def test_moved_doc_lives_under_shared_docs(name):
    assert (ROOT / "shared" / "docs" / name).exists(), f"shared/docs/{name} missing"
    assert not (ROOT / "docs" / name).exists(), f"docs/{name} must not remain in docs/"


@pytest.mark.parametrize("name", sorted(MOVED))
def test_shared_docs_readme_indexes_moved_doc(name):
    text = (ROOT / "shared" / "docs" / "README.md").read_text(encoding="utf-8")
    assert name in text, f"shared/docs/README.md missing index entry for {name}"


def test_docs_readme_points_at_shared_docs_without_moved_entries():
    text = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "shared/docs/" in text, "docs/README.md must point readers at shared/docs/"
    for name in MOVED:
        assert f"]({name})" not in text, f"docs/README.md still indexes {name}"


def test_package_json_files_ships_shared_not_docs():
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    files = pkg["files"]
    assert "shared" in files, "package.json files must include 'shared'"
    assert not any(f == "docs" or f.startswith("docs/") for f in files), files


def test_shipped_trees_cover_plain_directory_files_entries():
    """A new top-level tree added to package.json files must reach the stale-ref scan.

    Only the slash-free, glob-free entries are checked: the glob-derived trees
    (bin/swe-workbench-*, hooks/*.sh, pi/extensions) map onto SHIPPED_TREES members
    but have no exact-entry counterpart, so asserting those would be brittle.
    """
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    plain_dirs = {f for f in pkg["files"] if "/" not in f and "*" not in f}
    missing = plain_dirs - set(SHIPPED_TREES)
    assert not missing, (
        f"package.json ships {sorted(missing)} but SHIPPED_TREES does not cover them — "
        "the stale-reference guard would silently skip those trees"
    )


def test_no_shipped_tree_references_old_docs_paths():
    offenders = []
    scan_paths = [ROOT / tree for tree in SHIPPED_TREES] + [ROOT / "README.md"]
    for base in scan_paths:
        if not base.exists():
            continue
        paths = base.rglob("*") if base.is_dir() else [base]
        for path in paths:
            if not path.is_file() or "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name in MOVED:
                # (?<!shared/) — the relocated path shared/docs/<name> contains
                # docs/<name> as a substring; only bare docs/ paths are stale.
                if re.search(rf"(?<!shared/)docs/{re.escape(name)}", text):
                    offenders.append(f"{path.relative_to(ROOT)}: docs/{name}")
    assert not offenders, f"stale docs/ references in shipped trees: {offenders}"


def test_skill_cross_references_point_at_shared_docs():
    sites = {
        "skills/language-bash/SKILL.md": "shared/docs/shell-echo-vs-printf.md",
        "skills/workflow-pr-review-post/SKILL.md": "shared/docs/gh-api-field-flags.md",
        "skills/workflow-development/SKILL.md": "shared/docs/workflow-state.md",
        "skills/workflow-bug-triage/SKILL.md": "shared/docs/workflow-state.md",
        "skills/workflow-pr-review/SKILL.md": "shared/docs/workflow-state.md",
        "skills/workflow-worktree-session/SKILL.md": "shared/docs/workflow-state.md",
        "commands/converge.md": "shared/docs/workflow-state.md",
    }
    for rel, needle in sites.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert needle in text, f"{rel} missing reference to {needle}"
