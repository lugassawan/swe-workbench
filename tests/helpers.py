"""Shared test helpers — importable from test modules."""

import json
from pathlib import Path


def sentinel_block(text: str, fragment_name: str) -> str | None:
    """Return the inner content of the sentinel block for *fragment_name*
    (e.g. "lsp.md" or "shared/agents/lsp.md") in *text*, or None if the BEGIN
    marker is absent or has no matching END marker.

    Use together with a source-file read to assert content equality — the
    property that would have caught issue #619 (a plain include *string* was
    asserted present, never that it resolved to real content).
    """
    full_name = (
        fragment_name if fragment_name.startswith("shared/agents/")
        else f"shared/agents/{fragment_name}"
    )
    begin_marker = f"<!-- BEGIN {full_name} -->\n"
    idx = text.find(begin_marker)
    if idx == -1:
        return None
    start = idx + len(begin_marker)
    end_marker = f"<!-- END {full_name} -->"
    end_idx = text.find(end_marker, start)
    if end_idx == -1:
        return None
    return text[start:end_idx]


def make_plugin_tree(
    root: Path,
    *,
    skills: dict | None = None,
    agents: list[dict] | None = None,
    commands: list[dict] | None = None,
    plugin_json: dict | None = None,
    marketplace_json: dict | None = None,
    hooks_json: dict | None = None,
    catalog: str | None = None,
) -> Path:
    """Write a minimal valid plugin layout into *root*.

    Each keyword argument overrides one piece; omitted pieces get sane defaults.
    Returns root for convenience.
    """
    # plugin.json
    pj = plugin_json if plugin_json is not None else {
        "name": "test-plugin",
        "version": "1.0.0",
        "description": "Test plugin",
    }
    claude_plugin = root / ".claude-plugin"
    claude_plugin.mkdir(parents=True, exist_ok=True)
    (claude_plugin / "plugin.json").write_text(json.dumps(pj), encoding="utf-8")

    # marketplace.json
    mj = marketplace_json if marketplace_json is not None else {
        "plugins": [{"name": pj.get("name", "test-plugin"), "version": pj.get("version", "1.0.0")}]
    }
    (claude_plugin / "marketplace.json").write_text(json.dumps(mj), encoding="utf-8")

    # hooks/hooks.json
    hj = hooks_json if hooks_json is not None else {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{
                        "type": "command",
                        "command": 'bash "${CLAUDE_PLUGIN_ROOT}"/hooks/example.sh',
                    }],
                }
            ]
        }
    }
    hooks_dir = root / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    (hooks_dir / "hooks.json").write_text(json.dumps(hj), encoding="utf-8")

    # skills/
    skills_dir = root / "skills"
    skills_dir.mkdir(exist_ok=True)
    if skills is not None:
        for skill_name, body in skills.items():
            sd = skills_dir / skill_name
            sd.mkdir(exist_ok=True)
            (sd / "SKILL.md").write_text(body, encoding="utf-8")

    # agents/
    agents_dir = root / "agents"
    agents_dir.mkdir(exist_ok=True)
    shared_dir = root / "shared" / "agents"
    shared_dir.mkdir(parents=True, exist_ok=True)

    # The two sentinel-block source fragments (#619) — written unconditionally
    # so the `agents=` body generator below always has a real source file to
    # inline from, keeping any synthetic agent's blocks byte-identical to
    # their "source" within this same synthetic tree.
    (shared_dir / "skill-catalog-pointer.md").write_text(
        "Skill catalog pointer.\n", encoding="utf-8"
    )
    (shared_dir / "language-skill-required.md").write_text(
        "Language skill requirement.\n", encoding="utf-8"
    )

    # Build catalog slices listing every skill in skills_dir
    def _lines(ids):
        return "\n".join(f"- `swe-workbench:{sid}` — {sid} skill" for sid in ids)

    if catalog is not None:
        # Legacy convenience: caller-supplied catalog text goes to principles.md;
        # other slices get empty stubs so the validator sees valid (if empty) files.
        import re as _re
        _known = _re.findall(r"`swe-workbench:([\w-]+)`", catalog)
        _bad = [s for s in _known if any(s.startswith(p) for p in ("principle-", "language-", "workflow-")) or s == "ticket-context"]
        assert not _bad, (
            f"catalog= must not contain prefixed skills {_bad}; pass them via skills= so "
            "make_plugin_tree places them in the correct slice file automatically."
        )
        (shared_dir / "principles.md").write_text(catalog, encoding="utf-8")
        (shared_dir / "languages.md").write_text("\n", encoding="utf-8")
        (shared_dir / "workflows.md").write_text("\n", encoding="utf-8")
    else:
        on_disk = sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file())
        principles = [s for s in on_disk if s.startswith("principle-")]
        languages = [s for s in on_disk if s.startswith("language-")]
        workflows = [s for s in on_disk if s.startswith("workflow-") or s == "ticket-context"]
        # Skills with unrecognised prefixes land in principles (safe default)
        others = [s for s in on_disk if s not in principles and s not in languages and s not in workflows]
        principles = principles + others
        (shared_dir / "principles.md").write_text((_lines(principles) + "\n") if principles else "\n", encoding="utf-8")
        (shared_dir / "languages.md").write_text((_lines(languages) + "\n") if languages else "\n", encoding="utf-8")
        (shared_dir / "workflows.md").write_text((_lines(workflows) + "\n") if workflows else "\n", encoding="utf-8")

    if agents is not None:
        # #619: agent bodies must carry the sentinel-delimited blocks that
        # replaced the dead '@../shared/agents/*.md' includes, not the include
        # text itself (Claude Code never expands it). Every synthetic agent
        # gets the skill-catalog-pointer block; check_catalog_completeness's
        # reworked per-agent marker check also requires language-skill-required
        # on any agent whose stem isn't in validate._NON_CODE_AGENTS — none of
        # this helper's current callers build a product-manager-like fixture
        # via `agents=`, so there is no caller today that needs to opt out of
        # the language block (kept simple rather than adding an unused kwarg;
        # if a future test needs that scenario, write that one agent's body
        # directly instead of through this generator).
        pointer_content = (shared_dir / "skill-catalog-pointer.md").read_text(encoding="utf-8")
        language_content = (shared_dir / "language-skill-required.md").read_text(encoding="utf-8")
        for agent in agents:
            name = agent["name"]
            fm_lines = "\n".join(f"{k}: {v}" for k, v in agent.items())
            body = (
                f"---\n{fm_lines}\n---\n\n"
                f"<!-- BEGIN shared/agents/skill-catalog-pointer.md -->\n{pointer_content}"
                f"<!-- END shared/agents/skill-catalog-pointer.md -->\n\n"
                f"<!-- BEGIN shared/agents/language-skill-required.md -->\n{language_content}"
                f"<!-- END shared/agents/language-skill-required.md -->\n"
            )
            (agents_dir / f"{name}.md").write_text(body, encoding="utf-8")

    # commands/
    commands_dir = root / "commands"
    commands_dir.mkdir(exist_ok=True)
    if commands is not None:
        for cmd in commands:
            name = cmd["name"]
            fm_lines = "\n".join(f"{k}: {v}" for k, v in cmd.items() if k != "name")
            body = f"---\n{fm_lines}\n---\n\nCommand body.\n"
            (commands_dir / f"{name}.md").write_text(body, encoding="utf-8")

    return root
