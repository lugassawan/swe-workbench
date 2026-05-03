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
            if not isinstance(entry.get("matcher"), str):
                fail(path.relative_to(ROOT), f"hooks.{event}[{i}].matcher must be a string")
            sub_hooks = entry.get("hooks")
            if not isinstance(sub_hooks, list):
                fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks must be a list")
                continue
            for j, hook in enumerate(sub_hooks):
                if not isinstance(hook.get("type"), str):
                    fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks[{j}].type must be a string")
                if not isinstance(hook.get("command"), str):
                    fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks[{j}].command must be a string")


def check_skills():
    skills_dir = ROOT / "skills"
    # glob("*/SKILL.md") matches exactly depth-2 paths; no need for a post-hoc depth guard.
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill_dir_name = skill_md.parent.name
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


def check_agents():
    agents_dir = ROOT / "agents"
    for agent_md in sorted(agents_dir.glob("*.md")):
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


def check_agent_skill_refs():
    """Every `swe-workbench:<id>` in agents/*.md must resolve to skills/<id>/ on disk."""
    agents_dir = ROOT / "agents"
    skills_dir = ROOT / "skills"
    pattern = re.compile(r'`swe-workbench:([\w-]+)`')
    for agent_md in sorted(agents_dir.glob("*.md")):
        text = agent_md.read_text(encoding="utf-8")
        for skill_id in set(pattern.findall(text)):
            if not (skills_dir / skill_id).is_dir():
                fail(
                    agent_md.relative_to(ROOT),
                    f"references 'swe-workbench:{skill_id}' but skills/{skill_id}/ does not exist",
                )


def check_catalog_completeness():
    """Catalog at agents/shared/skills.md must list every skill, and every agent must include it."""
    catalog = ROOT / "agents" / "shared" / "skills.md"
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"

    if not catalog.is_file():
        fail(catalog.relative_to(ROOT), "missing — required catalog file")
        return  # remaining checks require the file; can't continue without it

    if not skills_dir.is_dir():
        fail(skills_dir.relative_to(ROOT), "missing — required skills directory")
        return

    text = catalog.read_text(encoding="utf-8")
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
        try:
            agent_text = agent_md.read_text(encoding="utf-8")
        except OSError as e:
            fail(agent_md.relative_to(ROOT), f"could not read file: {e}")
            continue
        if "@./shared/skills.md" not in agent_text:
            fail(agent_md.relative_to(ROOT),
                 "missing required '@./shared/skills.md' include"
                 " — add: '> See @./shared/skills.md for the full skill catalog.'")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    print("Validating swe-workbench plugin files...")
    print()

    plugin_data = check_plugin_json()
    check_marketplace_json(plugin_data)
    check_hooks_json()
    check_skills()
    check_agents()
    check_commands()
    check_agent_skill_refs()
    check_catalog_completeness()

    if FAILURES:
        print(f"FAILED — {len(FAILURES)} issue(s) found:", file=sys.stderr)
        for f in FAILURES:
            print(f, file=sys.stderr)
        sys.exit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()
