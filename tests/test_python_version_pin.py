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
    ci_versions = re.findall(r"python-version:\s*['\"]?(\d+(?:\.\d+)+)['\"]?", pr_yml)
    assert ci_versions, "Could not find python-version in .github/workflows/pr.yml"

    # Multi-interpreter workflows carry auxiliary versions (e.g. a 3.9 floor check
    # alongside the primary 3.12), so parity means the pin runs SOMEWHERE in CI —
    # a pin absent from every CI job is still the drift this guard exists to catch.
    assert pin in ci_versions, (
        f".python-version pins {pin!r} but pr.yml uses {sorted(set(ci_versions))!r}; "
        "update .python-version to match"
    )
