"""Guard: each issue template's frontmatter labels: value is correct (#336)."""

import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"

EXPECTED_LABELS = [
    ("chore_maintenance.md", "chore"),
    ("bug_report.md", "bug"),
    ("feature_request.md", "enhancement"),
]


def _frontmatter_labels(template_path: Path) -> str:
    """Return the `labels:` value from the YAML frontmatter block."""
    lines = template_path.read_text(encoding="utf-8").splitlines()
    in_frontmatter = False
    for line in lines:
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            break
        if in_frontmatter and line.startswith("labels:"):
            return line.split(":", 1)[1].strip()
    return ""


@pytest.mark.parametrize("filename,expected_label", EXPECTED_LABELS)
def test_issue_template_frontmatter_label(filename: str, expected_label: str) -> None:
    """Each template must declare exactly the right labels: value."""
    path = TEMPLATES_DIR / filename
    assert path.exists(), f"Template file missing: {path}"
    actual = _frontmatter_labels(path)
    if filename == "chore_maintenance.md":
        assert actual != "documentation", (
            "chore_maintenance.md must not use 'documentation' label — regression guard for #336"
        )
    assert actual == expected_label, (
        f"{filename}: expected labels: {expected_label!r}, got {actual!r}"
    )
