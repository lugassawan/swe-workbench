#!/usr/bin/env python3
"""Plugin self-validator. Zero dependencies beyond python3 stdlib."""

import json
import os
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FAILURES = []
WARNINGS = []

# SKILL.md line caps (#568). A skill declaring 'orchestrator: true' in its
# frontmatter gets the higher cap — see check_orchestrator_flag_earned() for
# the rule that the flag itself must be earned (size or composition).
BASE_SKILL_CAP = 150
ORCHESTRATOR_SKILL_CAP = 300

# Headroom warning threshold (#567): fraction of a skill's cap at which
# check_skill_cap_headroom() starts warning, ahead of check_skills()'s hard
# failure at 100%.
CAP_HEADROOM_WARN_FRACTION = 0.90

# Hook events that fire unconditionally and have no tool name to match against.
# Do NOT add PreToolUse / PostToolUse here — those are tool-matcher events and
# must carry a "matcher" field. Only true lifecycle events belong in this set.
_LIFECYCLE_HOOK_EVENTS = frozenset({"SubagentStop", "PreCompact", "Stop", "Notification"})

# Agents that reference @./shared/principles.md but are NOT code-touching and
# are therefore exempt from the languages.md co-requirement enforced by
# check_catalog_completeness(). Add an agent's stem here when it genuinely
# never reads or writes source code (e.g. it only files GitHub issues).
_NON_CODE_AGENTS = frozenset({
    "product-manager",
})

# Browser MCP tool patterns that trigger the hard gate (#364).
# Any agent or command containing one of these strings must also carry
# a BLOCKED: sentinel and a per-backend install hint.
# Exception: mcp__claude-in-chrome__* is the in-harness Claude browser extension —
# it has no installable package, so the install-hint requirement is waived for
# files whose only browser signal is claude-in-chrome references.
_BROWSER_MCP_SIGNALS = re.compile(
    r'browser_snapshot|read_console_messages|read_network_requests'
    r'|mcp__\S*chrome\S*|@playwright/mcp'
)
_CLAUDE_IN_CHROME_ONLY = re.compile(r'mcp__claude-in-chrome__\S*')
_BROWSER_INSTALL_HINTS = re.compile(
    r'claude mcp add \S+|npx @playwright/mcp@latest|npx chrome-devtools-mcp@latest'
)

# LSP tool gate (#559). Any agent granting LSP in its tools: frontmatter must
# preload the shared LSP doc, which in turn must carry the fallback sentence.
# Deliberately NOT a body-text regex: agents/shared/principles.md:27 uses "LSP"
# for the Liskov Substitution Principle, so a substring/body match would
# false-positive on every agent preloading principle-solid.
_LSP_FALLBACK = "LSP unavailable — falling back to Grep"   # em dash, U+2014
_LSP_SHARED_INCLUDE = "@./shared/lsp.md"


def fail(path, reason):
    FAILURES.append(f"  {path}: {reason}")


def warn(path, reason):
    """Non-fatal counterpart to fail(): appends to WARNINGS, never FAILURES.
    Must never be able to cause a non-zero exit — see main()'s WARNINGS
    reporting, which prints but does not gate sys.exit(1)."""
    WARNINGS.append(f"  {path}: {reason}")


_FM_KEY_RE = re.compile(r'^([\w][\w-]*):\s*(.*)$')
_FM_ITEM_RE = re.compile(r'^-\s+(.*\S)\s*$')


def parse_frontmatter(path, text=None):
    """Return dict of key:value from YAML frontmatter, or None.

    Single-line scalars yield str. A key with an empty scalar followed by
    `- item` lines yields list[str]. Keys are lowercased for case-insensitive
    lookup. Caller may pass pre-read `text` to avoid a second file read.
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
    pending = None  # key eligible to collect block-sequence items
    for line in block.splitlines():
        stripped = line.strip()
        if stripped == "":
            continue  # blank line: does not disturb a pending block-sequence key
        item = _FM_ITEM_RE.match(stripped)
        if item and pending is not None:
            if not isinstance(result[pending], list):
                result[pending] = []
            result[pending].append(item.group(1).strip())
            continue
        m = _FM_KEY_RE.match(stripped)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            result[key] = value
            pending = key if value == "" else None
        else:
            pending = None
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


# Closed-form shape for every hooks.json command string (issue #557): an
# explicit interpreter plus a quoted, braced CLAUDE_PLUGIN_ROOT expansion.
# This is a positive invariant this repo owns, not validation against the
# platform schema — a future hook needing arguments must widen this regex
# explicitly, which is the fail-loud behaviour intended.
_HOOK_COMMAND_SHAPE_RE = re.compile(
    r'^(?:bash|python3) "\$\{CLAUDE_PLUGIN_ROOT\}"/hooks/[A-Za-z0-9_.-]+$'
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
                command = hook.get("command")
                if not isinstance(command, str):
                    fail(path.relative_to(ROOT), f"hooks.{event}[{i}].hooks[{j}].command must be a string")
                elif not _HOOK_COMMAND_SHAPE_RE.match(command):
                    fail(
                        path.relative_to(ROOT),
                        f"hooks.{event}[{i}].hooks[{j}].command {command!r} does not match the "
                        f"required shape '(bash|python3) \"${{CLAUDE_PLUGIN_ROOT}}\"/hooks/<script>' (#557)",
                    )
                if "if" in hook:
                    fail(
                        path.relative_to(ROOT),
                        f"hooks.{event}[{i}].hooks[{j}] carries an 'if' condition — no hooks.json "
                        f"entry may use 'if' (see docs/plugin-platform-decisions.md §4)",
                    )


def _skill_cap_info(fm):
    """Return (is_orchestrator, cap) for a skill's parsed frontmatter dict.

    Single source of truth for the orchestrator-flag detection rule and cap
    selection (300 if 'orchestrator: true', else 150) — shared by
    check_skills() (which also needs is_orchestrator for its failure message)
    and check_skill_cap_headroom() (#567), so the two checks can never drift
    on what counts as 'orchestrator' or what cap applies.
    """
    is_orchestrator = fm.get("orchestrator", "").lower() == "true"
    cap = ORCHESTRATOR_SKILL_CAP if is_orchestrator else BASE_SKILL_CAP
    return is_orchestrator, cap


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
        is_orchestrator, cap = _skill_cap_info(fm)
        if line_count > cap:
            fail(
                skill_md.relative_to(ROOT),
                f"exceeds {cap}-line cap ({line_count} lines)"
                + ("" if is_orchestrator else "; add 'orchestrator: true' to frontmatter if intentional"),
            )


def check_skill_cap_headroom(cache=None):
    """Warn (non-fatally) when a skill's SKILL.md line count crosses 90% of
    its cap (#567) — early signal that a skill is approaching the hard cap
    that check_skills() enforces, before it actually trips that failure.

    Cap detection reuses _skill_cap_info() — the same helper check_skills()
    uses — so this never drifts from that check's orchestrator-flag rule.
    This check only ever calls warn(), never fail() — it must not affect the
    build's exit code. Skills with missing/malformed frontmatter or an
    unreadable file are skipped here; check_skills() already reports those.
    """
    skills_dir = ROOT / "skills"
    skills_cache = cache[1] if cache is not None else None
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        if skills_cache is not None and skill_md in skills_cache:
            text = skills_cache[skill_md]
            if text is None:
                continue  # unreadable — already reported by check_skills
        else:
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
        fm = parse_frontmatter(skill_md, text=text)
        if fm is None:
            continue  # malformed frontmatter — already reported by check_skills
        line_count = len(text.splitlines())
        _, cap = _skill_cap_info(fm)
        threshold = cap * CAP_HEADROOM_WARN_FRACTION
        if line_count > threshold:
            warn(
                skill_md.relative_to(ROOT),
                f"{line_count} lines — within {round((1 - CAP_HEADROOM_WARN_FRACTION) * 100)}% "
                f"of the {cap}-line cap; consider extracting content before it hits the hard cap",
            )


_ORCHESTRATOR_NAMESPACED_REF_RE = re.compile(r'`swe-workbench:([\w-]+)`')
_ORCHESTRATOR_BARE_REF_RE = re.compile(r'`([\w-]+)`')


def check_orchestrator_flag_earned(cache=None):
    """A skill declaring 'orchestrator: true' must earn the higher cap (#568):
    either by needing the extra headroom (line count > BASE_SKILL_CAP) or by
    coordinating other skills/agents. A skill at or under BASE_SKILL_CAP that
    references nothing has an inert flag and should have it removed.

    Reference detection is a coarse heuristic: any backtick-quoted token that
    resolves to a real skill/agent id counts, even a purely contrastive or
    negative mention (e.g. "unlike `other-skill`, this one does X"). It does
    not verify the mention is actually a delegation."""
    skills_dir = ROOT / "skills"
    agents_dir = ROOT / "agents"
    skills_cache = cache[1] if cache is not None else None

    valid_ids = {p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}
    valid_ids |= {p.stem for p in agents_dir.glob("*.md")}

    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill_dir_name = skill_md.parent.name
        if skills_cache is not None and skill_md in skills_cache:
            text = skills_cache[skill_md]
            if text is None:
                continue  # already reported by check_skills
        else:
            text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(skill_md, text=text)
        if fm is None or fm.get("orchestrator", "").lower() != "true":
            continue
        line_count = len(text.splitlines())
        if line_count > BASE_SKILL_CAP:
            continue  # headroom earns the flag outright
        own_valid_ids = valid_ids - {skill_dir_name}
        referenced = (
            set(_ORCHESTRATOR_NAMESPACED_REF_RE.findall(text))
            | set(_ORCHESTRATOR_BARE_REF_RE.findall(text))
        ) & own_valid_ids
        if not referenced:
            fail(
                skill_md.relative_to(ROOT),
                f"declares 'orchestrator: true' but is {line_count} lines (at or under the "
                f"{BASE_SKILL_CAP}-line base cap) and references no other skill or agent; "
                "remove the flag, or reference the skills/agents it coordinates",
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
        if (
            re.search(r'`swe-workbench:[\w-]+`', text)
            and "tools" in fm
            and "Skill" not in fm["tools"]
        ):
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
    """Every `swe-workbench:<id>` in agents/*.md must resolve to a skill dir,
    agent file, or command file on disk."""
    agents_dir = ROOT / "agents"
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
        for artifact_id in set(pattern.findall(text)):
            if not _artifact_exists(artifact_id):
                fail(
                    agent_md.relative_to(ROOT),
                    f"references 'swe-workbench:{artifact_id}' but no matching artifact found "
                    f"(checked skills/{artifact_id}/, agents/{artifact_id}.md, commands/{artifact_id}.md)",
                )


def check_preloaded_skills(cache=None):
    """Every agent's frontmatter 'skills:' entry must be a namespaced,
    resolvable, canary-bearing preload (issue #558/#562).

    Bare (non-namespaced) skill names silently fail to preload at dispatch
    time — Claude Code only resolves the 'swe-workbench:<id>' form. Agents
    without a 'skills:' key are skipped entirely, so this is a no-op for
    agents that don't opt into preloading. A body-text mention of the
    preloaded skill is no longer required — see check_unwired_principle_skills,
    which recognizes frontmatter 'skills:' entries as wiring in their own right.
    """
    agents_dir = ROOT / "agents"
    skills_dir = ROOT / "skills"
    agents_cache = cache[0] if cache is not None else None
    skills_cache = cache[1] if cache is not None else None

    for agent_md in sorted(agents_dir.glob("*.md")):
        if agents_cache is not None and agent_md in agents_cache:
            text = agents_cache[agent_md]
            if text is None:
                continue  # already reported by check_agents
        else:
            text = agent_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(agent_md, text=text)
        if fm is None or "skills" not in fm:
            continue
        rel = agent_md.relative_to(ROOT)
        entries = fm["skills"]
        if not isinstance(entries, list) or not entries:
            fail(
                rel,
                "frontmatter 'skills:' must be a YAML block sequence "
                "(e.g. '- swe-workbench:<id>'), not a scalar or empty value",
            )
            continue
        for entry in entries:
            if not entry.startswith("swe-workbench:"):
                fail(
                    rel,
                    f"frontmatter 'skills:' entry {entry!r} is not namespaced — "
                    "bare skill names silently fail to preload; use 'swe-workbench:<id>'",
                )
                continue
            skill_id = entry.split(":", 1)[1]
            skill_md = skills_dir / skill_id / "SKILL.md"
            if not skill_md.is_file():
                fail(
                    rel,
                    f"frontmatter 'skills:' entry {entry!r} does not resolve to "
                    f"skills/{skill_id}/SKILL.md",
                )
                continue
            if skills_cache is not None and skill_md in skills_cache:
                skill_text = skills_cache[skill_md]
            else:
                try:
                    skill_text = skill_md.read_text(encoding="utf-8")
                except OSError:
                    skill_text = None
            canary = f"SWB-PRELOAD-{skill_id.upper()}"
            if skill_text is None or f"preload-canary: {canary}" not in skill_text:
                fail(
                    rel,
                    f"preloaded skill 'skills/{skill_id}/SKILL.md' is missing its "
                    f"'<!-- preload-canary: {canary} -->' marker",
                )


def check_command_skill_refs():
    """Every `swe-workbench:<id>` in commands/*.md must resolve to a skill dir,
    agent file, or command file on disk."""
    commands_dir = ROOT / "commands"
    pattern = re.compile(r'`swe-workbench:([\w-]+)`')
    for cmd_md in sorted(commands_dir.glob("*.md")):
        text = cmd_md.read_text(encoding="utf-8")
        for artifact_id in set(pattern.findall(text)):
            if not _artifact_exists(artifact_id):
                fail(
                    cmd_md.relative_to(ROOT),
                    f"references 'swe-workbench:{artifact_id}' but no matching artifact found "
                    f"(checked skills/{artifact_id}/, agents/{artifact_id}.md, commands/{artifact_id}.md)",
                )


def _artifact_exists(artifact_id):
    """Return True if artifact_id resolves to a skill dir, agent file, or command file."""
    return (
        (ROOT / "skills" / artifact_id).is_dir()
        or (ROOT / "agents" / f"{artifact_id}.md").is_file()
        or (ROOT / "commands" / f"{artifact_id}.md").is_file()
    )


def check_skill_skill_refs(cache=None):
    """Every `swe-workbench:<id>` in skills/*/SKILL.md must resolve to a skill dir,
    agent file, or command file on disk."""
    skills_dir = ROOT / "skills"
    skills_cache = cache[1] if cache is not None else None
    pattern = re.compile(r'`swe-workbench:([\w-]+)`')
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        if skills_cache is not None and skill_md in skills_cache:
            text = skills_cache[skill_md]
            if text is None:
                fail(skill_md.relative_to(ROOT), "could not read file")
                continue
        else:
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                fail(skill_md.relative_to(ROOT), "could not read file")
                continue
        for artifact_id in set(pattern.findall(text)):
            if not _artifact_exists(artifact_id):
                fail(
                    skill_md.relative_to(ROOT),
                    f"references 'swe-workbench:{artifact_id}' but skills/{artifact_id}/ does not exist "
                    f"and neither does agents/{artifact_id}.md or commands/{artifact_id}.md",
                )


_BARE_ID_RE = re.compile(r'`([\w-]+)`')
_PROSE_REF_EXEMPTION_MARKER = '<!-- validate: prose-ref -->'


def _bare_actionable_id_set():
    """Return the set of every resolvable skill and agent id, mirroring the
    resolution index _build_dep_graph builds for the cycle checker."""
    ids = set()
    for p in (ROOT / "skills").glob("*/SKILL.md"):
        ids.add(p.parent.name)
    for p in (ROOT / "agents").glob("*.md"):
        if p.parent.name == "shared":
            continue
        ids.add(p.stem)
    return ids


def check_bare_actionable_refs(cache=None):
    """Machine-actionable dispatch references must use the namespaced
    `swe-workbench:<id>` form (#586).

    check_command_skill_refs / check_skill_skill_refs only resolution-check
    the already-namespaced `` `swe-workbench:<id>` `` pattern, so a bare
    dispatch id (e.g. "Delegate to the `senior-engineer` subagent") is never
    validated and can silently drift from the namespaced form used for the
    identical construct elsewhere. Two rules, both scoped to
    machine-actionable dispatch — prose, catalog tables, and README
    enumerations are untouched:

    Rule 1 (commands/*.md): every bare skill/agent id outside a fenced code
    block must be namespaced — command bodies are dispatch scripts, so no
    action-cue heuristic is applied. A line may opt out with the
    '<!-- validate: prose-ref -->' marker (a genuinely non-dispatch mention,
    e.g. an example list of literal identifier strings).

    Rule 2 (skills/*/SKILL.md): only lines the action-cued activation
    classifier (_ACTION_RE / _POINTER_RE / _SLASH_CMD_RE — the same regexes
    check_no_cycles's _build_dep_graph uses) would treat as a dispatch edge.
    Note this scans a narrower line set than _build_dep_graph: Rule 2 also
    strips fenced code blocks first (_strip_fenced_code_blocks), so a
    dispatch-cued line inside a fenced example is a cycle-graph edge but not
    a Rule 2 candidate. A skill naming its own id is exempt (self-reference),
    and the same exemption marker opts out a line the classifier over-flags
    as a dispatch cue when it is really prose.
    """
    if cache is None:
        cache = _build_cache()
    skills_cache = cache[1]

    ids = _bare_actionable_id_set()
    commands_dir = ROOT / "commands"
    skills_dir = ROOT / "skills"

    # Rule 1 — commands/*.md
    for cmd_md in sorted(commands_dir.glob("*.md")):
        try:
            text = cmd_md.read_text(encoding="utf-8")
        except OSError:
            continue
        stripped = _strip_fenced_code_blocks(text)
        for i, line in enumerate(stripped.split('\n'), start=1):
            if line.lstrip().startswith('@'):
                continue
            if _PROSE_REF_EXEMPTION_MARKER in line:
                continue
            for bare_id in _BARE_ID_RE.findall(line):
                if bare_id in ids:
                    fail(
                        cmd_md.relative_to(ROOT),
                        f"line {i}: bare reference `{bare_id}` must be namespaced as "
                        f"`swe-workbench:{bare_id}` — machine-actionable references in "
                        f"commands/ are dispatch instructions, not prose (mark a genuinely "
                        f"non-dispatch line with '{_PROSE_REF_EXEMPTION_MARKER}' to exempt it)",
                    )

    # Rule 2 — skills/*/SKILL.md dispatch-cued lines
    for skill_md, text in skills_cache.items():
        if skill_md.parent.parent != skills_dir:
            continue
        if text is None:
            continue
        own_id = skill_md.parent.name
        stripped = _strip_fenced_code_blocks(text)
        for i, line in enumerate(stripped.split('\n'), start=1):
            if line.lstrip().startswith('@'):
                continue
            if _PROSE_REF_EXEMPTION_MARKER in line:
                continue
            clean = _SLASH_CMD_RE.sub('', line)
            if not _ACTION_RE.search(clean):
                continue
            if _POINTER_RE.search(clean):
                continue
            for bare_id in _BARE_ID_RE.findall(line):
                if bare_id not in ids or bare_id == own_id:
                    continue
                fail(
                    skill_md.relative_to(ROOT),
                    f"line {i}: bare reference `{bare_id}` on a dispatch-cued line must be "
                    f"namespaced as `swe-workbench:{bare_id}` (mark the line "
                    f"'{_PROSE_REF_EXEMPTION_MARKER}' if it is genuinely not a dispatch)",
                )


def check_workflow_development_activation_contract():
    """The '/swe-workbench:<cmd>' tokens in workflow-development's description frontmatter
    must match exactly the set of commands whose .md files reference
    'swe-workbench:workflow-development'."""
    skill_md = ROOT / "skills" / "workflow-development" / "SKILL.md"
    if not skill_md.is_file():
        fail(
            skill_md.relative_to(ROOT),
            "missing — cannot check workflow-development activation contract",
        )
        return
    fm = parse_frontmatter(skill_md)
    if fm is None or "description" not in fm:
        fail(skill_md.relative_to(ROOT), "missing or malformed frontmatter")
        return

    commands_dir = ROOT / "commands"
    declared_pattern = re.compile(r'/swe-workbench:([\w-]+)')
    desc = fm["description"]
    # Scope to the activation clause (before "when") to avoid matching prose examples
    activation_clause = desc.split(" when ")[0]
    raw_declared = set(declared_pattern.findall(activation_clause))
    unknown_commands = sorted(t for t in raw_declared if not (commands_dir / f"{t}.md").is_file())
    if unknown_commands:
        fail(
            skill_md.relative_to(ROOT),
            f"workflow-development description lists unknown commands: {unknown_commands}",
        )
    # Exclude unknown tokens from set-equality to avoid double-reporting
    declared = raw_declared - set(unknown_commands)

    actual = set()
    wf_pattern = re.compile(r'`swe-workbench:workflow-development`')
    for cmd_md in sorted(commands_dir.glob("*.md")):
        # commands are intentionally not cached in _build_cache; read directly
        try:
            text = cmd_md.read_text(encoding="utf-8")
        except OSError:
            fail(cmd_md.relative_to(ROOT), "could not read file")
            continue
        if wf_pattern.search(text):
            actual.add(cmd_md.stem)

    if declared != actual:
        listed_not_activating = sorted(declared - actual)
        activating_not_listed = sorted(actual - declared)
        parts = []
        if listed_not_activating:
            parts.append(f"listed but do not activate: {listed_not_activating}")
        if activating_not_listed:
            parts.append(f"activate but are not listed: {activating_not_listed}")
        fail(
            skill_md.relative_to(ROOT),
            "workflow-development activation contract mismatch — " + "; ".join(parts),
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


_ADAPTER_FIELD_LABELS = ("Trigger", "Fetch", "Extract → block fields", "Degrade")
_ADAPTERS_HEADING_RE = re.compile(r'^##(?!#)[ \t]+Adapters[ \t]*$', re.MULTILINE)
# Next top-level ('##', not '###+') heading — bounds the '## Adapters' section.
_H2_BOUNDARY_RE = re.compile(r'^##(?!#)[ \t]+\S', re.MULTILINE)
# One '### <Provider>' sub-heading starts one adapter block.
_H3_PROVIDER_RE = re.compile(r'^###(?!#)[ \t]+(.+?)[ \t]*$', re.MULTILINE)
# Opening fence: ``` or ~~~ (3+) at some indent. Line-scanned (not matched
# as one block regex) so the closing fence can be length-checked against the
# opening length via a per-match compiled pattern — a plain backreference
# can only require an EXACT repeat, but CommonMark allows the closer to be
# >= the opener's length (e.g. open ``` / close ````).
_FENCE_OPEN_RE = re.compile(r'^([ \t]*)(`{3,}|~{3,})')


def _strip_fenced_code_blocks(text):
    """Blank out the interior of fenced (``` / ~~~) code blocks.

    Adapter authors illustrate the recipe template inside a fence (see
    docs/extending.md); without this, a fenced '## X' or '- **Trigger:**'
    example line is indistinguishable from real structure to the
    heading/boundary/label regexes below — either truncating a section early
    or masking a genuinely malformed block. Replaces every line spanned by a
    fence (open through close, inclusive) with a blank line, so downstream
    regex *positions* (offsets within the returned text) stay meaningful for
    anything derived from it. Line-based (not a single whole-text regex) so
    CRLF line endings and a closing fence longer than the opening one both
    strip correctly; a fence left unterminated to EOF is blanked to EOF too,
    matching CommonMark's own unterminated-fence behavior.
    """
    lines = text.split('\n')
    out = []
    i, n = 0, len(lines)
    while i < n:
        probe = lines[i][:-1] if lines[i].endswith('\r') else lines[i]
        opener = _FENCE_OPEN_RE.match(probe)
        if opener is None:
            out.append(lines[i])
            i += 1
            continue
        fence_char, open_len = opener.group(2)[0], len(opener.group(2))
        closer_re = re.compile(r'^[ \t]*' + re.escape(fence_char) + '{' + str(open_len) + r',}[ \t]*$')
        out.append('')
        i += 1
        while i < n:
            probe = lines[i][:-1] if lines[i].endswith('\r') else lines[i]
            out.append('')
            i += 1
            if closer_re.match(probe):
                break
    return '\n'.join(out)


def check_adapter_blocks(cache=None):
    """Every skills/<name>/SKILL.md where <name> ends with '-context' (the
    *-context family, e.g. ticket-context) must have a '## Adapters' section.

    Within that section, each '### <Provider>' sub-heading starts one adapter
    block (running to the next '###'/'##'/EOF) that must carry, in this exact
    order, four bold-labeled fields: **Trigger**, **Fetch**,
    **Extract → block fields**, **Degrade**. Fenced code blocks (used to show
    authors the adapter template) are excluded from this structural scan —
    see _strip_fenced_code_blocks.
    """
    skills_dir = ROOT / "skills"
    skills_cache = cache[1] if cache is not None else None
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill_dir_name = skill_md.parent.name
        if not skill_dir_name.endswith("-context"):
            continue
        if skills_cache is not None and skill_md in skills_cache:
            text = skills_cache[skill_md]
            if text is None:
                fail(skill_md.relative_to(ROOT), "could not read file")
                continue
        else:
            text = skill_md.read_text(encoding="utf-8")
        text = _strip_fenced_code_blocks(text)

        heading = _ADAPTERS_HEADING_RE.search(text)
        if heading is None:
            fail(skill_md.relative_to(ROOT), "missing required '## Adapters' section")
            continue

        boundary = _H2_BOUNDARY_RE.search(text, heading.end())
        section = text[heading.end():boundary.start()] if boundary else text[heading.end():]

        providers = list(_H3_PROVIDER_RE.finditer(section))
        if not providers:
            fail(skill_md.relative_to(ROOT), "'## Adapters' section has zero '### <Provider>' blocks; at least one is required")
            continue
        for i, prov_match in enumerate(providers):
            provider = prov_match.group(1).strip()
            block_start = prov_match.end()
            block_end = providers[i + 1].start() if i + 1 < len(providers) else len(section)
            _check_adapter_block_field_order(skill_md, provider, section[block_start:block_end])


def _check_adapter_block_field_order(skill_md, provider, block):
    """Confirm the 4 required bold-labeled fields appear in `block`, in order.

    Searches for each label starting from just after the previous match, so a
    label that is either absent or appears before an earlier label (i.e. out
    of order) is reported the same way: as the first offending field.
    """
    cursor = 0
    for label in _ADAPTER_FIELD_LABELS:
        pat = re.compile(r'^[ \t]*-\s+\*\*' + re.escape(label) + r':\*\*', re.MULTILINE)
        match = pat.search(block, cursor)
        if match is None:
            fail(
                skill_md.relative_to(ROOT),
                f"### {provider} adapter block missing or out-of-order required field: {label!r}",
            )
            return
        cursor = match.end()


def check_catalog_completeness(cache=None):
    """Per-slice catalogs under agents/shared/ must list every skill in the right slice,
    and every agent must reference at least one slice catalog.

    Slice files and their skill-name prefix rules:
      principles.md  → skill names starting with 'principle-'
      languages.md   → skill names starting with 'language-'
      workflows.md   → skill names starting with 'workflow-' plus the '*-context' family

    Skills with unrecognised prefixes are assigned to principles.md by convention.
    """
    _SLICE_FILES = {
        "principles.md": ("principle-",),
        "languages.md": ("language-",),
        "workflows.md": ("workflow-",),
    }
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
        if sid.endswith("-context"):
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
                 " _NON_CODE_AGENTS at the top of validate.py.")


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
    """Every skills/principle-*/ must be referenced by at least one agent —
    either backticked in body text, or listed in an agent's 'skills:'
    frontmatter (unconditional preload wiring counts as wiring in its own
    right; a body mention is no longer required once a skill is preloaded).

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

    agent_data = []
    for f in agent_files:
        text = agents_cache[f] if agents_cache is not None else f.read_text(encoding="utf-8")
        fm = parse_frontmatter(f, text=text)
        fm_skills = fm.get("skills") if fm is not None else None
        agent_data.append((text, fm_skills if isinstance(fm_skills, list) else []))

    for skill_id in principle_skills:
        needle = f"`swe-workbench:{skill_id}`"
        entry = f"swe-workbench:{skill_id}"
        wired = any(
            needle in text or entry in fm_skills
            for text, fm_skills in agent_data
        )
        if not wired:
            fail(
                Path("agents") / "<unwired>",
                f"principle skill 'swe-workbench:{skill_id}' is not referenced by any "
                f"agent in agents/*.md — wire it into a relevant agent's "
                f"'## Principle consultation' list or 'skills:' frontmatter",
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


def check_hook_script_permissions():
    """Every hooks/*.sh and hooks/*.py must be executable.

    hooks.json now always spells out an explicit interpreter (bash/python3),
    so the exec bit is no longer load-bearing for hook invocation itself —
    but it must stay set so a script also works when run directly (e.g. by a
    developer debugging it, or a future caller that invokes it bare). This
    closes a real gap: skill_usage_record.sh, skill_usage_flush.sh, and
    workflow_resume_hint.sh previously had zero exec-bit coverage anywhere
    in this repo's checks or tests (#557).

    Checks the exec bit only (os.access, matching check_bin_wrappers() below)
    rather than an exact 0755 mode: a checkout under umask 002 legitimately
    produces 0775 for a file git tracks as executable, and that must not be
    a spurious failure unrelated to any file actually edited.
    """
    hooks_dir = ROOT / "hooks"
    for script in sorted(list(hooks_dir.glob("*.sh")) + list(hooks_dir.glob("*.py"))):
        if not os.access(script, os.X_OK):
            fail(script.relative_to(ROOT), "must be executable (chmod +x)")


# Every bin/ wrapper must be invokable as a bare command once <plugin>/bin is
# on PATH: exec-bit set, a #!/usr/bin/env <interp> shebang (any interpreter,
# not just bash — see docs/plugin-platform-decisions.md), and the
# swe-workbench- prefix that is the only guard against colliding with a
# user's own PATH entries (bin/ has no other enforcement mechanism for it).
_SHEBANG_RE = re.compile(r'^#!/usr/bin/env \S+\n')


def check_bin_wrappers():
    bin_dir = ROOT / "bin"
    if not bin_dir.is_dir():
        return
    for wrapper in sorted(bin_dir.iterdir()):
        if not wrapper.is_file():
            continue
        if wrapper.name == "README.md":
            continue
        rel = wrapper.relative_to(ROOT)
        if not wrapper.name.startswith("swe-workbench-"):
            fail(rel, "bin/ wrapper must be prefixed swe-workbench-")
            continue
        if wrapper.suffix in (".sh", ".py"):
            fail(rel, "bin/ wrapper must be a bare command name, not carry a .sh/.py extension")
            continue
        if not os.access(wrapper, os.X_OK):
            fail(rel, "bin/ wrapper is not executable (chmod +x)")
        try:
            with wrapper.open(encoding="utf-8") as fh:
                first_line = fh.readline()
        except OSError as exc:
            fail(rel, f"could not read wrapper: {exc}")
            continue
        if not _SHEBANG_RE.match(first_line):
            fail(rel, "bin/ wrapper must start with a #!/usr/bin/env <interp> shebang")

    # #571 collapsed runtime/ into bin/ — the wrapper/script split is retired.
    # A reappearing runtime/ means that split is being silently reintroduced.
    runtime_dir = ROOT / "runtime"
    if runtime_dir.is_dir():
        fail(
            runtime_dir.relative_to(ROOT),
            "runtime/ must not exist — scripts live directly in bin/ as bare "
            "swe-workbench-<name> commands (see #571); do not recreate the "
            "wrapper/script split",
        )


# ──────────────────────────────────────────────
# Dependency-flow cycle checker
# ──────────────────────────────────────────────

_CYCLE_MENTION_RE = re.compile(r'`swe-workbench:([\w-]+)`')
# Backtick-delimited slash-command refs are async handoffs, not activations.
# Both backticks are required to avoid matching Unix paths (e.g. scripts/validate.py).
_SLASH_CMD_RE = re.compile(r'`/(?:swe-workbench:)?[\w-]+`')
# Action words that signal an activation (case-insensitive).
_ACTION_RE = re.compile(
    r'\b(invoke|activate|apply|execute via|dispatch|delegate|compose|consult|run)\b',
    re.IGNORECASE,
)
# Pointer/reference words that exclude a line from being an edge.
_POINTER_RE = re.compile(
    r'\b(see|defer to|recommend|like|per |unlike|e\.g\.|cf\.|analogous|mirror|'
    r'follows the|precedent|such as|similar to|counterpart|note them)\b',
    re.IGNORECASE,
)


def _build_dep_graph(cache):
    """Return adjacency dict: {(kind, id): set of (kind, id)} for action-cued activations."""
    root = ROOT
    agents_cache, skills_cache = cache[0], cache[1]

    skills_dir = root / "skills"
    agents_dir = root / "agents"
    commands_dir = root / "commands"

    # Pre-build resolution index: id -> (kind, id)
    resolvable = {}
    for p in skills_dir.glob("*/SKILL.md"):
        resolvable[p.parent.name] = ("skill", p.parent.name)
    for p in agents_dir.glob("*.md"):
        if p.parent.name == "shared":
            continue
        if p.stem not in resolvable:
            resolvable[p.stem] = ("agent", p.stem)

    graph = {}

    def _scan(src_node, text):
        for line in text.splitlines():
            # Skip @-include lines — pure file composition, not activations.
            if line.lstrip().startswith('@'):
                continue
            # Strip slash-command tokens (async handoffs) before checking for
            # action cues and swe-workbench refs. Stripping rather than skipping
            # the whole line preserves real activation edges that co-occur with
            # a slash hint (e.g. "invoke `swe-workbench:x` (then run `/review`)").
            clean = _SLASH_CMD_RE.sub('', line)
            if not _ACTION_RE.search(clean):
                continue
            if _POINTER_RE.search(clean):
                continue
            for mid in _CYCLE_MENTION_RE.findall(clean):
                dst_node = resolvable.get(mid)
                if dst_node is None or dst_node == src_node:
                    continue
                graph.setdefault(src_node, set()).add(dst_node)

    # Commands
    for cmd_md in sorted(commands_dir.glob("*.md")):
        src = ("command", cmd_md.stem)
        try:
            text = cmd_md.read_text(encoding="utf-8")
        except OSError:
            continue
        _scan(src, text)

    # Skills
    for skill_md, text in skills_cache.items():
        if skill_md.parent.parent != skills_dir:
            continue
        if text is None:
            continue
        src = ("skill", skill_md.parent.name)
        _scan(src, text)

    # Agents (non-shared)
    for agent_md, text in agents_cache.items():
        if agent_md.parent.name == "shared":
            continue
        if text is None:
            continue
        src = ("agent", agent_md.stem)
        _scan(src, text)

    return graph


def check_no_cycles(cache=None):
    """Fail if the action-cued activation graph contains a cycle."""
    if cache is None:
        cache = _build_cache()
    graph = _build_dep_graph(cache)

    # DFS with white/gray/black coloring.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}
    stack = []
    reported = set()

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for neighbor in sorted(graph.get(node, set())):
            if color.get(neighbor) == GRAY:
                # Back-edge found — extract cycle from stack.
                cycle_start = stack.index(neighbor)
                cycle = stack[cycle_start:] + [neighbor]
                key = tuple(cycle)
                if key not in reported:
                    reported.add(key)
                    path = " -> ".join(f"{k}:{i}" for k, i in cycle)
                    fail(
                        Path("(dependency graph)"),
                        f"dependency cycle: {path} — break the back-edge "
                        f"(an activated artifact must not activate its activator)",
                    )
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor)
        stack.pop()
        color[node] = BLACK

    all_nodes = set(graph.keys()) | {n for nbrs in graph.values() for n in nbrs}
    for node in sorted(all_nodes):
        if color.get(node, WHITE) == WHITE:
            dfs(node)


def check_plan_mode_workflow_embedding():
    """Every command that activates workflow-development Mode A must instruct embedding the
    ## Workflow section covering the ExitPlanMode path — otherwise the section is silently
    dropped under built-in plan mode (#423).

    Note: gate fires when all three signals appear anywhere in the document. A command that
    mentions 'Mode A' only in a 'Skip Mode A if …' clause without activating it will produce
    a false positive if ExitPlanMode is also absent. Today no such command exists; add the
    clause if one is introduced.
    """
    commands_dir = ROOT / "commands"
    if not commands_dir.is_dir():
        fail(Path("commands"), "directory missing — cannot check plan-mode workflow embedding (#423)")
        return
    wf_ref = re.compile(r'`swe-workbench:workflow-development`')
    mode_a = re.compile(r'\bMode A\b')
    clause = "ExitPlanMode"
    for cmd_md in sorted(commands_dir.glob("*.md")):
        try:
            text = cmd_md.read_text(encoding="utf-8")
        except OSError:
            fail(cmd_md.relative_to(ROOT), "could not read file")
            continue
        if wf_ref.search(text) and mode_a.search(text) and clause not in text:
            fail(
                cmd_md.relative_to(ROOT),
                "activates workflow-development Mode A but does not mention ExitPlanMode in the "
                "embedding instruction — under built-in plan mode the ## Workflow section is "
                "silently dropped (#423). Add the robustness clause covering both authoring paths.",
            )


def check_workflow_full_fidelity_mandate():
    """SKILL.md Mode A must mandate verbatim reproduction of the Workflow template, and
    the template header must carry 'do not abridge' — locks fix for #455.

    Two invariants checked:
    1. The '## Plan-Time Behavior (Mode A)' section of workflow-development/SKILL.md
       must contain both 'in full' and 'verbatim' (the explicit no-summarize mandate).
    2. The header of templates/plan-workflow-section.md (before the first ````markdown
       fence) must contain 'do not abridge' (the instruction travels with the template).
    """
    skill_md = ROOT / "skills" / "workflow-development" / "SKILL.md"
    if not skill_md.is_file():
        fail(skill_md.relative_to(ROOT),
             "missing — cannot check Mode A full-fidelity mandate (#455)")
        skill_text = None
    else:
        try:
            skill_text = skill_md.read_text(encoding="utf-8")
        except OSError:
            fail(skill_md.relative_to(ROOT), "could not read file")
            skill_text = None
    if skill_text is not None:
        mode_a_marker = "## Plan-Time Behavior (Mode A)"
        idx = skill_text.find(mode_a_marker)
        if idx < 0:
            fail(
                skill_md.relative_to(ROOT),
                "section '## Plan-Time Behavior (Mode A)' not found — "
                "cannot locate Mode A full-fidelity mandate (#455).",
            )
        else:
            next_h2 = skill_text.find("\n## ", idx + len(mode_a_marker))
            section = skill_text[idx:next_h2] if next_h2 >= 0 else skill_text[idx:]
            # Fail if either token is absent — both are required.
            if "in full" not in section or "verbatim" not in section:
                fail(
                    skill_md.relative_to(ROOT),
                    "Mode A paragraph is missing the full-fidelity mandate — the section must "
                    "contain both 'in full' and 'verbatim' to prevent the orchestrator from "
                    "condensing the ## Workflow template (#455).",
                )

    template_md = ROOT / "skills" / "workflow-development" / "templates" / "plan-workflow-section.md"
    if not template_md.is_file():
        fail(template_md.relative_to(ROOT),
             "missing — cannot check template full-fidelity header (#455)")
        tmpl_text = None
    else:
        try:
            tmpl_text = template_md.read_text(encoding="utf-8")
        except OSError:
            fail(template_md.relative_to(ROOT), "could not read file")
            tmpl_text = None
    if tmpl_text is not None:
        fence_idx = tmpl_text.find("````markdown")
        header = tmpl_text[:fence_idx] if fence_idx >= 0 else tmpl_text
        if "do not abridge" not in header:
            fail(
                template_md.relative_to(ROOT),
                "template header is missing 'do not abridge' — the no-summarize instruction "
                "must travel with the template so the mandate is visible at the point of use (#455).",
            )


def check_browser_tool_gate(cache=None):
    """Any agent or command referencing browser MCP tools must carry a BLOCKED: sentinel
    and a per-backend install hint — enforces the hard gate from #364.

    Signals that trigger the check: browser_snapshot, read_console_messages,
    read_network_requests, mcp__*chrome*, @playwright/mcp.
    Required when triggered: BLOCKED: string + a per-backend install hint,
    either `claude mcp add <name> npx <package>@latest` (preferred) or the
    legacy `npx <package>@latest` form.
    """
    agents_cache = cache[0] if cache is not None else None
    for subdir, use_cache in ((ROOT / "agents", True), (ROOT / "commands", False)):
        if not subdir.is_dir():
            continue
        for md in sorted(subdir.glob("*.md")):
            if use_cache and agents_cache is not None and md in agents_cache:
                text = agents_cache[md]
                if text is None:
                    fail(md.relative_to(ROOT), "could not read file")
                    continue
            else:
                try:
                    text = md.read_text(encoding="utf-8")
                except OSError:
                    fail(md.relative_to(ROOT), "could not read file")
                    continue
            if not _BROWSER_MCP_SIGNALS.search(text):
                continue
            # Claude-in-Chrome is in-harness (no installable package); if the file's
            # only browser signal is claude-in-chrome references, waive the install-hint.
            stripped = _CLAUDE_IN_CHROME_ONLY.sub("", text)
            if not _BROWSER_MCP_SIGNALS.search(stripped):
                continue
            rel = md.relative_to(ROOT)
            if "BLOCKED:" not in text:
                fail(
                    rel,
                    "references browser MCP tools but missing BLOCKED: sentinel — "
                    "add a hard-gate that returns BLOCKED: with a per-backend install hint "
                    "(e.g. `claude mcp add playwright npx @playwright/mcp@latest`) "
                    "when the required MCP server is absent (#364)",
                )
            elif not _BROWSER_INSTALL_HINTS.search(text):
                fail(
                    rel,
                    "references browser MCP tools and has BLOCKED: but missing a per-backend install hint — "
                    "add `claude mcp add playwright npx @playwright/mcp@latest` or "
                    "`claude mcp add chrome-devtools-mcp npx chrome-devtools-mcp@latest` (#364)",
                )


def check_lsp_tool_gate(cache=None):
    """Any agent granting LSP in its tools: frontmatter must preload
    agents/shared/lsp.md, and that shared file must carry the LSP-unavailable
    fallback sentence (#559).

    Only ever inspects the tools: frontmatter value (parsed via
    parse_frontmatter, either the scalar split on ',' or the YAML sequence
    form, with exact-token membership) — never a body-text regex.
    agents/shared/principles.md uses "LSP" for the Liskov Substitution
    Principle, so a body-text match would false-positive on every agent
    preloading principle-solid.

    If no agent grants LSP, this returns without requiring the shared file to
    exist — that keeps the check from ossifying a future removal of LSP.
    """
    agents_cache = cache[0] if cache is not None else None
    agents_dir = ROOT / "agents"
    if not agents_dir.is_dir():
        return

    granting = []
    for md in sorted(agents_dir.glob("*.md")):
        if agents_cache is not None and md in agents_cache:
            text = agents_cache[md]
            if text is None:
                fail(md.relative_to(ROOT), "could not read file")
                continue
        else:
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                fail(md.relative_to(ROOT), "could not read file")
                continue
        fm = parse_frontmatter(md, text=text)
        if not fm:
            continue
        tools = fm.get("tools")
        if isinstance(tools, str):
            tokens = {t.strip() for t in tools.split(",")}
        elif isinstance(tools, list):
            tokens = {str(t).strip() for t in tools}
        else:
            continue
        if "LSP" not in tokens:
            continue
        granting.append((md, text))

    if not granting:
        return

    shared_path = agents_dir / "shared" / "lsp.md"
    try:
        shared_text = shared_path.read_text(encoding="utf-8")
    except OSError:
        shared_text = None

    if shared_text is None:
        fail(
            shared_path.relative_to(ROOT),
            "one or more agents grant LSP in tools: but agents/shared/lsp.md "
            "is missing — add the shared LSP doc with the fallback sentence (#559)",
        )
    elif _LSP_FALLBACK not in shared_text:
        fail(
            shared_path.relative_to(ROOT),
            f"missing the fallback sentence {_LSP_FALLBACK!r} (#559)",
        )

    for md, text in granting:
        if _LSP_SHARED_INCLUDE not in text:
            fail(
                md.relative_to(ROOT),
                f"grants LSP in tools: but body is missing the "
                f"{_LSP_SHARED_INCLUDE!r} include (#559)",
            )


# ──────────────────────────────────────────────
# echo/printf shell footgun (#549)
# ──────────────────────────────────────────────

_BASH_BLOCK_RE = re.compile(r'^```bash[ \t]*\n(.*?)\n^```[ \t]*$', re.MULTILINE | re.DOTALL)
# echo at a command position: line start, or after ; & | ( { ) — a bare '&'
# also covers '&&' and a bare '|' also covers '||' since both share their last
# char; ')' covers a `case` arm ('a) echo ...'), '{' covers a brace group
# ('{ echo ...; }'). An optional shell keyword (if/elif/then/else/do/while/
# until) may sit between the position marker and 'echo' (e.g. 'elif echo ...
# ; then') — the keyword itself must be at that same command position, so a
# keyword mentioned in a trailing comment ('# if echo fails') still can't
# reach this branch.
_ECHO_CMD_POS_RE = re.compile(
    r'(?:^|[;&|({)])\s*(?:(?:if|elif|then|else|do|while|until)\s+)?echo(?=\s|$)'
)
# Matches a bare variable reference ($VAR, ${VAR}) or a command/process
# substitution opener ($( or a backtick) — the same escape-expansion risk
# applies to whatever string ends up in echo's argument, not just bare
# variables (PR #564 review follow-up).
_VAR_REF_RE = re.compile(r'\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\(|`')
_SEPARATOR_CHARS = frozenset(' \t;&|')


def _redirect_target_hazard(window, j, n):
    """From `j` (first char after a redirect operator), skip whitespace,
    extract the target token, and return (new_index, is_hazard) — `is_hazard`
    is False only for a `/dev/null` target (quotes stripped before compare)."""
    while j < n and window[j] in ' \t':
        j += 1
    k = j
    while k < n and window[k] not in _SEPARATOR_CHARS:
        k += 1
    target = window[j:k].strip('"\'')
    return k, target != '/dev/null'


def _find_echo_hazard_end(window):
    """Quote-aware scan of `window` (the text right after 'echo') for the
    first real pipe/redirect hazard, stopping at the first unquoted command
    separator (';', '&&', bare '&', '||') with no hazard found.

    Quote-awareness matters because the JSON this check exists to protect
    routinely contains a literal ';' inside a quoted string — a naive
    unquoted `;`-split would truncate the scan before reaching a real pipe
    or redirect that comes after it on the same line.

    Returns the hazard's start offset into `window`, or None if the command
    ends (separator or end-of-line) with no real pipe/redirect found.
    """
    quote = None
    i, n = 0, len(window)
    while i < n:
        c = window[i]
        if quote:
            if c == '\\' and quote == '"' and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ('"', "'"):
            quote = c
            i += 1
            continue
        if c == ';':
            return None
        if c == '&':
            if i + 1 < n and window[i + 1] == '>':
                # '&>'/'&>>' — combined stdout+stderr redirect to a real
                # target; same hazard rules as a bare '>' (PR #564 review:
                # checking '&' before '>' previously misread this as a bare
                # background job / '&&' and bailed before the real redirect).
                j = i + 2
                if j < n and window[j] == '>':
                    j += 1
                if j < n and window[j] == '&':
                    i = j + 1  # fd dup ('&>&2') — not a hazard, keep scanning
                    continue
                k, is_hazard = _redirect_target_hazard(window, j, n)
                if not is_hazard:
                    i = k
                    continue
                return i
            return None  # bare '&' (background) or '&&' — both end the command
        if c == '|':
            if i + 1 < n and window[i + 1] == '|':
                return None  # '||' — logical OR, not a hazard
            return i  # real pipe
        if c == '>':
            j = i + 1
            if j < n and window[j] == '>':
                j += 1
            if j < n and window[j] == '&':
                i = j + 1  # fd dup ('>&2') — not a hazard, keep scanning
                continue
            k, is_hazard = _redirect_target_hazard(window, j, n)
            if not is_hazard:
                i = k
                continue
            return i  # real file redirect
        i += 1
    return None


def _echo_hazard_in_line(line):
    """True if `line` pipes or redirects a variable through `echo` to a real
    destination — not `/dev/null`, not an fd dup (`>&`), not `||`."""
    for m in _ECHO_CMD_POS_RE.finditer(line):
        window = line[m.end():]
        hazard_end = _find_echo_hazard_end(window)
        if hazard_end is None:
            continue
        if _VAR_REF_RE.search(window[:hazard_end]):
            return True
    return False


# printf at a command position — same rules as _ECHO_CMD_POS_RE.
_PRINTF_CMD_POS_RE = re.compile(
    r'(?:^|[;&|({)])\s*(?:(?:if|elif|then|else|do|while|until)\s+)?printf(?=\s)'
)
# A whole argument token that is NOTHING but a variable reference (optionally
# single/double-quoted) — the hazard is $VAR used as printf's FORMAT string,
# not as an argument to a literal '%s'.
_BARE_VAR_TOKEN_RE = re.compile(r'^(["\']?)(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)\1(?=\s|$)')
_PRINTF_DASH_V_RE = re.compile(r'^-v\s+\S+\s+')


def _printf_hazard_in_line(line):
    """True if `line` invokes `printf` with a bare variable as the format
    string. `$VAR` then IS the format — a literal `%s` inside it reads a
    nonexistent argument, and `%n` is a memory-write primitive in some
    `printf(1)` implementations (PR #564 review follow-up)."""
    for m in _PRINTF_CMD_POS_RE.finditer(line):
        rest = line[m.end():].lstrip(' \t')
        v_match = _PRINTF_DASH_V_RE.match(rest)
        if v_match:
            rest = rest[v_match.end():]  # `-v NAME` assigns to a var instead
            # of stdout — the format string is the NEXT token, not NAME.
        if _BARE_VAR_TOKEN_RE.match(rest):
            return True
    return False


def _ends_with_continuation(line):
    """True if `line` ends in an odd number of trailing backslashes — bash
    line-continuation requires the final backslash be unescaped; trailing
    backslashes pair up as literal characters except a possible odd one out,
    which escapes the newline (PR #564 review follow-up: a fixed 1-vs-2
    suffix check missed this for 3+ trailing backslashes)."""
    trailing = len(line) - len(line.rstrip('\\'))
    return trailing % 2 == 1


def _join_bash_continuations(block_lines):
    """Yield (start_offset, logical_line) pairs, joining a line ending in an
    unescaped trailing '\\' with the physical line(s) that follow — bash
    treats '\\<newline>' as a line-continuation, so a hazard can span what
    look like two independent physical lines (PR #564 review follow-up).
    A trailing '\\\\' (escaped backslash, i.e. a literal backslash char) is
    NOT a continuation.
    """
    i, n = 0, len(block_lines)
    while i < n:
        start = i
        parts = [block_lines[i]]
        while _ends_with_continuation(parts[-1]) and i + 1 < n:
            i += 1
            parts.append(block_lines[i])
        logical = ' '.join(p[:-1] if p.endswith('\\') else p for p in parts)
        yield start, logical
        i += 1


def _scan_bash_blocks_for_hazard(cache, is_hazard_line, message):
    """Scan fenced ```bash blocks under skills/, commands/, agents/ (including
    reference/ subdirs) and fail() on any line where `is_hazard_line` returns
    True. `message` is called with the 1-indexed line number and must return
    the failure reason string.

    docs/ is intentionally excluded from the scanned roots — the sibling doc
    page must show the bad pattern as a worked example without tripping this
    guard (#549). Known limitation: scans raw lines with no heredoc-body
    awareness, so a worked "here's the wrong way" example placed inside a
    heredoc (rather than behind a '#' comment, which the command-position
    regex already exempts) would be misread as a real hazard — narrow and
    currently theoretical (PR #564 review follow-up).
    """
    agents_cache = cache[0] if cache is not None else None
    skills_cache = cache[1] if cache is not None else None
    roots = (
        (ROOT / "skills", skills_cache),
        (ROOT / "commands", None),
        (ROOT / "agents", agents_cache),
    )
    for base, sub_cache in roots:
        if not base.is_dir():
            continue
        for md in sorted(base.rglob("*.md")):
            if sub_cache is not None and md in sub_cache:
                text = sub_cache[md]
                if text is None:
                    continue  # unreadable — already reported by another check
            else:
                try:
                    text = md.read_text(encoding="utf-8")
                except OSError:
                    continue
            for block_match in _BASH_BLOCK_RE.finditer(text):
                block = block_match.group(1)
                block_start_line = text.count('\n', 0, block_match.start(1)) + 1
                for offset, line in _join_bash_continuations(block.splitlines()):
                    if is_hazard_line(line):
                        fail(md.relative_to(ROOT), message(block_start_line + offset))


def check_no_echo_var_hazard(cache=None):
    """Flag bash blocks in skills/, commands/, agents/ that pipe or redirect a
    variable through `echo` — zsh (the user's likely login shell) expands
    backslash escapes in echo's argument, corrupting embedded JSON (#549).
    Use printf '%s' instead; see docs/shell-echo-vs-printf.md.
    """
    _scan_bash_blocks_for_hazard(
        cache,
        _echo_hazard_in_line,
        lambda ln: (
            f"line {ln}: bash block pipes/redirects a variable through 'echo' — "
            f"zsh expands backslash escapes and corrupts JSON; use printf '%s' "
            f"(see docs/shell-echo-vs-printf.md)"
        ),
    )


def check_no_printf_var_format(cache=None):
    """Flag bash blocks in skills/, commands/, agents/ that pass a bare
    variable as `printf`'s format string — `printf "$VAR"` is the naive (and
    dangerous) translation of `echo "$VAR"`: `$VAR` becomes the FORMAT, so a
    literal `%s` inside it reads a nonexistent argument, and `%n` is a
    memory-write primitive in some `printf(1)` implementations. Always
    `printf '%s' "$VAR"` — see docs/shell-echo-vs-printf.md.
    """
    _scan_bash_blocks_for_hazard(
        cache,
        _printf_hazard_in_line,
        lambda ln: (
            f"line {ln}: bash block passes a bare variable as printf's format "
            f"string — a literal %s/%n inside it is read as a format directive; "
            f"use printf '%s' \"$VAR\" (see docs/shell-echo-vs-printf.md)"
        ),
    )


# ──────────────────────────────────────────────
# Un-enumerated /tmp scratch write gate (#552)
# ──────────────────────────────────────────────

# A redirect (`>`/`>>`) or `--body-file` flag whose target is a LITERAL
# /tmp/... path (not a variable reference) — captures the target token,
# quotes stripped, for the sanctioned-prefix check below. A variable-rooted
# target ("$RUN_DIR/x", "$STATE_FILE") never matches: it doesn't start with
# the literal text "/tmp/".
_TMP_WRITE_TARGET_RE = re.compile(
    r'(?:>{1,2}|--body-file[= ])\s*"?(/tmp/\S+?)"?(?=\s|$|[;&|)])'
)

# Sanctioned, enumerable prefixes: the run-dir root itself, the two PR-scoped
# state directories, and swe-workbench-clean-state-files' own Path-B single-file-writer
# allowlist (bin/swe-workbench-clean-state-files:81) — kept in sync with that regex
# by hand, since the two files serve different audiences (shell vs. this
# Python gate) and a shared source would be more indirection than the four
# lines it'd save.
_SANCTIONED_TMP_PREFIX_RE = re.compile(
    r'^/tmp/(?:'
    r'swe-workbench-run/|swe-workbench-pr-review/|swe-workbench-address-feedback/|'
    r'(?:capture|report-issue|audit-emit|extend|hotfix|cleanup-followup|bug-triage)-'
    r')'
)


def _tmp_write_hazard_in_line(line):
    """True if `line` redirects to, or passes `--body-file` with, a literal
    `/tmp/...` path that is neither under the run-dir root / a PR-scoped
    state dir, nor one of clean-state-files.sh's sanctioned basename
    prefixes. Such a path is un-enumerable by construction (#552) — nothing
    can ever reap it by name, and nothing bounds two concurrent flows from
    silently clobbering it."""
    for m in _TMP_WRITE_TARGET_RE.finditer(line):
        if not _SANCTIONED_TMP_PREFIX_RE.match(m.group(1)):
            return True
    return False


def check_no_unenumerated_tmp_write(cache=None):
    """Flag bash blocks in skills/, commands/, agents/ that write to a literal
    /tmp/... path outside both $RUN_DIR (bin/swe-workbench-new-run-dir) and the
    sanctioned PR-keyed prefixes (bin/swe-workbench-clean-state-files). This is the
    regression gate for #552: without it, a new shipped-prose call site can
    reintroduce a global, never-reaped path like the old /tmp/payload.json.
    """
    _scan_bash_blocks_for_hazard(
        cache,
        _tmp_write_hazard_in_line,
        lambda ln: (
            f"line {ln}: bash block writes to a literal /tmp/... path that is "
            f"neither $RUN_DIR-rooted nor a sanctioned PR-keyed prefix — "
            f"allocate $RUN_DIR via swe-workbench-new-run-dir and write under "
            f"it instead (see bin/swe-workbench-new-run-dir)"
        ),
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
    check_skill_cap_headroom(cache=cache)
    check_orchestrator_flag_earned(cache=cache)
    check_skill_trigger_fixtures()
    check_agents(cache=cache)
    check_commands()
    check_agent_skill_refs(cache=cache)
    check_preloaded_skills(cache=cache)
    check_command_skill_refs()
    check_skill_skill_refs(cache=cache)
    check_bare_actionable_refs(cache=cache)
    check_workflow_development_activation_contract()
    check_plan_mode_workflow_embedding()
    check_workflow_full_fidelity_mandate()
    check_catalog_completeness(cache=cache)
    check_adapter_blocks(cache=cache)
    check_shared_includes_not_blockquoted(cache=cache)
    check_template_placeholders(cache=cache)
    check_unwired_principle_skills(cache=cache)
    check_examples()
    check_hook_scripts()
    check_hook_script_permissions()
    check_bin_wrappers()
    check_test_subprocess_env()
    check_no_cycles(cache=cache)
    check_browser_tool_gate(cache=cache)
    check_lsp_tool_gate(cache=cache)
    check_no_echo_var_hazard(cache=cache)
    check_no_printf_var_format(cache=cache)
    check_no_unenumerated_tmp_write(cache=cache)

    if WARNINGS:
        print(f"WARNING — {len(WARNINGS)} skill(s) near their line cap:")
        for w in WARNINGS:
            print(w)
        print()

    if FAILURES:
        print(f"FAILED — {len(FAILURES)} issue(s) found:", file=sys.stderr)
        for f in FAILURES:
            print(f, file=sys.stderr)
        sys.exit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()
