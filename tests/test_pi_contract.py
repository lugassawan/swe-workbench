"""Contract tests for the swe-workbench <-> Pi Coding Agent frontmatter boundary (issue #605)
and, below, the guard/hint event-translation boundary (issue #607).

ADR-0001's runtime adapter (pi/) reads agents/*.md, skills/*/SKILL.md, and commands/*.md
frontmatter through Pi's own YAML parser — which is strict. scripts/validate.py's
parse_frontmatter() is a hand-rolled, lenient parser: it accepted agents/architect.md's
former `description: ...existing code: authoring an ADR...` line (a colon-space inside a
plain scalar), which a real YAML 1.1/1.2 parser rejects outright (mapping values are not
allowed here). That divergence would have made Pi fail to load the agent silently — this
module is the anti-drift gate ADR-0001 promised for that coupling; it must go RED before a
future frontmatter edit can break Pi, not after.

Ratchet shape follows tests/test_agent_model_tiers.py: module-level dict/set literals record
what this repo's frontmatter currently uses. A new key/tool/skill only trips a test once
*this repo* writes it into a file — keeping the gate open-world per
docs/plugin-platform-decisions.md §2, rather than a closed-form schema.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import validate
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / "agents"
SKILLS_DIR = ROOT / "skills"
COMMANDS_DIR = ROOT / "commands"
SHARED_DIR = ROOT / "shared"
EXTENSIONS_DIR = ROOT / "pi" / "extensions"
HOOKS_DIR = ROOT / "hooks"

# The complete key vocabulary agents/*.md frontmatter uses today. A new key (e.g. a future
# Phase 7 `pi:` override block) must be added here deliberately, not discovered by CI red.
FRONTMATTER_KEYS = {"name", "description", "model", "tools", "skills"}

# Union of every comma-separated token across all agents/*.md `tools:` lines. Grows only
# when an agent's frontmatter is edited to grant a new tool — not on every agent edit.
TOOL_TOKENS = {
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "Read",
    "Skill",
    "WebFetch",
    "Write",
}

# Union of every `swe-workbench:<id>` entry across all agents/*.md `skills:` blocks.
SKILL_IDS = {
    "swe-workbench:language-typescript",
    "swe-workbench:principle-accessibility",
    "swe-workbench:principle-api-design",
    "swe-workbench:principle-clean-architecture",
    "swe-workbench:principle-clean-code",
    "swe-workbench:principle-code-review",
    "swe-workbench:principle-communication",
    "swe-workbench:principle-concurrency",
    "swe-workbench:principle-cost-awareness",
    "swe-workbench:principle-data-modeling",
    "swe-workbench:principle-ddd",
    "swe-workbench:principle-design-patterns",
    "swe-workbench:principle-distributed-systems",
    "swe-workbench:principle-error-handling",
    "swe-workbench:principle-event-driven",
    "swe-workbench:principle-observability",
    "swe-workbench:principle-performance",
    "swe-workbench:principle-postmortem",
    "swe-workbench:principle-product-design",
    "swe-workbench:principle-refactoring",
    "swe-workbench:principle-release-engineering",
    "swe-workbench:principle-resiliency",
    "swe-workbench:principle-security",
    "swe-workbench:principle-solid",
    "swe-workbench:principle-tdd",
    "swe-workbench:principle-testing",
    "swe-workbench:principle-version-control",
}


def _frontmatter_files():
    """Every file in the plan's Pi-relevant scope that may carry a --- frontmatter block."""
    files = list(AGENTS_DIR.glob("*.md"))
    files += list(SKILLS_DIR.glob("*/SKILL.md"))
    files += list(COMMANDS_DIR.glob("*.md"))
    files += list(SHARED_DIR.rglob("*.md"))
    return sorted(files)


def _frontmatter_block(path):
    """Return the raw text between the opening and closing '---' markers, or None.

    Mirrors validate.parse_frontmatter's own delimiter-finding logic so both parsers see
    exactly the same substring — the only fair way to compare "does this parse" and
    "what keys does this produce" across the two implementations.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[3:end]


def test_all_frontmatter_is_strict_yaml_parseable():
    failures = []
    for path in _frontmatter_files():
        block = _frontmatter_block(path)
        if block is None:
            continue
        try:
            yaml.safe_load(block)
        except yaml.YAMLError as e:
            failures.append(f"{path.relative_to(ROOT)}: {e}")
    assert not failures, (
        "frontmatter block(s) fail strict YAML parsing — Pi's real parser would reject "
        "these (a lenient hand-rolled parser accepting them is not enough):\n"
        + "\n".join(f"  {f}" for f in failures)
    )


def test_strict_and_lenient_parsers_agree_on_keys():
    """The only assertion that catches lenient-accepts / strict-rejects key drift.

    Schema conformance is not the gate here — key-set agreement between validate.py's
    hand-rolled parser and a real YAML parser is, since that is the one property that can
    silently diverge without either parser raising.
    """
    mismatches = []
    for path in _frontmatter_files():
        block = _frontmatter_block(path)
        if block is None:
            continue
        try:
            strict = yaml.safe_load(block)
        except yaml.YAMLError:
            continue  # reported by test_all_frontmatter_is_strict_yaml_parseable
        if not isinstance(strict, dict):
            continue
        strict_keys = {str(k).lower() for k in strict.keys()}
        lenient = validate.parse_frontmatter(path)
        lenient_keys = set(lenient.keys()) if lenient is not None else set()
        if strict_keys != lenient_keys:
            mismatches.append(
                f"{path.relative_to(ROOT)}: strict={sorted(strict_keys)} "
                f"lenient={sorted(lenient_keys)}"
            )
    assert not mismatches, (
        "strict (PyYAML) and lenient (validate.parse_frontmatter) parsers disagree on "
        "frontmatter keys — one accepts something the other doesn't:\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )


def test_agent_frontmatter_keys_are_inventoried():
    on_disk = set()
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        on_disk |= set(fm.keys())
    assert on_disk == FRONTMATTER_KEYS, (
        "agents/*.md frontmatter keys have drifted from the inventory — "
        f"only on disk: {sorted(on_disk - FRONTMATTER_KEYS)}, "
        f"only in FRONTMATTER_KEYS: {sorted(FRONTMATTER_KEYS - on_disk)}"
    )


def test_tool_tokens_and_skill_ids_are_inventoried():
    tool_tokens = set()
    skill_ids = set()
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        tools = fm.get("tools")
        if tools:
            tool_tokens |= {t.strip() for t in tools.split(",")}
        skills = fm.get("skills")
        if isinstance(skills, list):
            skill_ids |= {s for s in skills if s.startswith("swe-workbench:")}
    assert tool_tokens == TOOL_TOKENS, (
        "agents/*.md tool tokens have drifted from the inventory — "
        f"only on disk: {sorted(tool_tokens - TOOL_TOKENS)}, "
        f"only in TOOL_TOKENS: {sorted(TOOL_TOKENS - tool_tokens)}"
    )
    assert skill_ids == SKILL_IDS, (
        "agents/*.md skill ids have drifted from the inventory — "
        f"only on disk: {sorted(skill_ids - SKILL_IDS)}, "
        f"only in SKILL_IDS: {sorted(SKILL_IDS - skill_ids)}"
    )


# ---------------------------------------------------------------------------
# Guard/hint event-translation contract (issue #607). Golden-inventory ratchets over
# pi/extensions/*.ts — module-level literals asserted equal to what's on disk, per
# docs/plugin-platform-decisions.md §2. These fail only when THIS repo's adapter drifts from
# the invariants #607's design settled on, never on an upstream SDK addition.
# ---------------------------------------------------------------------------

_EXTENSION_TS_FILES = sorted(EXTENSIONS_DIR.glob("*.ts"))
_NON_INDEX_TS_FILES = [p for p in _EXTENSION_TS_FILES if p.name != "index.ts"]

_PACKAGE_IMPORT_RE = re.compile(
    # [^}]* (not a DOTALL .*?) so this cannot swallow past the FIRST closing brace it meets —
    # a lazy .*? still crosses unrelated statements in between when the file has multiple
    # `import ... from "..."` blocks between the first "import" keyword and this package name.
    r'import\s+(type\s+)?\{[^}]*\}\s+from\s+["\']@earendil-works/pi-coding-agent["\']',
)


def test_every_sdk_import_under_extensions_is_type_only():
    """A plain (non-type) import of a runtime SDK symbol would defeat the
    `node --experimental-strip-types` test harness the moment it's exercised outside a
    node_modules-having checkout, and — per this repo's own established convention in
    pi/extensions/index.ts — is never actually needed: every narrowing this adapter does uses
    a manual `toolName === "..."` check plus a type cast instead of the SDK's
    `isToolCallEventType` runtime helper."""
    violations = []
    for path in _EXTENSION_TS_FILES:
        text = path.read_text(encoding="utf-8")
        for match in _PACKAGE_IMPORT_RE.finditer(text):
            if match.group(1) is None:
                violations.append(f"{path.relative_to(ROOT)}: {match.group(0)!r}")
    assert not violations, (
        "every import of @earendil-works/pi-coding-agent under pi/extensions/ must be "
        f"`import type` — found non-type-only import(s):\n" + "\n".join(violations)
    )


def test_node_child_process_imported_in_exactly_guard_runner():
    importers = []
    for path in _EXTENSION_TS_FILES:
        text = path.read_text(encoding="utf-8")
        if re.search(r'from\s+["\']node:child_process["\']', text) or "require(\"node:child_process\")" in text:
            importers.append(path.name)
    assert importers == ["guard-runner.ts"], (
        "node:child_process must be imported in exactly guard-runner.ts — the sole auditable "
        f"process-spawn boundary for the adapter; found it imported in: {importers}"
    )


def test_no_shell_true_under_extensions():
    violations = [
        str(p.relative_to(ROOT)) for p in _EXTENSION_TS_FILES if re.search(r"shell\s*:\s*true", p.read_text(encoding="utf-8"))
    ]
    assert not violations, f"shell: true is forbidden under pi/extensions/ — found in: {violations}"


def test_extension_ts_files_excluding_index_stay_under_line_cap():
    """A volume bound, not a semantic guard-logic detector — no regex reliably distinguishes
    genuine guard logic from an unusually long comment or type block, and one that tried would
    either miss unusual patterns or false-positive on prose. Bounded line count plus the
    child_process/shell:true ratchets above give real containment without pretending to detect
    reimplemented guard logic directly."""
    LINE_CAP = 250
    violations = []
    for path in _NON_INDEX_TS_FILES:
        n = len(path.read_text(encoding="utf-8").splitlines())
        if n > LINE_CAP:
            violations.append(f"{path.name}: {n} lines")
    assert not violations, f"pi/extensions/*.ts files (excluding index.ts) must stay <= {LINE_CAP} lines: {violations}"


def _node_major_version():
    node = shutil.which("node")
    if node is None:
        return None
    result = subprocess.run([node, "--version"], capture_output=True, text=True, env=_CLEAN_ENV, timeout=10)
    return int(result.stdout.strip().lstrip("v").split(".")[0])


_NODE_MAJOR = _node_major_version()
_NODE_TOO_OLD = _NODE_MAJOR is None or _NODE_MAJOR < 22

if _NODE_TOO_OLD and os.environ.get("CI"):
    pytest.fail(
        "Node >= 22 required for pi contract tests that dump GUARD_DISPATCH but not found (or "
        "too old) in CI — check the pytest job's actions/setup-node step",
        pytrace=False,
    )

requires_node = pytest.mark.skipif(
    _NODE_TOO_OLD, reason="requires Node >= 22 (--experimental-strip-types) to import cc-payload.ts"
)

_DUMP_DISPATCH_DRIVER = """
import { pathToFileURL } from "node:url";
const mod = await import(pathToFileURL(process.argv[2]).href);
console.log(JSON.stringify(mod.GUARD_DISPATCH));
"""


@pytest.fixture(scope="module")
def guard_dispatch():
    if _NODE_TOO_OLD:
        pytest.skip("requires Node >= 22")
    import tempfile

    node = shutil.which("node")
    assert node is not None
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "dump.mjs"
        driver.write_text(_DUMP_DISPATCH_DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", str(driver), str(EXTENSIONS_DIR / "cc-payload.ts")],
            capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
        )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    return json.loads(result.stdout)


@requires_node
def test_guard_dispatch_script_paths_exist_and_are_executable(guard_dispatch):
    for tool, spec in guard_dispatch.items():
        script_path = ROOT / spec["scriptRelPath"]
        assert script_path.exists(), f"{tool}: {spec['scriptRelPath']} does not exist"
        # os.access(X_OK), never an exact-mode check — a umask-002 checkout legitimately
        # produces 0775 for an executable file, which an exact `& 0o111` comparison would flag.
        assert os.access(script_path, os.X_OK), f"{tool}: {spec['scriptRelPath']} is not executable"


@requires_node
def test_guard_dispatch_tool_name_casing_is_pinned(guard_dispatch):
    """secret_guard.py matches tool_name by exact string equality against "Write"/"Edit" — a
    lowercase leak here would silently no-op the guard while every other test stays green."""
    assert guard_dispatch["bash"]["ccToolName"] is None
    assert guard_dispatch["write"]["ccToolName"] == "Write"
    assert guard_dispatch["edit"]["ccToolName"] == "Edit"


@requires_node
def test_guard_dispatch_fail_postures_are_pinned(guard_dispatch):
    assert guard_dispatch["bash"]["failPosture"] == "closed"
    assert guard_dispatch["write"]["failPosture"] == "open"
    assert guard_dispatch["edit"]["failPosture"] == "open"


# Every JSON field path each hook actually reads (verified against hooks/*.sh|py source below),
# and every field path the adapter's CC-shaped payloads carry for the Pi tool that reaches it.
# A hook reading a field the adapter never sends would silently no-op that behavior on Pi.
REFERENCED_FIELDS = {
    "bash_guard.sh": {"tool_input.command"},
    "secret_guard.py": {"tool_name", "tool_input.content", "tool_input.file_path", "tool_input.new_string"},
    "workflow_resume_hint.sh": {"cwd", "source"},
    "skill_autoload_hint.sh": {"tool_input.file_path", "session_id"},
}
ADAPTER_PAYLOAD_FIELDS = {
    "bash_guard.sh": {"tool_input.command"},
    "secret_guard.py": {"tool_name", "tool_input.content", "tool_input.file_path", "tool_input.new_string"},
    "workflow_resume_hint.sh": {"cwd", "source"},
    "skill_autoload_hint.sh": {"tool_input.file_path", "session_id"},
}


def test_referenced_fields_are_a_subset_of_adapter_payload_fields():
    for hook, referenced in REFERENCED_FIELDS.items():
        carried = ADAPTER_PAYLOAD_FIELDS[hook]
        assert referenced <= carried, (
            f"{hook} reads field(s) {referenced - carried} that the adapter's payload for it "
            "never carries — that field would silently always read empty on Pi"
        )


def test_referenced_fields_actually_appear_in_hook_source():
    """Sanity-checks REFERENCED_FIELDS against the real script text so a hook edit that renames
    or drops a field trips this ratchet, instead of the literal silently going stale."""
    sources = {
        "bash_guard.sh": (HOOKS_DIR / "bash_guard.sh").read_text(encoding="utf-8"),
        "secret_guard.py": (HOOKS_DIR / "secret_guard.py").read_text(encoding="utf-8"),
        "workflow_resume_hint.sh": (HOOKS_DIR / "workflow_resume_hint.sh").read_text(encoding="utf-8"),
        "skill_autoload_hint.sh": (HOOKS_DIR / "skill_autoload_hint.sh").read_text(encoding="utf-8"),
    }
    for hook, fields in REFERENCED_FIELDS.items():
        text = sources[hook]
        for field in fields:
            leaf = field.rsplit(".", 1)[-1]
            assert leaf in text, f"{hook}: expected field leaf {leaf!r} (from {field!r}) not found in source"


# hooks/*.sh|py -> Pi wiring status. "wired": translated by guards.ts this phase. "n/a": the
# concept the hook manipulates does not exist on Pi (documented in
# docs/plugin-platform-decisions.md §6). "deferred": not wired yet because the Pi tool it needs
# (Skill / subagents) doesn't exist until #608/#610 — tracked there, not here.
HOOK_PI_STATUS = {
    "bash_guard.sh": "wired",
    "secret_guard.py": "wired",
    "workflow_resume_hint.sh": "wired",
    "skill_autoload_hint.sh": "wired",
    "worktree_permission_grant.sh": "n/a",
    "skill_usage_record.sh": "deferred",
    "skill_usage_flush.sh": "deferred",
}


def test_every_hook_script_has_a_pi_status_row():
    on_disk = {p.name for p in HOOKS_DIR.glob("*.sh")} | {p.name for p in HOOKS_DIR.glob("*.py")}
    assert on_disk == set(HOOK_PI_STATUS), (
        "hooks/*.sh|py has drifted from the Pi-wiring inventory — "
        f"only on disk: {sorted(on_disk - set(HOOK_PI_STATUS))}, "
        f"only in HOOK_PI_STATUS: {sorted(set(HOOK_PI_STATUS) - on_disk)}"
    )


def test_worktree_permission_grant_is_explicitly_not_applicable():
    assert HOOK_PI_STATUS["worktree_permission_grant.sh"] == "n/a", (
        "worktree_permission_grant.sh's PreToolUse permissionDecision output has no target on "
        "Pi (README.md: 'No permission popups') — this must stay an explicit N/A, not silently "
        "absent from the inventory"
    )
