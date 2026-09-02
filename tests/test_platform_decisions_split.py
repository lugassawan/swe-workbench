"""Guard tests for the plugin-platform-decisions docs split.

The former monolith is now split into topic-scoped docs/decisions-*.md files so a
new ruling lands in the doc that owns its topic instead of growing one file
without bound. These tests pin the split: the family exists, the monolith is
gone, docs/README.md indexes every member, and no stale reference (filename or
out-of-range section number) survives anywhere in the repo.
"""

import re
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV
from validate import ROOT

MONOLITH_STEM = "plugin-platform-decisions"

FAMILY = {
    "decisions-bin-path.md",
    "decisions-ci-validation.md",
    "decisions-hooks.md",
    "decisions-pi-port.md",
    "decisions-task-dispatch.md",
    "decisions-runtime-envelope.md",
    "decisions-cross-harness.md",
}


def test_family_docs_exist():
    for name in sorted(FAMILY):
        assert (ROOT / "docs" / name).is_file(), f"docs/{name} missing"


def test_monolith_is_gone():
    assert not (ROOT / "docs" / f"{MONOLITH_STEM}.md").exists(), (
        f"docs/{MONOLITH_STEM}.md must not coexist with the docs/decisions-*.md family — "
        "new rulings go into the topic doc that owns them, not back into a monolith"
    )


def test_docs_readme_indexes_family():
    text = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    for name in sorted(FAMILY):
        assert f"]({name})" in text, f"docs/README.md missing index entry for {name}"
    assert f"]({MONOLITH_STEM}.md)" not in text, (
        "docs/README.md still indexes the retired monolith"
    )


def _tracked_files():
    """Yield repo-relative paths of all git-tracked files (gitignored planning
    roots and scratch state are excluded by construction, because git does not
    list them)."""
    self_path = Path(__file__).resolve()
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
        env=_CLEAN_ENV,
    ).stdout.splitlines()
    for rel in listed:
        if rel.startswith("tests/fixtures/"):
            continue  # historical corpus diffs legitimately name the monolith
        path = ROOT / rel
        if path.is_file() and path.resolve() != self_path:
            yield rel, path


def test_no_stale_monolith_references():
    offenders = []
    for rel, path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if MONOLITH_STEM in text:
            offenders.append(rel)
    assert not offenders, (
        f"stale '{MONOLITH_STEM}' references — point them at docs/decisions-*.md: {offenders}"
    )


# A decisions-*.md mention qualified by a section number, allowing for wrapped
# prose between the filename and the §N (e.g. validate.py's error strings).
_SECTION_REF_RE = re.compile(r"decisions-([a-z-]+)\.md[^§]{0,80}§(\d+)", re.DOTALL)


def _section_count(name):
    text = (ROOT / "docs" / name).read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^## ", text))


def test_section_number_references_are_in_range():
    """Every `decisions-<topic>.md §N` reference must name a section that exists.

    The split renumbered sections per-doc; an inbound §-qualified reference that
    drifts past a future section insert or reorder would point at the wrong
    ruling with nothing failing. This pins the number against the target doc's
    actual `## ` heading count.
    """
    offenders = []
    for rel, path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in _SECTION_REF_RE.finditer(text):
            target = f"decisions-{match.group(1)}.md"
            num = int(match.group(2))
            if target not in FAMILY:
                offenders.append(f"{rel}: unknown decisions doc {target!r}")
                continue
            count = _section_count(target)
            if not 1 <= num <= count:
                offenders.append(
                    f"{rel}: {target} §{num} out of range (doc has §1–§{count})"
                )
    assert not offenders, (
        f"section-number references past a doc's heading count: {offenders}"
    )
