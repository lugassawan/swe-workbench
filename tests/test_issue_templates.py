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
    """Return the scalar labels: value from the YAML frontmatter block.

    Only handles the single-value form (labels: chore), not multi-value
    YAML lists. Sufficient for all current templates.
    """
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
    assert actual == expected_label, (
        f"{filename}: expected labels: {expected_label!r}, got {actual!r}"
        + (" — regression guard for #336" if filename == "chore_maintenance.md" else "")
    )


def test_bug_report_has_harness_section():
    """bug_report.md must offer a harness-agnostic environment section: a checkbox
    selector naming both harnesses, and a version field naming both capture commands."""
    text = (TEMPLATES_DIR / "bug_report.md").read_text(encoding="utf-8")

    assert "## Harness" in text, (
        "bug_report.md must include a '## Harness' section (replacing the old "
        "Claude-Code-only '## Claude Code version' field)"
    )
    assert "## Claude Code version" not in text, (
        "bug_report.md must not retain the single-harness '## Claude Code version' heading"
    )
    harness_pos = text.find("## Harness")
    version_pos = text.find("## Harness version", harness_pos)
    assert version_pos != -1, (
        "bug_report.md must include a '## Harness version' section after '## Harness'"
    )
    plugin_pos = text.find("## Plugin version", version_pos)
    assert plugin_pos != -1, (
        "bug_report.md must retain '## Plugin version' after '## Harness version'"
    )

    harness_block = text[harness_pos:version_pos]
    assert "Claude Code" in harness_block, (
        "bug_report.md '## Harness' section must name Claude Code"
    )
    assert "Pi Coding Agent" in harness_block, (
        "bug_report.md '## Harness' section must name the Pi Coding Agent"
    )

    version_block = text[version_pos:plugin_pos]
    assert "claude --version" in version_block, (
        "bug_report.md '## Harness version' section must give the Claude Code capture command"
    )
    assert "pi --version" in version_block, (
        "bug_report.md '## Harness version' section must give the Pi capture command"
    )


@pytest.mark.parametrize("filename", ["bug_report.md", "feature_request.md"])
def test_surface_checklist_has_pi_adapter_row(filename: str) -> None:
    """bug_report.md and feature_request.md must both list the Pi adapter as a surface,
    keeping the two checklists in parity."""
    text = (TEMPLATES_DIR / filename).read_text(encoding="utf-8")
    assert "Pi adapter" in text and "pi/extensions/" in text, (
        f"{filename} must include a 'Pi adapter — `pi/extensions/`' row in its surface checklist"
    )


def test_chore_template_names_package_json_in_release_row():
    """chore_maintenance.md's Release / packaging row must name package.json alongside
    .claude-plugin/ and scripts/ — package.json is the Pi install manifest."""
    text = (TEMPLATES_DIR / "chore_maintenance.md").read_text(encoding="utf-8")
    release_line = next(
        (line for line in text.splitlines() if "Release / packaging" in line), None
    )
    assert release_line is not None, (
        "chore_maintenance.md must include a 'Release / packaging' row"
    )
    assert "package.json" in release_line, (
        "chore_maintenance.md's 'Release / packaging' row must name package.json "
        "(the Pi install manifest) alongside .claude-plugin/ and scripts/"
    )
