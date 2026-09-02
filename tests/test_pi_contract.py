"""Contract tests for the swe-workbench <-> Pi Coding Agent frontmatter boundary (issue #605)
and, below, the guard/hint event-translation boundary.

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
docs/decisions-ci-validation.md §1, rather than a closed-form schema.
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
PI_EXTENSIONS_INDEX = ROOT / "pi" / "extensions" / "index.ts"


_PI_YAML_CORE_SCALAR_TAGS = frozenset(
    {
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:timestamp",
    }
)


class PiCompatibleYamlLoader(yaml.SafeLoader):
    yaml_implicit_resolvers = {
        initial: [
            resolver
            for resolver in resolvers
            if resolver[0] not in _PI_YAML_CORE_SCALAR_TAGS
        ]
        for initial, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


PiCompatibleYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
PiCompatibleYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^(?:0o[0-7]+|[-+]?[0-9]+|0x[0-9a-fA-F]+)$"),
    list("+-0123456789"),
)
PiCompatibleYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^(?:[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)|"
        r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)[eE][-+]?[0-9]+|"
        r"[-+]?(?:\.[0-9]+|[0-9]+\.[0-9]*))$"
    ),
    list("+-.0123456789"),
)

# Transcribed byte-for-byte from `substituteArgs`'s replacement regex in
# @earendil-works/pi-coding-agent@0.84.3's dist/core/prompt-templates.js (also present,
# unchanged, on that package's `src/core/prompt-templates.ts` at the same pin). Re-diff this
# against the installed package (`grep -n substituteArgs node_modules/@earendil-works/
# pi-coding-agent/dist/core/prompt-templates.js`) whenever the root `package.json`'s
# peerDependencies bump changes the pin — the alternation is what silently eats `$0`:
# the final `\$(...|\d+)` branch matches any `$<digits>`, including `$0`, and the
# matched substring is replaced with `args[-1] ?? ""` — i.e. the empty string, since no
# template is ever invoked with a 0th positional arg. `$(0)` is the portable escape: it is
# valid awk (an expression field reference `$(0)` means the same thing as `$0`) but does not
# match this regex, so Pi's substitution passes it through untouched.
PI_SUBSTITUTE_ARGS_RE = re.compile(
    r"\$\{(\d+|ARGUMENTS|@):-([^}]*)\}|\$\{@:(\d+)(?::(\d+))?\}|\$(ARGUMENTS|@|\d+)"
)

# The complete key vocabulary agents/*.md frontmatter uses today. A new key (e.g. a future
# Phase 7 `pi:` override block) must be added here deliberately, not discovered by CI red.
FRONTMATTER_KEYS = {"name", "description", "model", "effort", "tools", "skills"}

# Union of every agents/*.md `model:` value. Mirrors model-policy.ts's KNOWN_MODEL_TIERS — a new
# tier value on disk not also added to that module's MODEL_POLICY would resolve to nothing
# for every provider, silently falling back to the parent's model with zero signal.
MODEL_TIERS = {"haiku", "sonnet", "opus"}

# Union of every agents/*.md `effort:` value — not the full KNOWN_EFFORTS type space, just what's
# actually on disk today (every agent uses its tier's DEFAULT_TIER_EFFORT). Mirrors MODEL_TIERS:
# a new effort value on disk not also covered by MODEL_POLICY's exhaustive per-cell map would be
# unreachable, since every cell already covers all 5 known efforts by construction.
EFFORTS = {"high", "xhigh"}

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


def _body_after_frontmatter(path):
    """Return (body, body_start_line): the body Pi's own parseFrontmatter would hand to
    substituteArgs, and the 1-indexed line in the original file where that body's first
    character lives (post-normalization, pre-strip) — so callers can report accurate line
    numbers for matches found inside `body`, which has leading/trailing whitespace stripped
    and so cannot be offset from directly by counting its own newlines alone.

    Mirrors dist/utils/frontmatter.js's extractFrontmatter exactly (source at
    @earendil-works/pi-coding-agent@0.84.3): normalize newlines ('\\r\\n' then '\\r' -> '\\n',
    same as Pi's normalizeNewlines) before any offset math, find the closing '---' via
    indexOf from index 3, slice from 4 chars past that match, then strip(). Do NOT reuse
    _frontmatter_block's delimiter logic here — it requires an exact '\\n---\\n' match and
    never trims, which leaves an extra leading '\\n' in the body for every file using the
    standard '---\\n\\n<body>' shape.
    """
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---"):
        return text, 1
    end = text.find("\n---", 3)
    if end == -1:
        return text, 1
    raw_body = text[end + 4 :]
    stripped = raw_body.strip()
    leading_offset = raw_body.index(stripped) if stripped else len(raw_body)
    body_start_line = text.count("\n", 0, end + 4 + leading_offset) + 1
    return stripped, body_start_line


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


def test_strict_skill_descriptions_follow_pi_contract():
    failures = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        block = _frontmatter_block(path)
        try:
            frontmatter = yaml.load(block, Loader=PiCompatibleYamlLoader) if block is not None else None
        except yaml.YAMLError as error:
            failures.append(f"{path.relative_to(ROOT)}: {error}")
            continue
        description = frontmatter.get("description") if isinstance(frontmatter, dict) else None
        if not isinstance(description, str) or not description.strip():
            failures.append(f"{path.relative_to(ROOT)}: description must be a nonblank string")
            continue
        description_length = len(description.encode("utf-16-le", "surrogatepass")) // 2
        if description_length > 1024:
            failures.append(
                f"{path.relative_to(ROOT)}: description exceeds 1024 UTF-16 units "
                f"({description_length})"
            )
    assert not failures, "Pi skill description contract violations:\n" + "\n".join(failures)


@pytest.mark.parametrize("description", ["0b101", "1_000", "2026-08-22", "12:34:56"])
def test_pi_loader_keeps_pi_string_scalars_as_strings(description):
    frontmatter = yaml.load(f"description: {description}\n", Loader=PiCompatibleYamlLoader)

    assert frontmatter["description"] == description


@pytest.mark.parametrize("description", ["0o755", ".nan"])
def test_pi_loader_resolves_pi_non_string_scalars(description):
    frontmatter = yaml.load(f"description: {description}\n", Loader=PiCompatibleYamlLoader)

    assert not isinstance(frontmatter["description"], str)


@pytest.mark.parametrize("description", ["yes", "no", "on", "off"])
def test_strict_skill_descriptions_accept_pi_boolean_like_strings(monkeypatch, tmp_path, description):
    skills_dir = tmp_path / "skills"
    skill_md = skills_dir / "my-skill" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text(
        f"---\nname: my-skill\ndescription: {description}\n---\n", encoding="utf-8"
    )
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "SKILLS_DIR", skills_dir)

    test_strict_skill_descriptions_follow_pi_contract()


@pytest.mark.parametrize("description", ["true", "false"])
def test_strict_skill_descriptions_reject_pi_boolean_scalars(monkeypatch, tmp_path, description):
    skills_dir = tmp_path / "skills"
    skill_md = skills_dir / "my-skill" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text(
        f"---\nname: my-skill\ndescription: {description}\n---\n", encoding="utf-8"
    )
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "SKILLS_DIR", skills_dir)

    with pytest.raises(AssertionError, match="description must be a nonblank string"):
        test_strict_skill_descriptions_follow_pi_contract()


def test_strict_skill_descriptions_accept_unpaired_yaml_surrogates(monkeypatch, tmp_path):
    skills_dir = tmp_path / "skills"
    skill_md = skills_dir / "my-skill" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text(
        '---\nname: my-skill\ndescription: "\\uD800"\n---\n', encoding="utf-8"
    )
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "SKILLS_DIR", skills_dir)

    try:
        test_strict_skill_descriptions_follow_pi_contract()
    except UnicodeEncodeError as error:
        pytest.fail(f"Pi-valid unpaired surrogate raised {error}")


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


def test_model_tiers_are_inventoried():
    tiers = set()
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        model = fm.get("model")
        if model:
            tiers.add(model)
    assert tiers == MODEL_TIERS, (
        "agents/*.md model tiers have drifted from the inventory — "
        f"only on disk: {sorted(tiers - MODEL_TIERS)}, "
        f"only in MODEL_TIERS: {sorted(MODEL_TIERS - tiers)}. A new tier value must also be "
        "added to model-policy.ts's KNOWN_MODEL_TIERS and MODEL_POLICY, or it silently "
        "resolves to nothing for every provider."
    )


def test_efforts_are_inventoried():
    efforts = set()
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fm = validate.parse_frontmatter(path)
        assert fm is not None, f"{path} has no parseable frontmatter"
        effort = fm.get("effort")
        if effort:
            efforts.add(effort)
    assert efforts == EFFORTS, (
        "agents/*.md efforts have drifted from the inventory — "
        f"only on disk: {sorted(efforts - EFFORTS)}, "
        f"only in EFFORTS: {sorted(EFFORTS - efforts)}. A new effort value must also be "
        "added to model-policy.ts's KNOWN_EFFORTS, or it silently resolves to nothing for "
        "every provider."
    )


# ---------------------------------------------------------------------------
# Guard/hint event-translation contract. Golden-inventory ratchets over
# pi/extensions/*.ts — module-level literals asserted equal to what's on disk, per
# docs/decisions-ci-validation.md §1.
# ---------------------------------------------------------------------------

_EXTENSION_TS_FILES = sorted(EXTENSIONS_DIR.glob("*.ts"))
_NON_INDEX_TS_FILES = [p for p in _EXTENSION_TS_FILES if p.name != "index.ts"]

_IMPORT_FROM_RE = re.compile(
    # [^}]* (not a DOTALL .*?) so this cannot swallow past the FIRST closing brace it meets —
    # a lazy .*? still crosses unrelated statements in between when the file has multiple
    # `import ... from "..."` blocks in one file. The `\*\s+as\s+\S+` alternative is required
    # separately from `\S+` — for `import * as Type from "typebox"`, `\S+` greedily consumes
    # only `*` (stops at the following space), and then `\s+from` fails to match "as Type
    # from...", so the WHOLE alternation fails at that position with no backtrack into a
    # shorter match; without this explicit alternative a namespace import silently never
    # matches at all, rather than merely mis-capturing.
    r'import\s+(type\s+)?(?:\{[^}]*\}|\*\s+as\s+\S+|\S+)\s+from\s+["\']([^"\']+)["\']',
)

# Bare side-effect imports (`import "polyfill"`) have no `from` clause at all, so they never
# match _IMPORT_FROM_RE regardless of alternation — a structurally separate pattern, not a gap
# in the one above.
_IMPORT_SIDE_EFFECT_RE = re.compile(r'import\s+(type\s+)?["\']([^"\']+)["\']')


def test_no_extension_file_has_a_value_import_of_a_bare_specifier():
    """Every @earendil-works/pi-coding-agent import here is `import type` (this adapter narrows
    tool events with a manual `toolName === "..."` check plus a cast, never the SDK's
    `isToolCallEventType` runtime helper) — but the real rationale is broader than that one
    package: tests/test_pi_extension.py and test_pi_contract.py drive these files under
    `node --experimental-strip-types`, which has no bundler, no jiti, and no node_modules alias
    resolution beyond plain Node module resolution. A value import of ANY bare specifier (a
    package name, not `node:*` or a relative `./*.ts` path) breaks that harness the same way a
    value import of the SDK would — e.g. `import { Type } from "typebox"` would sail through the
    old package-name-hardcoded check while still breaking every pytest run. Zero violations
    today; this is a pure strengthening, not a behavior change."""
    violations = []
    for path in _EXTENSION_TS_FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in (_IMPORT_FROM_RE, _IMPORT_SIDE_EFFECT_RE):
            for match in pattern.finditer(text):
                is_type_only, specifier = match.group(1), match.group(2)
                if is_type_only is not None:
                    continue
                if specifier.startswith("node:") or specifier.startswith("./") or specifier.startswith("../"):
                    continue
                violations.append(f"{path.relative_to(ROOT)}: {match.group(0)!r}")
    assert not violations, (
        "pi/extensions/*.ts must not value-import any bare specifier (only `node:*` or a "
        f"relative `./*.ts` import may be a value import) — found:\n" + "\n".join(violations)
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

function flatten(obj, prefix) {
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) out.push(...flatten(v, path));
    else out.push(path);
  }
  return out;
}

const bashEvent = { input: { command: "x" } };
const writeEvent = { input: { content: "x", path: "y" } };
const editEvent = { input: { path: "y", edits: [{ oldText: "a", newText: "b" }] } };

const fields = {
  "bash_guard.sh": flatten(mod.bashPayload(bashEvent)),
  "secret_guard.py": [
    ...flatten(mod.writePayload(writeEvent)),
    ...flatten(mod.editPayloads(editEvent)[0]),
  ],
  "workflow_resume_hint.sh": flatten(mod.resumeHintPayload("cwd-value", "startup")),
  "memory_hint.sh": flatten(mod.memoryHintPayload("cwd-value", "pi")),
  "skill_autoload_hint.sh": flatten(mod.skillHintPayload("path-value", "session-value")),
};

console.log(JSON.stringify({ dispatch: mod.GUARD_DISPATCH, fields }));
"""


@pytest.fixture(scope="module")
def cc_payload_dump():
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


@pytest.fixture(scope="module")
def guard_dispatch(cc_payload_dump):
    return cc_payload_dump["dispatch"]


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


# Every JSON field path each hook actually reads, verified against hooks/*.sh|py source below.
REFERENCED_FIELDS = {
    "bash_guard.sh": {"tool_input.command"},
    "secret_guard.py": {"tool_name", "tool_input.content", "tool_input.file_path", "tool_input.new_string"},
    "workflow_resume_hint.sh": {"cwd", "source"},
    "memory_hint.sh": {"cwd", "harness"},
    "skill_autoload_hint.sh": {"tool_input.file_path", "session_id"},
}


@requires_node
def test_referenced_fields_are_a_subset_of_adapter_payload_fields(cc_payload_dump):
    for hook, referenced in REFERENCED_FIELDS.items():
        carried = set(cc_payload_dump["fields"][hook])
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
        "memory_hint.sh": (HOOKS_DIR / "memory_hint.sh").read_text(encoding="utf-8"),
        "skill_autoload_hint.sh": (HOOKS_DIR / "skill_autoload_hint.sh").read_text(encoding="utf-8"),
    }
    for hook, fields in REFERENCED_FIELDS.items():
        text = sources[hook]
        for field in fields:
            leaf = field.rsplit(".", 1)[-1]
            assert leaf in text, f"{hook}: expected field leaf {leaf!r} (from {field!r}) not found in source"


# hooks/*.sh|py -> Pi wiring status. "wired": translated by guards.ts this phase. "n/a": the
# concept the hook manipulates either does not exist on Pi (documented in
# docs/decisions-pi-port.md §1) or is implemented natively by a Pi extension module
# instead of spawning the Claude hook script (documented in docs/decisions-cross-harness.md §1 for handoff_guard.py).
# "deferred": not wired, but the missing Pi capability is expected to arrive and unblock wiring
# — currently no rows sit in this bucket.
HOOK_PI_STATUS = {
    "bash_guard.sh": "wired",
    "secret_guard.py": "wired",
    "handoff_guard.py": "n/a",
    "workflow_resume_hint.sh": "wired",
    "memory_hint.sh": "wired",
    "skill_autoload_hint.sh": "wired",
    "worktree_permission_grant.sh": "n/a",
    "skill_usage_record.sh": "n/a",
    "skill_usage_flush.sh": "n/a",
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


def test_handoff_guard_is_explicitly_not_applicable():
    assert HOOK_PI_STATUS["handoff_guard.py"] == "n/a", (
        "Pi-side handoff ownership and quota recovery are implemented natively in "
        "pi/extensions/handoff.ts (tool_call + after_provider_response); the Claude hook script "
        "is Claude-payload-shaped and is never spawned on Pi. This must stay an explicit N/A "
        "row, not silently absent from the inventory"
    )


@pytest.mark.parametrize("hook", ["skill_usage_record.sh", "skill_usage_flush.sh"])
def test_skill_usage_hooks_are_explicitly_not_applicable(hook):
    assert HOOK_PI_STATUS[hook] == "n/a", (
        f"{hook} measures runtime Skill invocations inside a dispatched subagent — an observable "
        "Pi structurally lacks: no Skill tool exists in any Pi process, dispatched children get "
        "skill bodies preloaded into their system prompt (pi/extensions/agent-spec.ts), and "
        "child pi.exec processes expose no events to the parent. This must stay an explicit "
        "N/A row (docs/decisions-pi-port.md §1, §4), not silently re-deferred on a "
        "capability-arrival rationale"
    )


def test_no_pi_argument_substitution_hazard_in_commands():
    """Every $-token Pi's substituteArgs regex would match, across commands/*.md and
    shared/**/*.md, must be exactly `$ARGUMENTS` — the one substitution swe-workbench's
    commands are written to expect.

    This allowlists the single legal token rather than blocklisting known-bad ones: `$@`,
    `$1`, `${2:-x}`, `${@:1:2}` all trip this without being enumerated, and so does any
    alternation Pi adds to the regex later. `$0` is the hazard this guard was
    written for — Pi replaces it with the empty string, silently corrupting any awk script
    that uses `$0` as its whole-record variable. The fix is `$(0)`, valid in every awk and
    invisible to this regex; see the comment above `PI_SUBSTITUTE_ARGS_RE`.
    """
    violations = []
    paths = sorted(COMMANDS_DIR.glob("*.md")) + sorted(SHARED_DIR.rglob("*.md"))
    for path in paths:
        body, body_start_line = _body_after_frontmatter(path)
        for match in PI_SUBSTITUTE_ARGS_RE.finditer(body):
            if match.group(0) != "$ARGUMENTS":
                line_no = body_start_line + body.count("\n", 0, match.start())
                violations.append(f"{path.relative_to(ROOT)}:{line_no}: {match.group(0)!r}")
    assert not violations, (
        "Pi's substituteArgs (dist/core/prompt-templates.js, "
        "@earendil-works/pi-coding-agent@0.84.3) would rewrite these tokens — every "
        "alternative it matches other than literal `$ARGUMENTS` is replaced with the "
        "matched positional arg or, if unset, the empty string, silently corrupting the "
        "command body when swe-workbench's own commands are loaded as Pi prompt templates. "
        "Use `$(0)` (or otherwise avoid a bare `$<digits>`/`$@`/`${...}` token) instead:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_pi_extension_wires_commands_as_prompt_paths():
    """Smoke check only — flagged honestly as text-not-behaviour.

    tests/test_pi_extension.py's test_resources_discover_returns_exactly_the_skills_and_commands_dirs
    already exercises this wiring behaviourally (it drives the real extension through Node and
    asserts exact equality on the resources_discover result) — but that test is `@requires_node`
    and skips locally on Node < 22, and CI's Node pin could itself be removed or narrowed by a
    future change to .github/workflows/pr.yml without this repo's own tests objecting. This
    assertion has no such dependency: it only proves the wiring line is present in source, so the
    `promptPaths: [join(root, "commands")]` wiring in pi/extensions/index.ts keeps *some* coverage
    — text, not behaviour — even in a pytest-only run where Node isn't available.
    """
    text = PI_EXTENSIONS_INDEX.read_text(encoding="utf-8")
    assert "promptPaths" in text
    assert 'join(root, "commands")' in text


# ---------------------------------------------------------------------------
# ask_user_question schema-as-data ratchet. Pins pi/extensions/ask-user.ts's parameters to a
# plain JSON-Schema object literal — never a TypeBox value import — since
# @earendil-works/pi-ai's constrained-sampling.js (getJsonSchemaToolParameters, ~line 111 as of
# pi-coding-agent@0.84.3) returns `tool.parameters` verbatim to the provider and nothing on the
# registration path (dist/core/tools/tool-definition-wrapper.js) runs TypeBox's
# Value.Check/Compile against it. Re-diff that citation directly if this test ever needs to
# change: `grep -n getJsonSchemaToolParameters` against the installed pi-ai package.
# ---------------------------------------------------------------------------

_ASK_USER_SCHEMA_DRIVER = """
import { pathToFileURL } from "node:url";

const mod = await import(pathToFileURL(process.argv[2]).href);
let registered;
const stubPi = { registerTool(tool) { registered = tool; } };
mod.registerAskUser(stubPi);
console.log(JSON.stringify({ parameters: registered.parameters, hasPromptSnippet: typeof registered.promptSnippet === "string" && registered.promptSnippet.length > 0 }));
"""

ASK_USER_TS = EXTENSIONS_DIR / "ask-user.ts"


@requires_node
def test_ask_user_question_parameters_is_a_plain_json_schema_object():
    node = shutil.which("node")
    assert node is not None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "ask-user-schema-dump.mjs"
        driver.write_text(_ASK_USER_SCHEMA_DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", str(driver), str(ASK_USER_TS)],
            capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
        )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    dumped = json.loads(result.stdout)
    parameters = dumped["parameters"]
    assert isinstance(parameters, dict), "parameters must serialize as a plain JSON object"
    assert parameters.get("type") == "object"
    assert "questions" in parameters.get("properties", {})
    assert dumped["hasPromptSnippet"] is True, (
        "custom tools are omitted from the system prompt's Available tools section without a "
        "promptSnippet — ask_user_question must always carry one"
    )


def test_ask_user_ts_has_no_typebox_import():
    text = ASK_USER_TS.read_text(encoding="utf-8")
    assert '"typebox"' not in text and "'typebox'" not in text, (
        "ask-user.ts must derive its parameter type from the SDK's own ToolDefinition re-export, "
        "never by importing typebox directly — see the file's own module docstring for why"
    )


def test_ask_user_prompt_guidelines_offer_free_text_other():
    """The guideline forbidding a free-text "Other" is retracted alongside the
    feature — otherwise the model is instructed not to use the row the tool just added."""
    text = ASK_USER_TS.read_text(encoding="utf-8")
    assert "Never fabricate" not in text, (
        'the "Never fabricate a free-text Other option" guideline must be removed once the '
        "tool appends an Other row itself"
    )
    assert "appended automatically" in text, (
        "the replacement guideline must tell the caller the Other row is automatic"
    )


# ---------------------------------------------------------------------------
# task-tool dispatcher (agent-spec.ts + subagent.ts). Layering boundary, translation-table
# exhaustiveness, and a live zero-LLM probe of the --exclude-tools recursion guard.
# ---------------------------------------------------------------------------

AGENT_SPEC_TS = EXTENSIONS_DIR / "agent-spec.ts"
MODEL_POLICY_TS = EXTENSIONS_DIR / "model-policy.ts"
SUBAGENT_TS = EXTENSIONS_DIR / "subagent.ts"
BIN_SCRIPTS_TS = EXTENSIONS_DIR / "bin-scripts.ts"


def test_agent_spec_ts_never_references_pi():
    """agent-spec.ts is the domain layer for the task tool: it may read this plugin's own
    agents/*.md and skills/*/SKILL.md files, but must never reference the Pi SDK or spawn a
    process — that's subagent.ts's job. Stricter than the generic bare-specifier test above (which
    permits `import type`): this scans the whole file text, so it would also catch a stray
    reference in a comment or a future non-import usage, not just an import statement."""
    text = AGENT_SPEC_TS.read_text(encoding="utf-8")
    assert "pi-coding-agent" not in text, "agent-spec.ts must not reference the Pi SDK at all"
    assert "node:child_process" not in text, "agent-spec.ts must not spawn processes — that is subagent.ts's job"


def test_model_policy_ts_never_references_pi():
    """model-policy.ts is the domain layer for dispatch-policy resolution: pure data and pure
    functions, no Pi SDK reference and no process spawning — subagent.ts owns querying
    ctx.modelRegistry and everything else that touches Pi. Same posture, same test shape, as
    test_agent_spec_ts_never_references_pi above."""
    text = MODEL_POLICY_TS.read_text(encoding="utf-8")
    assert "pi-coding-agent" not in text, "model-policy.ts must not reference the Pi SDK at all"
    assert "node:child_process" not in text, "model-policy.ts must not spawn processes — that is subagent.ts's job"


def test_bin_scripts_ts_never_references_pi():
    """bin-scripts.ts is the domain layer for the generated bin/ inventory preamble section:
    pure text generation from node:fs/node:path only, no Pi SDK reference and no process
    spawning — index.ts owns composing it into the system prompt. Same posture, same test
    shape, as test_agent_spec_ts_never_references_pi above."""
    text = BIN_SCRIPTS_TS.read_text(encoding="utf-8")
    assert "pi-coding-agent" not in text, "bin-scripts.ts must not reference the Pi SDK at all"
    assert "node:child_process" not in text, "bin-scripts.ts must not spawn processes — that is index.ts's job"


_TRANSLATION_TABLE_DRIVER = """
import { pathToFileURL } from "node:url";
const [, , toolVocabPath, agentSpecPath] = process.argv;
const toolVocab = await import(pathToFileURL(toolVocabPath).href);
const agentSpec = await import(pathToFileURL(agentSpecPath).href);
console.log(JSON.stringify({
  renameKeys: toolVocab.RENAME_TABLE.map(([cc]) => cc),
  dropTokens: [...agentSpec.DROP_TOKENS],
}));
"""


@requires_node
def test_task_tool_translation_table_is_exhaustive_over_tool_tokens():
    """Every token in TOOL_TOKENS (the live inventory of agents/*.md `tools:` values) must have
    a mapping — via RENAME_TABLE (rename) or DROP_TOKENS (drop) — so a future 8th/9th tool token
    can't silently fall through translateToolTokens un-mapped. The reverse direction is checked
    too, but with one documented exception: RENAME_TABLE carries `LS` for tool-vocab.ts's general
    CC->Pi prose even though no agent's `tools:` frontmatter currently grants LS — a real Pi
    rename target, not drift, so it is the one allowed extra rather than asserted away."""
    import tempfile

    node = shutil.which("node")
    assert node is not None
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "translation-table-dump.mjs"
        driver.write_text(_TRANSLATION_TABLE_DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", str(driver), str(EXTENSIONS_DIR / "tool-vocab.ts"), str(AGENT_SPEC_TS)],
            capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
        )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    dumped = json.loads(result.stdout)
    mapped = set(dumped["renameKeys"]) | set(dumped["dropTokens"])

    missing = TOOL_TOKENS - mapped
    assert not missing, f"TOOL_TOKENS not covered by RENAME_TABLE/DROP_TOKENS: {sorted(missing)}"

    extra = mapped - TOOL_TOKENS
    assert extra == {"LS"}, (
        "RENAME_TABLE/DROP_TOKENS carries tokens beyond agents/*.md's live TOOL_TOKENS vocabulary "
        f"other than the known LS entry (see this test's docstring): {sorted(extra)}"
    )


_REAL_AGENTS_PARSE_DRIVER = """
import { pathToFileURL } from "node:url";
const [, , agentSpecPath, root] = process.argv;
const mod = await import(pathToFileURL(agentSpecPath).href);

const out = {};
for (const name of mod.listAgentNames(root)) {
  try {
    const spec = mod.readAgentSpec(root, name);
    const translated = mod.translateToolTokens(spec.tools);
    out[name] = { ok: true, toolCount: translated.length };
  } catch (err) {
    out[name] = { ok: false, message: String(err && err.message) };
  }
}
console.log(JSON.stringify(out));
"""


@requires_node
def test_real_agents_parse_and_translate_without_throwing():
    """Drives the REAL hand-rolled TS parser (readAgentSpec/translateToolTokens) against every
    actual agents/*.md file on disk — not the synthetic fixtures test_pi_extension.py's parser
    tests use, and not validate.py's separate lenient Python parser (which the exhaustiveness
    ratchets above cross-check against instead of the TS one). A frontmatter edit that's valid
    under the Python parser's rules but breaks an assumption the TS regex parser makes (e.g. a
    block-style `tools:` sequence instead of the assumed inline comma string) would otherwise
    stay CI-green and only surface as a runtime throw the first time that agent is actually
    dispatched via `task` — the exact 'frontmatter drift should fail CI, not silently break at
    dispatch time' failure mode this repo's Pi port is designed to avoid."""
    import tempfile

    node = shutil.which("node")
    assert node is not None
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "real-agents-parse-dump.mjs"
        driver.write_text(_REAL_AGENTS_PARSE_DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", str(driver), str(AGENT_SPEC_TS), str(ROOT)],
            capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
        )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    dumped = json.loads(result.stdout)
    assert dumped, "no agents/*.md files were discovered — listAgentNames or ROOT is likely wrong"
    failures = {name: r["message"] for name, r in dumped.items() if not r["ok"]}
    assert not failures, f"real agents/*.md files failed to parse/translate via the TS parser: {failures}"


_FULL_KNOWN_EFFORTS = {"low", "medium", "high", "xhigh", "max"}

_MODEL_POLICY_DUMP_DRIVER = """
import { pathToFileURL } from "node:url";
const mod = await import(pathToFileURL(process.argv[2]).href);
console.log(JSON.stringify({
  knownTiers: mod.KNOWN_MODEL_TIERS,
  knownEfforts: mod.KNOWN_EFFORTS,
  supportedProviders: mod.SUPPORTED_PROVIDERS,
  defaultTierEffort: mod.DEFAULT_TIER_EFFORT,
  policy: mod.MODEL_POLICY,
}));
"""


@pytest.fixture(scope="module")
def model_policy_dump(tmp_path_factory):
    if _NODE_TOO_OLD:
        pytest.skip("requires Node >= 22")
    driver = tmp_path_factory.mktemp("pi-model-policy-dump") / "dump.mjs"
    driver.write_text(_MODEL_POLICY_DUMP_DRIVER, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(MODEL_POLICY_TS)],
        capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    return json.loads(result.stdout)


@requires_node
def test_model_policy_is_exhaustive_over_known_tiers_and_efforts(model_policy_dump):
    """model-policy.ts's own KNOWN_MODEL_TIERS must equal the live MODEL_TIERS ratchet,
    KNOWN_EFFORTS must equal the full 5-value portable-effort vocabulary, and MODEL_POLICY must
    cover all 3 providers x 3 tiers x 5 efforts with no gap — an uncovered cell would silently
    resolve to undefined (parent-model fallback) for that cell only, which is easy to miss
    without an exhaustiveness check."""
    assert set(model_policy_dump["knownTiers"]) == MODEL_TIERS, (
        f"model-policy.ts's KNOWN_MODEL_TIERS ({sorted(model_policy_dump['knownTiers'])}) has "
        f"drifted from the live agents/*.md inventory ({sorted(MODEL_TIERS)})"
    )
    assert set(model_policy_dump["knownEfforts"]) == _FULL_KNOWN_EFFORTS, (
        f"model-policy.ts's KNOWN_EFFORTS ({sorted(model_policy_dump['knownEfforts'])}) has "
        f"drifted from the full portable-effort vocabulary ({sorted(_FULL_KNOWN_EFFORTS)})"
    )
    assert set(model_policy_dump["supportedProviders"]) == set(PROVIDER_DATA_FILES), (
        f"model-policy.ts's SUPPORTED_PROVIDERS ({sorted(model_policy_dump['supportedProviders'])}) "
        f"has drifted from this test's PROVIDER_DATA_FILES inventory ({sorted(PROVIDER_DATA_FILES)})"
    )
    for provider, tiers in model_policy_dump["policy"].items():
        assert set(tiers) == MODEL_TIERS, (
            f"MODEL_POLICY[{provider!r}] covers {sorted(tiers)}, missing "
            f"{sorted(MODEL_TIERS - set(tiers))} — an uncovered tier silently falls back to the "
            "parent's model for that provider only"
        )
        for tier, cell in tiers.items():
            thinking_keys = set(cell["thinking"])
            assert thinking_keys == _FULL_KNOWN_EFFORTS, (
                f"MODEL_POLICY[{provider!r}][{tier!r}].thinking covers {sorted(thinking_keys)}, "
                f"missing {sorted(_FULL_KNOWN_EFFORTS - thinking_keys)} — an uncovered effort "
                "silently resolves to undefined thinking for that cell only"
            )


# The ticket's 3x3 default matrix (docs/cost-tiers.md's "On the Pi Coding Agent" table),
# reproduced by feeding DEFAULT_TIER_EFFORT[tier] through MODEL_POLICY[provider][tier].thinking —
# this is the one source of truth the matrix is asserted against, not a second hand-copied table.
_TICKET_DEFAULT_MATRIX = {
    "anthropic": {
        "opus": ("claude-opus-5", "high"),
        "sonnet": ("claude-sonnet-5", "xhigh"),
        "haiku": ("claude-haiku-4-5", "high"),
    },
    "openai-codex": {
        "opus": ("gpt-5.6-sol", "high"),
        "sonnet": ("gpt-5.6-terra", "xhigh"),
        "haiku": ("gpt-5.6-luna", "high"),
    },
    "zai": {
        "opus": ("glm-5.3", "max"),
        "sonnet": ("glm-5.3", "high"),
        "haiku": ("glm-5.2-highspeed", "high"),
    },
}


@requires_node
def test_default_tier_effort_reproduces_ticket_matrix(model_policy_dump):
    default_effort = model_policy_dump["defaultTierEffort"]
    for provider, tiers in _TICKET_DEFAULT_MATRIX.items():
        for tier, (model_id, thinking) in tiers.items():
            cell = model_policy_dump["policy"][provider][tier]
            effort = default_effort[tier]
            assert cell["model"] == model_id, (
                f"MODEL_POLICY[{provider!r}][{tier!r}].model: expected {model_id!r}, got {cell['model']!r}"
            )
            assert cell["thinking"][effort] == thinking, (
                f"MODEL_POLICY[{provider!r}][{tier!r}].thinking[{effort!r}]: expected {thinking!r}, "
                f"got {cell['thinking'][effort]!r}"
            )


@requires_node
def test_zai_thinking_tables_are_monotone_and_gapless_across_all_efforts(model_policy_dump):
    """Full-table pin for all three zai cells, not just the two ticket-pinned default-effort
    points test_default_tier_effort_reproduces_ticket_matrix already covers. opus shifts every
    effort up by 2 rungs (clamped at max); sonnet shifts every effort down by 1 rung (clamped at
    low), on the [low, medium, high, xhigh, max] ladder — haiku is a distinct model
    (glm-5.2-highspeed) so it stays identity. This is the strongest single guarantee that opus
    stays strictly deeper than sonnet for every possible nominal effort, not just the defaults
    agents/*.md happens to declare today."""
    assert model_policy_dump["policy"]["zai"]["opus"]["thinking"] == {
        "low": "high", "medium": "xhigh", "high": "max", "xhigh": "max", "max": "max",
    }
    assert model_policy_dump["policy"]["zai"]["sonnet"]["thinking"] == {
        "low": "low", "medium": "low", "high": "medium", "xhigh": "high", "max": "xhigh",
    }
    assert model_policy_dump["policy"]["zai"]["haiku"]["thinking"] == {
        "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max",
    }


# Verbatim filenames from the bundled Pi SDK's own provider-data directory (see
# _pi_ai_provider_data_dir below) — the file each SUPPORTED_PROVIDERS entry's catalog lives in.
PROVIDER_DATA_FILES = {
    "anthropic": "anthropic.json",
    "openai-codex": "openai-codex.json",
    "zai": "zai.json",
}


def _pi_ai_provider_data_dir():
    """Locates the bundled `@earendil-works/pi-ai` package's provider-data directory — the
    installed peer's own catalog, pinned to this repo's package.json devDependency. Tries the
    nested path npm produces when pi-ai is NOT independently hoisted to top-level node_modules
    (pi-coding-agent's own nested node_modules) first, then a top-level hoisted path as a
    fallback for an npm resolution that hoists it instead — same two-path posture as any other
    npm install topology this repo doesn't control."""
    nested = (
        ROOT / "node_modules" / "@earendil-works" / "pi-coding-agent" / "node_modules"
        / "@earendil-works" / "pi-ai" / "dist" / "providers" / "data"
    )
    if nested.is_dir():
        return nested
    hoisted = ROOT / "node_modules" / "@earendil-works" / "pi-ai" / "dist" / "providers" / "data"
    if hoisted.is_dir():
        return hoisted
    return None


_PI_AI_DATA_DIR = _pi_ai_provider_data_dir()

if _PI_AI_DATA_DIR is None and os.environ.get("CI"):
    pytest.fail(
        "the pinned Pi catalog (node_modules/@earendil-works/pi-coding-agent's nested "
        "@earendil-works/pi-ai, or a hoisted install) was not found in CI — the pytest job must "
        "run `npm ci` before this test can verify MODEL_POLICY's exact ids against the real "
        "catalog; check the pytest job's npm ci step",
        pytrace=False,
    )

requires_pi_ai_catalog = pytest.mark.skipif(
    _PI_AI_DATA_DIR is None, reason="requires `npm ci` (node_modules/@earendil-works/pi-ai's bundled provider data)"
)


@requires_node
@requires_pi_ai_catalog
def test_model_policy_ids_exist_in_pinned_catalog(model_policy_dump):
    """Every MODEL_POLICY cell names an exact id — this asserts each one actually exists in the
    bundled Pi SDK's own catalog data, not just that it looks plausible. A typo or a removed
    model here would otherwise only surface the first time a real dispatch tried to use it."""
    assert _PI_AI_DATA_DIR is not None  # narrows for the type checker; requires_pi_ai_catalog already gates this
    for provider, tiers in model_policy_dump["policy"].items():
        data_path = _PI_AI_DATA_DIR / PROVIDER_DATA_FILES[provider]
        data = json.loads(data_path.read_text(encoding="utf-8"))
        api = next(iter(data))
        ids_on_catalog = set(data[api].keys())
        for tier, cell in tiers.items():
            assert cell["model"] in ids_on_catalog, (
                f"MODEL_POLICY[{provider!r}][{tier!r}].model {cell['model']!r} not found in the "
                f"pinned catalog ({data_path.relative_to(ROOT)}) — ids: {sorted(ids_on_catalog)}"
            )


_ZAI_CLAMP_DRIVER = """
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const [, , modelsJsPath, zaiDataPath] = process.argv;
const mod = await import(pathToFileURL(modelsJsPath).href);
const zaiData = JSON.parse(readFileSync(zaiDataPath, "utf8"));
const api = Object.keys(zaiData)[0];
const model = zaiData[api]["glm-5.3"];
console.log(JSON.stringify({
  supported: mod.getSupportedThinkingLevels(model),
  clampedMax: mod.clampThinkingLevel(model, "max"),
  clampedHigh: mod.clampThinkingLevel(model, "high"),
}));
"""


@requires_node
@requires_pi_ai_catalog
def test_zai_glm_5_3_dispatches_real_max_thinking_in_pinned_catalog():
    """Successor to the signal test this replaces (`..._clamps_nominal_max_to_high_...`), which
    pinned the Z.AI clamp this repo's MODEL_POLICY deliberately shipped ahead of: through
    @earendil-works/pi-coding-agent@0.84.2, the pinned Pi SDK's bundled catalog *entry* for
    `glm-5.3` declared no `thinkingLevelMap` at all (a gap in that dependency's data, not in
    glm-5.3 itself — per Z.AI's own spec the model always reasons and genuinely supports "max" as
    one of its three real effort levels: low/high/max), so the installed SDK's own
    `clampThinkingLevel` (dist/models.js) reduced MODEL_POLICY.zai.opus's nominal "max" down to
    "high" at dispatch time — identical to zai.sonnet's nominal "high". As of the 0.84.3 bump, the
    pinned catalog now ships a real `thinkingLevelMap` for `glm-5.3` (low/high/max), so that clamp
    no longer applies: zai.opus's nominal "max" dispatches as genuine "max", strictly deeper than
    zai.sonnet's "high" — the opus/sonnet split documented in docs/cost-tiers.md's Z.AI clamp
    caveat is now real, dispatch-visible behavior, not purely nominal. This drives the REAL SDK
    clamp function against the REAL pinned catalog data, not a reimplementation of its logic. If a
    future catalog change drops glm-5.3's thinkingLevelMap again, this test fails loudly — the
    signal to revisit docs/cost-tiers.md's Z.AI clamp caveat once more, not a silent behavior
    change to discover later."""
    node = shutil.which("node")
    assert node is not None
    assert _PI_AI_DATA_DIR is not None  # narrows for the type checker; requires_pi_ai_catalog already gates this
    models_js = _PI_AI_DATA_DIR.parent.parent / "models.js"
    assert models_js.exists(), f"expected {models_js} alongside the pinned provider data"
    zai_data_path = _PI_AI_DATA_DIR / PROVIDER_DATA_FILES["zai"]
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "zai-clamp-dump.mjs"
        driver.write_text(_ZAI_CLAMP_DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", str(driver), str(models_js), str(zai_data_path)],
            capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
        )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    dumped = json.loads(result.stdout)
    assert {"low", "high", "max"} <= set(dumped["supported"]), (
        f"glm-5.3 no longer declares low/high/max support ({dumped['supported']}) in the pinned "
        "catalog — the zai opus/sonnet thinking-level split in MODEL_POLICY may have reverted to "
        "purely nominal; revisit docs/cost-tiers.md's Z.AI clamp caveat and this test"
    )
    assert dumped["clampedMax"] == "max", "zai.opus's nominal max should dispatch as real max now"
    assert dumped["clampedHigh"] == "high"


_TASK_SCHEMA_DRIVER = """
import { pathToFileURL } from "node:url";
const mod = await import(pathToFileURL(process.argv[2]).href);
let registered;
const stubPi = { registerTool(tool) { registered = tool; } };
mod.registerSubagent(stubPi, process.argv[3]);
console.log(JSON.stringify({
  parameters: registered.parameters,
  hasPromptSnippet: typeof registered.promptSnippet === "string" && registered.promptSnippet.length > 0,
  name: registered.name,
}));
"""


@requires_node
def test_task_tool_parameters_is_a_plain_json_schema_object():
    node = shutil.which("node")
    assert node is not None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "task-schema-dump.mjs"
        driver.write_text(_TASK_SCHEMA_DRIVER, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", str(driver), str(SUBAGENT_TS), tmp],
            capture_output=True, text=True, env=_CLEAN_ENV, timeout=30,
        )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    dumped = json.loads(result.stdout)
    assert dumped["name"] == "task"
    parameters = dumped["parameters"]
    assert isinstance(parameters, dict), "parameters must serialize as a plain JSON object"
    assert parameters.get("type") == "object"
    assert set(parameters.get("required", [])) == {"agent", "prompt"}
    assert dumped["hasPromptSnippet"] is True, (
        "custom tools are omitted from the system prompt's Available tools section without a "
        "promptSnippet — task must always carry one"
    )


_EXCLUDE_TOOLS_PROBE_WRAPPER = """
import {{ registerSubagent }} from {subagent_path};

export default function (pi) {{
  registerSubagent(pi, {root});
  pi.on("session_start", (event, ctx) => {{
    const active = pi.getActiveTools();
    process.stderr.write("PROBE_ACTIVE_TOOLS:" + JSON.stringify(active) + "\\n");
    ctx.shutdown();
  }});
}}
"""


def test_exclude_tools_structurally_prevents_task_tool_activation(tmp_path_factory):
    """Live-CLI, zero-model-call probe: registers the REAL task tool (subagent.ts's
    registerSubagent) via the real `pi` binary, and confirms `--exclude-tools task,subagent`
    keeps it out of pi.getActiveTools() — the exact mechanism subagent.ts's own argv relies on
    for its recursion guard (verified against dist/core/agent-session.js's isAllowedTool: an
    excluded tool is never added to the tool registry at construction time, so it cannot be
    resurrected from inside the child session). A session_start handler calls ctx.shutdown()
    before any prompt is sent — `pi -p` with zero message args never calls session.prompt(), so
    this makes no network or model call.

    No node_modules and no global `pi` install exists in this repo's pytest CI job today
    (only the separate typecheck-pi job runs `npm ci`, and no job installs `pi`
    globally) — this test provides real coverage on any developer machine with `pi` installed,
    and will start providing CI coverage automatically if a future CI change adds a `pi`
    install step to the pytest job. Skipping here is a documented, intentional trade-off, not a
    silent no-op.

    `run_probe` passes `--no-extensions` alongside its own explicit `--extension`: on a
    developer machine that has ever run `pi install git:github.com/lugassawan/swe-workbench`
    (e.g. to dogfood the Pi port), that install persists as a globally-discovered extension
    registering its own `task` tool, which collides with this probe's `task` tool registration.
    `--no-extensions` disables discovery of that pre-existing global registration while still
    honoring the explicit `--extension` path (per `pi --help`), keeping the probe hermetic."""
    pi_bin = shutil.which("pi")
    if pi_bin is None:
        pytest.skip("requires a global `pi` CLI on PATH — not provisioned in this repo's pytest CI job")

    wrapper = tmp_path_factory.mktemp("pi-exclude-tools-probe") / "probe.ts"
    wrapper.write_text(
        _EXCLUDE_TOOLS_PROBE_WRAPPER.format(
            subagent_path=json.dumps(str(SUBAGENT_TS)),
            root=json.dumps(str(ROOT)),
        ),
        encoding="utf-8",
    )

    def run_probe(exclude):
        args = [
            pi_bin, "-p", "--no-extensions", "--extension", str(wrapper),
            "--no-session", "--mode", "text",
        ]
        if exclude:
            args += ["--exclude-tools", "task,subagent"]
        result = subprocess.run(args, capture_output=True, text=True, env=dict(_CLEAN_ENV), timeout=30)
        assert result.returncode == 0, f"probe failed: {result.stderr}"
        marker = "PROBE_ACTIVE_TOOLS:"
        line = next((l for l in result.stderr.splitlines() if l.startswith(marker)), None)
        assert line is not None, f"probe never reported active tools; stderr={result.stderr!r}"
        return json.loads(line[len(marker):])

    with_task = run_probe(exclude=False)
    assert "task" in with_task, f"expected task active with no --exclude-tools, got {with_task}"

    excluded = run_probe(exclude=True)
    assert "task" not in excluded, f"--exclude-tools task,subagent failed to exclude task: {excluded}"
