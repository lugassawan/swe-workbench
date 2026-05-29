#!/usr/bin/env python3
"""Plugin self-validator. Zero dependencies beyond python3 stdlib."""

import json
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FAILURES = []

# Hook events that fire unconditionally and have no tool name to match against.
# Do NOT add PreToolUse / PostToolUse here — those are tool-matcher events and
# must carry a "matcher" field. Only true lifecycle events belong in this set.
_LIFECYCLE_HOOK_EVENTS = frozenset({"SubagentStop", "PreCompact", "Stop", "Notification"})


def fail(path, reason):
    FAILURES.append(f"  {path}: {reason}")


def parse_frontmatter(path, text=None):
    """Return dict of key:value from YAML frontmatter (single-line scalars only), or None.

    Keys are lowercased for case-insensitive lookup. Caller may pass pre-read `text`
    to avoid a second file read.
    """
    if text is None:
        text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    # Match closing --- on its own line; prefer \n---\n to avoid body horizontal rules.
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end].strip()
    result = {}
    for line in block.splitlines():
        m = re.match(r'^([\w][\w-]*):\s*(.*)$', line.strip())
        if m:
            result[m.group(1).lower()] = m.group(2).strip()
    return result


# ──────────────────────────────────────────────
# File-read cache
# ──────────────────────────────────────────────

def _build_cache():
    """Read every agent .md and every skills/*/SKILL.md exactly once.

    Returns (agents, skills) where each is a dict[Path, str | None].
    rglob("*.md") is intentional: it covers check_unwired_principle_skills
    (which uses rglob) in addition to the flat-glob consumers.
    Unreadable files are stored as None so consumers that track failures
    (e.g. check_catalog_completeness) can report them without re-reading.
    ROOT is resolved inside this function so test monkeypatching of ROOT works.

    Note: skills/*/templates/*.md files are NOT cached here; check_template_placeholders
    reads each template file directly (one read_text() call per template).
    """
    agents_dir = ROOT / "agents"
    skills_dir = ROOT / "skills"
    agents: dict = {}
    skills: dict = {}
    for p in agents_dir.rglob("*.md"):
        try:
            agents[p] = p.read_text(encoding="utf-8")
        except OSError:
            agents[p] = None  # sentinel: present but unreadable
    for p in skills_dir.glob("*/SKILL.md"):
        try:
            skills[p] = p.read_text(encoding="utf-8")
        except OSError:
            skills[p] = None  # sentinel: present but unreadable
    return agents, skills


# ──────────────────────────────────────────────
# Validators
# ──────────────────────────────────────────────

def check_plugin_json():
    path = ROOT / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(path.relative_to(ROOT), f"JSON parse error: {e}")
        return None
    for field in ("name", "version", "description"):
        if field not in data:
            fail(path.relative_to(ROOT), f"missing required field: {field!r}")
    return data


def check_marketplace_json(plugin_data):
    path = ROOT / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(path.relative_to(ROOT), f"JSON parse error: {e}")
        return
    try:
        entry = data["plugins"][0]
    except (KeyError, IndexError, TypeError):
        fail(path.relative_to(ROOT), "expected plugins[0] to exist")
        return
    if plugin_data:
        if entry.get("name") != plugin_data.get("name"):
            fail(
                path.relative_to(ROOT),
                f"plugins[0].name {entry.get('name')!r} != plugin.json name {plugin_data.get('name')!r}",
            )
        if entry.get("version") != plugin_data.get("version"):
            fail(
                path.relative_to(ROOT),
                f"plugins[0].version {entry.get('version')!r} != plugin.json version {plugin_data.get('version')!r}",
            )


def check_hooks_json():
    path = ROOT / "hooks" / "hooks.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(path.relative_to(ROOT), f"JSON parse error: {e}")
        return
    hooks_root = data.get("hooks")
    if not isinstance(hooks_root, dict):
        fail(path.relative_to(ROOT), "top-level 'hooks' must be an object")
        return
    for event, matchers in hooks_root.items():
        if not isinstance(matchers, list):
            fail(path.relative_to(ROOT), f"hooks.{event} must be a list")
            continue
        for i, entry in enumerate(matchers):
            if not isinstance(entry, dict):
                fail(path.relative_to(ROOT), f"hooks.{event}[{i}] must be an object")
                continue
            if event not in _LIFECYCLE_HOOK_EVENTS and not isinstance(entry.get("matcher"), str):
                fail(path.relative_to(ROOT), f"hooks.{event}[{i}].matcher must be a string")
            sub_hooks = entry.get("hooks")
            if not isinstance(sub_hooks, list):
                fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks must be a list")
                continue
            for j, hook in enumerate(sub_hooks):
                if not isinstance(hook, dict):
                    fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks[{j}] must be an object")
                    continue
                if not isinstance(hook.get("type"), str):
                    fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks[{j}].type must be a string")
                if not isinstance(hook.get("command"), str):
                    fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks[{j}].command must be a string")


def check_skills(cache=None):
    skills_dir = ROOT / "skills"
    skills_cache = cache[1] if cache is not None else None
    # glob("*/SKILL.md") matches exactly depth-2 paths; no need for a post-hoc depth guard.
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill_dir_name = skill_md.parent.name
        if skills_cache is not None and skill_md in skills_cache:
            text = skills_cache[skill_md]
            if text is None:
                fail(skill_md.relative_to(ROOT), "could not read file")
                continue
        else:
            text = skill_md.read_text(encoding="utf-8")
        line_count = len(text.splitlines())  # total file length including frontmatter
        fm = parse_frontmatter(skill_md, text=text)
        if fm is None:
            fail(skill_md.relative_to(ROOT), "missing or malformed frontmatter")
            continue
        if "name" not in fm:
            fail(skill_md.relative_to(ROOT), "frontmatter missing required field: 'name'")
        if "description" not in fm:
            fail(skill_md.relative_to(ROOT), "frontmatter missing required field: 'description'")
        if fm.get("name") != skill_dir_name:
            fail(
                skill_md.relative_to(ROOT),
                f"frontmatter name {fm.get('name')!r} does not match directory name {skill_dir_name!r}",
            )
        is_orchestrator = fm.get("orchestrator", "").lower() == "true"
        cap = 300 if is_orchestrator else 150
        if line_count > cap:
            fail(
                skill_md.relative_to(ROOT),
                f"exceeds {cap}-line cap ({line_count} lines)"
                + ("" if is_orchestrator else "; add 'orchestrator: true' to frontmatter if intentional"),
            )


def check_agents(cache=None):
    agents_dir = ROOT / "agents"
    agents_cache = cache[0] if cache is not None else None
    for agent_md in sorted(agents_dir.glob("*.md")):
        if agents_cache is not None and agent_md in agents_cache:
            text = agents_cache[agent_md]
            if text is None:
                fail(agent_md.relative_to(ROOT), "could not read file")
                continue
        else:
            text = agent_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(agent_md, text=text)
        if fm is None:
            fail(agent_md.relative_to(ROOT), "missing or malformed frontmatter")
            continue
        for field in ("name", "description"):
            if field not in fm:
                fail(agent_md.relative_to(ROOT), f"frontmatter missing required field: {field!r}")
        if re.search(r'`swe-workbench:[\w-]+`', text) and "Skill" not in fm.get("tools", ""):
            fail(agent_md.relative_to(ROOT), "references swe-workbench: skills but 'Skill' is missing from tools: frontmatter")


def check_commands():
    commands_dir = ROOT / "commands"
    for cmd_md in sorted(commands_dir.glob("*.md")):
        fm = parse_frontmatter(cmd_md)
        if fm is None:
            fail(cmd_md.relative_to(ROOT), "missing or malformed frontmatter")
            continue
        if "description" not in fm:
            fail(cmd_md.relative_to(ROOT), "frontmatter missing required field: 'description'")


def check_agent_skill_refs(cache=None):
    """Every `swe-workbench:<id>` in agents/*.md must resolve to skills/<id>/ on disk."""
    agents_dir = ROOT / "agents"
    skills_dir = ROOT / "skills"
    agents_cache = cache[0] if cache is not None else None
    pattern = re.compile(r'`swe-workbench:([\w-]+)`')
    for agent_md in sorted(agents_dir.glob("*.md")):
        if agents_cache is not None and agent_md in agents_cache:
            text = agents_cache[agent_md]
            if text is None:
                fail(agent_md.relative_to(ROOT), "could not read file")
                continue
        else:
            text = agent_md.read_text(encoding="utf-8")
        for skill_id in set(pattern.findall(text)):
            if not (skills_dir / skill_id).is_dir():
                fail(
                    agent_md.relative_to(ROOT),
                    f"references 'swe-workbench:{skill_id}' but skills/{skill_id}/ does not exist",
                )


def check_command_skill_refs():
    """Every `swe-workbench:<id>` in commands/*.md must resolve to skills/<id>/ on disk."""
    commands_dir = ROOT / "commands"
    skills_dir = ROOT / "skills"
    pattern = re.compile(r'`swe-workbench:([\w-]+)`')
    for cmd_md in sorted(commands_dir.glob("*.md")):
        text = cmd_md.read_text(encoding="utf-8")
        for skill_id in set(pattern.findall(text)):
            if not (skills_dir / skill_id).is_dir():
                fail(
                    cmd_md.relative_to(ROOT),
                    f"references 'swe-workbench:{skill_id}' but skills/{skill_id}/ does not exist",
                )


TEMPLATE_MARKER_RE = re.compile(r'\[\[detect:([a-z][a-z0-9-]*)\]\]')


def check_template_placeholders(cache=None):
    """Every [[detect:KEY]] in skills/*/templates/*.md must be documented in the
    adjacent SKILL.md's '## Project Detection' section as a backtick-wrapped key."""
    skills_dir = ROOT / "skills"
    skills_cache = cache[1] if cache is not None else None
    for template in sorted(skills_dir.glob("*/templates/*.md")):
        skill_md = template.parent.parent / "SKILL.md"
        if not skill_md.is_file():
            continue
        if skills_cache is not None and skill_md in skills_cache:
            skill_text = skills_cache[skill_md]
            if skill_text is None:
                fail(skill_md.relative_to(ROOT), "could not read file")
                continue
        else:
            skill_text = skill_md.read_text(encoding="utf-8")
        pd_idx = skill_text.find("## Project Detection")
        if pd_idx >= 0:
            next_h2 = skill_text.find("\n## ", pd_idx + 4)
            section = skill_text[pd_idx:next_h2] if next_h2 >= 0 else skill_text[pd_idx:]
        else:
            section = ""
        keys = set(TEMPLATE_MARKER_RE.findall(template.read_text(encoding="utf-8")))
        for key in sorted(keys):
            if f"`{key}`" not in section:
                fail(
                    template.relative_to(ROOT),
                    f"undocumented marker '[[detect:{key}]]' — add `{key}` to "
                    f"'## Project Detection' in {skill_md.relative_to(ROOT)}",
                )


def check_skill_trigger_fixtures():
    """Every skills/<name>/SKILL.md must have a sibling triggers.txt with ≥2
    non-empty non-comment lines (each ≤200 chars)."""
    skills_dir = ROOT / "skills"
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        triggers = skill_md.parent / "triggers.txt"
        if not triggers.is_file():
            fail(
                triggers.relative_to(ROOT),
                "missing — every skill needs ≥2 trigger fixtures (one per line). "
                "See CONTRIBUTING.md.",
            )
            continue
        lines = [
            ln.strip()
            for ln in triggers.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        if len(lines) < 2:
            fail(
                triggers.relative_to(ROOT),
                f"has {len(lines)} trigger fixture(s); minimum is 2",
            )
        for ln in lines:
            if len(ln) > 200:
                fail(
                    triggers.relative_to(ROOT),
                    f"line exceeds 200 chars: {ln[:50]!r}…",
                )


def check_catalog_completeness(cache=None):
    """Per-slice catalogs under agents/shared/ must list every skill in the right slice,
    and every agent must reference at least one slice catalog.

    Slice files and their skill-name prefix rules:
      principles.md  → skill names starting with 'principle-'
      languages.md   → skill names starting with 'language-'
      workflows.md   → skill names starting with 'workflow-' plus 'ticket-context'

    Skills with unrecognised prefixes are assigned to principles.md by convention.
    """
    _SLICE_FILES = {
        "principles.md": ("principle-",),
        "languages.md": ("language-",),
        "workflows.md": ("workflow-",),
    }
    _WORKFLOW_EXTRAS = frozenset({"ticket-context"})
    _SLICE_REFS = frozenset({
        "@./shared/principles.md",
        "@./shared/languages.md",
        "@./shared/workflows.md",
    })
    # — = EM DASH; [^\r\n]* avoids capturing CRLF carriage returns in description
    entry_re = re.compile(r'^-\s+`swe-workbench:([\w-]+)`\s+—\s+(\S[^\r\n]*)$', re.MULTILINE)

    agents_dir = ROOT / "agents"
    shared_dir = agents_dir / "shared"
    skills_dir = ROOT / "skills"
    agents_cache = cache[0] if cache is not None else None

    if not skills_dir.is_dir():
        fail(skills_dir.relative_to(ROOT), "missing — required skills directory")
        return

    on_disk = {p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()}

    def _expected_slice(sid):
        for fname, prefixes in _SLICE_FILES.items():
            if any(sid.startswith(p) for p in prefixes):
                return fname
        if sid in _WORKFLOW_EXTRAS:
            return "workflows.md"
        return "principles.md"  # safe default for unrecognised prefixes

    # Audit each slice file
    for slice_file in _SLICE_FILES:
        slice_path = shared_dir / slice_file
        if not slice_path.is_file():
            fail(slice_path.relative_to(ROOT), "missing — required catalog slice file")
            continue

        if agents_cache is not None and slice_path in agents_cache:
            text = agents_cache[slice_path]
            if text is None:
                fail(slice_path.relative_to(ROOT), "could not read file")
                continue
        else:
            try:
                text = slice_path.read_text(encoding="utf-8")
            except OSError as e:
                fail(slice_path.relative_to(ROOT), f"could not read file: {e}")
                continue

        slice_ids = {sid for sid, _ in entry_re.findall(text)}
        expected_in_slice = {sid for sid in on_disk if _expected_slice(sid) == slice_file}

        for sid in sorted(expected_in_slice - slice_ids):
            fail(slice_path.relative_to(ROOT),
                 f"missing entry for 'swe-workbench:{sid}' (skills/{sid}/SKILL.md exists)")
        for sid in sorted(slice_ids - on_disk):
            fail(slice_path.relative_to(ROOT),
                 f"stale entry 'swe-workbench:{sid}' has no skills/{sid}/ on disk")
        for sid in sorted(slice_ids & on_disk):
            if _expected_slice(sid) != slice_file:
                fail(slice_path.relative_to(ROOT),
                     f"entry 'swe-workbench:{sid}' belongs in {_expected_slice(sid)}, not {slice_file}")

    # Agents that reference @./shared/principles.md but are not code-touching
    # (e.g. product-manager files GitHub issues and never reads source).
    # These are explicitly exempt from the languages.md co-requirement below.
    _NON_CODE_AGENTS = frozenset({
        "product-manager",
    })

    # Every agent must reference at least one slice catalog, and every
    # code-touching agent (one that includes principles.md) must ALSO include
    # languages.md so language-specific skills are always in scope.
    for agent_md in sorted(agents_dir.glob("*.md")):
        if agents_cache is not None and agent_md in agents_cache:
            agent_text = agents_cache[agent_md]
            if agent_text is None:
                fail(agent_md.relative_to(ROOT), "could not read file")
                continue
        else:
            try:
                agent_text = agent_md.read_text(encoding="utf-8")
            except OSError as e:
                fail(agent_md.relative_to(ROOT), f"could not read file: {e}")
                continue
        if not any(ref in agent_text for ref in _SLICE_REFS):
            fail(agent_md.relative_to(ROOT),
                 "missing required slice catalog reference"
                 " — add at least one of: '@./shared/principles.md',"
                 " '@./shared/languages.md', '@./shared/workflows.md'")
            continue
        # Code-touching agents must include both catalogs.
        if (agent_md.stem not in _NON_CODE_AGENTS
                and "@./shared/principles.md" in agent_text
                and "@./shared/languages.md" not in agent_text):
            fail(agent_md.relative_to(ROOT),
                 "code-touching agent includes '@./shared/principles.md' but is missing"
                 " '@./shared/languages.md' — add it so language-* skills are in scope."
                 " If this agent never touches source code, add its stem to"
                 " _NON_CODE_AGENTS in check_catalog_completeness().")


_BLOCKQUOTED_SHARED_RE = re.compile(r'^\s*>.*@\./shared/')


def check_shared_includes_not_blockquoted(cache=None):
    """`@./shared/*.md` includes must be plain paragraphs, not blockquotes.

    A leading '> ' suppresses include resolution so the shared catalog/contract
    is never injected into the agent (issue #309). Convergent plain form:
    `See @./shared/principles.md for the skill catalog.`
    """
    agents_dir = ROOT / "agents"
    agents_cache = cache[0] if cache is not None else None
    for agent_md in sorted(agents_dir.glob("*.md")):
        if agents_cache is not None and agent_md in agents_cache:
            text = agents_cache[agent_md]
            if text is None:
                fail(agent_md.relative_to(ROOT), "could not read file")
                continue
        else:
            try:
                text = agent_md.read_text(encoding="utf-8")
            except OSError as e:
                fail(agent_md.relative_to(ROOT), f"could not read file: {e}")
                continue
        for i, line in enumerate(text.splitlines(), 1):
            if _BLOCKQUOTED_SHARED_RE.match(line):
                fail(
                    agent_md.relative_to(ROOT),
                    f"line {i}: '@./shared/' include is blockquoted — drop the leading "
                    f"'> ' so the include resolves (issue #309): {line.strip()[:60]!r}",
                )


def check_examples():
    """Example files in skills/*/examples/**/*.md must not exceed 120 lines."""
    skills_dir = ROOT / "skills"
    for example in sorted(skills_dir.glob("*/examples/**/*.md")):
        try:
            text = example.read_text(encoding="utf-8")
        except OSError as e:
            fail(example.relative_to(ROOT), f"could not read file: {e}")
            continue
        line_count = len(text.splitlines())
        if line_count > 120:
            fail(
                example.relative_to(ROOT),
                f"exceeds 120-line example cap ({line_count} lines); "
                "split into multiple files or trim the example",
            )


def check_unwired_principle_skills(cache=None):
    """Every skills/principle-*/ must be referenced by at least one agent.

    agents/shared/ (the catalog slice files) are explicitly excluded — they list
    every skill by design and must not count as a wiring reference.
    """
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    shared_dir = agents_dir / "shared"
    agents_cache = cache[0] if cache is not None else None

    principle_skills = sorted(
        p.name for p in skills_dir.glob("principle-*")
        if (p / "SKILL.md").is_file()
    )

    agent_files = [
        f for f in sorted(agents_dir.rglob("*.md"))
        if f.parent != shared_dir
        and (agents_cache is None or agents_cache.get(f) is not None)
    ]

    for skill_id in principle_skills:
        needle = f"`swe-workbench:{skill_id}`"
        wired = any(
            needle in (agents_cache[f] if agents_cache is not None else f.read_text(encoding="utf-8"))
            for f in agent_files
        )
        if not wired:
            fail(
                Path("agents") / "<unwired>",
                f"principle skill 'swe-workbench:{skill_id}' is not referenced by any "
                f"agent in agents/*.md — wire it into a relevant agent's "
                f"'## Principle consultation' list",
            )


# ──────────────────────────────────────────────
# Python hook syntax check
# ──────────────────────────────────────────────

_TEST_ENV_LEAK_RE = re.compile(
    r'\benv\s*=\s*(?:\{\s*\*\*\s*os\.environ|dict\s*\(\s*os\.environ\s*\)|os\.environ(?!\s*\.))'
)


_TEST_ENV_EXEMPT = frozenset({"conftest.py", "test_validate.py"})


def check_test_subprocess_env():
    """tests/*.py subprocess sites must not pass the raw parent env.
    Use env=dict(_CLEAN_ENV) or env={**_CLEAN_ENV, ...}. See tests/README.md.
    conftest.py is exempt (defines _CLEAN_ENV and the runtime guard).
    test_validate.py is exempt (contains bad-pattern strings as test fixture data)."""
    tests_dir = ROOT / "tests"
    for py_file in sorted(tests_dir.glob("*.py")):  # intentionally flat — subdirs not scanned
        if py_file.name in _TEST_ENV_EXEMPT:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError as e:
            fail(py_file.relative_to(ROOT), f"could not read file: {e}")
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _TEST_ENV_LEAK_RE.search(line):
                fail(
                    py_file.relative_to(ROOT),
                    f"line {i}: subprocess env= leaks the parent environment "
                    f"(GIT_DIR leaks into git children under the pre-push hook). "
                    f"Use env=dict(_CLEAN_ENV) or env={{**_CLEAN_ENV, ...}}. "
                    f"See tests/README.md.",
                )


def check_hook_scripts():
    hooks_dir = ROOT / "hooks"
    for py_file in sorted(hooks_dir.glob("*.py")):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            fail(py_file.relative_to(ROOT), str(exc))


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    print("Validating swe-workbench plugin files...")
    print()

    cache = _build_cache()

    plugin_data = check_plugin_json()
    check_marketplace_json(plugin_data)
    check_hooks_json()
    check_skills(cache=cache)
    check_skill_trigger_fixtures()
    check_agents(cache=cache)
    check_commands()
    check_agent_skill_refs(cache=cache)
    check_command_skill_refs()
    check_catalog_completeness(cache=cache)
    check_shared_includes_not_blockquoted(cache=cache)
    check_template_placeholders(cache=cache)
    check_unwired_principle_skills(cache=cache)
    check_examples()
    check_hook_scripts()
    check_test_subprocess_env()

    if FAILURES:
        print(f"FAILED — {len(FAILURES)} issue(s) found:", file=sys.stderr)
        for f in FAILURES:
            print(f, file=sys.stderr)
        sys.exit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()
