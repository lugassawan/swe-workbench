"""Tests for workflow-audit-emit-issues skill (#345)."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "workflow-audit-emit-issues"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGERS = SKILL_DIR / "triggers.txt"
WORKFLOWS_MD = ROOT / "agents" / "shared" / "workflows.md"
CATALOG_MD = ROOT / "docs" / "catalog.md"


def _parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def _body(text: str) -> str:
    """Return text after the closing --- of frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1:])
    return text


# ── file existence ────────────────────────────────────────────────────────────

def test_skill_md_exists():
    assert SKILL_MD.exists(), "skills/workflow-audit-emit-issues/SKILL.md must exist"


def test_triggers_txt_exists():
    assert TRIGGERS.exists(), "skills/workflow-audit-emit-issues/triggers.txt must exist"


# ── frontmatter ───────────────────────────────────────────────────────────────

def test_frontmatter_name():
    fm = _parse_frontmatter(SKILL_MD.read_text())
    assert fm.get("name") == "workflow-audit-emit-issues", (
        "frontmatter 'name' must be 'workflow-audit-emit-issues'"
    )


def test_frontmatter_orchestrator_true():
    fm = _parse_frontmatter(SKILL_MD.read_text())
    assert fm.get("orchestrator", "").lower() == "true", (
        "frontmatter must include 'orchestrator: true' (enables 300-line cap)"
    )


def test_frontmatter_description_keywords():
    fm = _parse_frontmatter(SKILL_MD.read_text())
    desc = fm.get("description", "").lower()
    for kw in ("audit findings", "grouped", "github issues", "subsystem", "emit"):
        assert kw in desc, (
            f"frontmatter description must contain keyword '{kw}' for trigger scoring"
        )


# ── line cap ─────────────────────────────────────────────────────────────────

def test_skill_within_300_lines():
    lines = SKILL_MD.read_text().splitlines()
    assert len(lines) <= 300, (
        f"skills/workflow-audit-emit-issues/SKILL.md has {len(lines)} lines; "
        "orchestrator cap is 300"
    )


# ── required CLI patterns ────────────────────────────────────────────────────

def test_gh_issue_create_present():
    text = SKILL_MD.read_text()
    assert "gh issue create" in text, "SKILL.md must contain 'gh issue create'"


def test_body_file_flag_present():
    text = SKILL_MD.read_text()
    assert "--body-file" in text, (
        "SKILL.md must use --body-file (not --template) for issue creation"
    )


def test_gh_label_list_present():
    text = SKILL_MD.read_text()
    assert "gh label list" in text, (
        "SKILL.md must call 'gh label list' for template/label discovery"
    )


def test_gh_issue_create_template_absent():
    text = SKILL_MD.read_text()
    assert "gh issue create --template" not in text, (
        "SKILL.md must NOT use 'gh issue create --template'; use --body-file instead"
    )


# ── confirm / preview gate ────────────────────────────────────────────────────

def test_confirm_keyword_present():
    text = SKILL_MD.read_text().lower()
    assert "confirm" in text, (
        "SKILL.md must mention the 'confirm' gate for filing"
    )


def test_preview_keyword_present():
    text = SKILL_MD.read_text().lower()
    assert "preview" in text, (
        "SKILL.md must mention 'preview' (batch preview before filing)"
    )


def test_drop_n_edit_n_present():
    text = SKILL_MD.read_text()
    assert "drop" in text and ("edit" in text.lower()), (
        "SKILL.md must document 'drop N' and 'edit N' for the confirm gate"
    )


# ── grouping / subsystem logic ────────────────────────────────────────────────

def test_subsystem_grouping_documented():
    text = SKILL_MD.read_text().lower()
    assert "subsystem" in text, (
        "SKILL.md must document subsystem-based grouping of findings"
    )


def test_path_prefix_grouping_documented():
    text = SKILL_MD.read_text().lower()
    assert "path" in text and "prefix" in text, (
        "SKILL.md must document path-prefix derivation for subsystem labels"
    )


def test_misc_fallback_documented():
    text = SKILL_MD.read_text().lower()
    assert "misc" in text, (
        "SKILL.md must document 'misc' as the fallback subsystem for findings with no path"
    )


# ── cycle-safety: no action verbs targeting resolvable refs ──────────────────

_ACTION_RE = re.compile(
    r'\b(invoke|activate|apply|execute via|dispatch|delegate|compose|consult|run)\b',
    re.IGNORECASE,
)
_POINTER_RE = re.compile(
    r'\b(see|defer to|recommend|like|per |unlike|e\.g\.|cf\.|analogous|mirror|'
    r'follows the|precedent|such as|similar to|counterpart|note them)\b',
    re.IGNORECASE,
)
_REF_RE = re.compile(r'`swe-workbench:([\w-]+)`')

# Skills that must not be activated (back-edges) from this new skill.
_AUDIT_CHAIN = {"workflow-codebase-audit", "workflow-bug-triage"}


_PLAIN_AUDIT_RE = re.compile(r'`(workflow-codebase-audit|workflow-bug-triage)`')


def test_no_action_verb_to_audit_chain():
    """The new skill must not action-cue into the audit chain (would create a cycle)."""
    text = SKILL_MD.read_text()
    for line in text.splitlines():
        if line.lstrip().startswith("@"):
            continue
        refs = _REF_RE.findall(line)
        chain_refs = [r for r in refs if r in _AUDIT_CHAIN]
        if not chain_refs:
            continue
        if _ACTION_RE.search(line) and not _POINTER_RE.search(line):
            pytest_fail = ", ".join(f"`swe-workbench:{r}`" for r in chain_refs)
            assert False, (
                f"Line contains an action verb targeting audit-chain skill(s) {pytest_fail} — "
                "this creates a dependency cycle. Use pointer words only (see, mirrors, etc.).\n"
                f"  Line: {line.strip()}"
            )


def test_no_action_verb_to_audit_chain_plain_refs():
    """Plain backtick refs (no swe-workbench: prefix) are invisible to _REF_RE but still
    resolve in validate.py — guard those too."""
    text = SKILL_MD.read_text()
    for line in text.splitlines():
        if line.lstrip().startswith("@"):
            continue
        if not _PLAIN_AUDIT_RE.search(line):
            continue
        if _ACTION_RE.search(line) and not _POINTER_RE.search(line):
            assert False, (
                f"Plain ref with action verb — potential back-edge: {line.strip()}"
            )


# ── resolvable swe-workbench refs ────────────────────────────────────────────

def _all_resolvable_ids() -> set:
    ids: set = set()
    for skill_dir in (ROOT / "skills").iterdir():
        if (skill_dir / "SKILL.md").is_file():
            ids.add(skill_dir.name)
    for agent_md in (ROOT / "agents").glob("*.md"):
        ids.add(agent_md.stem)
    for cmd_md in (ROOT / "commands").glob("*.md"):
        ids.add(cmd_md.stem)
    return ids


def test_all_swe_workbench_refs_resolve():
    text = SKILL_MD.read_text()
    resolvable = _all_resolvable_ids()
    for ref in _REF_RE.findall(text):
        # Exclude the skill itself
        if ref == "workflow-audit-emit-issues":
            continue
        assert ref in resolvable, (
            f"`swe-workbench:{ref}` referenced in SKILL.md but not found on disk"
        )


# ── catalog registration ──────────────────────────────────────────────────────

def test_workflows_md_contains_name():
    text = WORKFLOWS_MD.read_text()
    assert "workflow-audit-emit-issues" in text, (
        "agents/shared/workflows.md must contain 'workflow-audit-emit-issues'"
    )


def test_catalog_md_contains_name():
    text = CATALOG_MD.read_text()
    assert "workflow-audit-emit-issues" in text, (
        "docs/catalog.md must contain 'workflow-audit-emit-issues'"
    )


def test_readme_contains_name():
    readme = ROOT / "README.md"
    text = readme.read_text()
    assert "workflow-audit-emit-issues" in text, (
        "README.md Workflows bullet must contain 'workflow-audit-emit-issues'"
    )


# ── triggers.txt ─────────────────────────────────────────────────────────────

def test_triggers_has_at_least_two_fixtures():
    lines = [l.strip() for l in TRIGGERS.read_text().splitlines() if l.strip()]
    assert len(lines) >= 2, (
        f"triggers.txt must have ≥2 trigger fixtures; found {len(lines)}"
    )


def test_triggers_mention_audit_and_issues():
    text = TRIGGERS.read_text().lower()
    assert "audit" in text and ("issue" in text or "github" in text), (
        "triggers.txt must mention 'audit' and 'issue'/'github' for good trigger scoring"
    )
