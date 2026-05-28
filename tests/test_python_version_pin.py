"""Parity guard: .python-version must match the python-version declared in pr.yml.

Prevents silent drift where CI runs Python X but local tooling uses Python Y.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_python_version_file_exists():
    assert (ROOT / ".python-version").exists(), ".python-version is missing"


def test_python_version_file_matches_pr_yml():
    pin = (ROOT / ".python-version").read_text().strip()

    pr_yml = (ROOT / ".github" / "workflows" / "pr.yml").read_text()
    match = re.search(r"python-version:\s*['\"]?(\d+(?:\.\d+)+)['\"]?", pr_yml)
    assert match, "Could not find python-version in .github/workflows/pr.yml"
    ci_version = match.group(1)

    assert pin == ci_version, (
        f".python-version pins {pin!r} but pr.yml uses {ci_version!r}; "
        "update .python-version to match"
    )
