#!/usr/bin/env python3
"""Plugin self-validator. Zero dependencies beyond python3 stdlib."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FAILURES = []


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
            if not isinstance(entry.get("matcher"), str):
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
        text = (skills_cache.get(skill_md) if skills_cache is not None else None) \
            or skill_md.read_text(encoding="utf-8")
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
        text = (agents_cache.get(agent_md) if agents_cache is not None else None) \
            or agent_md.read_text(encoding="utf-8")
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
        text = (agents_cache.get(agent_md) if agents_cache is not None else None) \
            or agent_md.read_text(encoding="utf-8")
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
        skill_text = (skills_cache.get(skill_md) if skills_cache is not None else None) \
            or skill_md.read_text(encoding="utf-8")
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
    """Catalog at agents/shared/skills.md must list every skill, and every agent must include it."""
    catalog = ROOT / "agents" / "shared" / "skills.md"
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    agents_cache = cache[0] if cache is not None else None

    if not catalog.is_file():
        fail(catalog.relative_to(ROOT), "missing — required catalog file")
        return  # remaining checks require the file; can't continue without it

    if not skills_dir.is_dir():
        fail(skills_dir.relative_to(ROOT), "missing — required skills directory")
        return

    text = (agents_cache.get(catalog) if agents_cache is not None else None) \
        or catalog.read_text(encoding="utf-8")
    # — = EM DASH; [^\r\n]* avoids capturing CRLF carriage returns in description
    entry_re = re.compile(r'^-\s+`swe-workbench:([\w-]+)`\s+—\s+(\S[^\r\n]*)$', re.MULTILINE)
    catalog_ids = {sid for sid, _ in entry_re.findall(text)}
    on_disk = {p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()}

    for sid in sorted(on_disk - catalog_ids):
        fail(catalog.relative_to(ROOT),
             f"missing entry for 'swe-workbench:{sid}' (skills/{sid}/SKILL.md exists)")
    for sid in sorted(catalog_ids - on_disk):
        fail(catalog.relative_to(ROOT),
             f"stale entry 'swe-workbench:{sid}' has no skills/{sid}/ on disk")

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
        if "@./shared/skills.md" not in agent_text:
            fail(agent_md.relative_to(ROOT),
                 "missing required '@./shared/skills.md' include"
                 " — add: '> See @./shared/skills.md for the full skill catalog.'")


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

    agents/shared/skills.md (the catalog) is explicitly excluded — it lists
    every skill by design and must not count as a wiring reference.
    """
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    catalog = agents_dir / "shared" / "skills.md"
    agents_cache = cache[0] if cache is not None else None

    principle_skills = sorted(
        p.name for p in skills_dir.glob("principle-*")
        if (p / "SKILL.md").is_file()
    )

    agent_files = sorted(f for f in agents_dir.rglob("*.md") if f != catalog)

    for skill_id in principle_skills:
        needle = f"`swe-workbench:{skill_id}`"
        wired = any(
            needle in (
                (agents_cache.get(f) if agents_cache is not None else None)
                or f.read_text(encoding="utf-8")
            )
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
    check_template_placeholders(cache=cache)
    check_unwired_principle_skills(cache=cache)
    check_examples()

    if FAILURES:
        print(f"FAILED — {len(FAILURES)} issue(s) found:", file=sys.stderr)
        for f in FAILURES:
            print(f, file=sys.stderr)
        sys.exit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()
