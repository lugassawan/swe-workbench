"""Shared test helpers — importable from test modules."""

import json
from pathlib import Path


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
                    "hooks": [{"type": "command", "command": "exit 0"}],
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
    shared_dir = agents_dir / "shared"
    shared_dir.mkdir(exist_ok=True)

    # Build catalog slices listing every skill in skills_dir
    def _lines(ids):
        return "\n".join(f"- `swe-workbench:{sid}` — {sid} skill" for sid in ids)

    if catalog is not None:
        # Legacy convenience: caller-supplied catalog text goes to principles.md;
        # other slices get empty stubs so the validator sees valid (if empty) files.
        # IMPORTANT: only pass skills with unrecognised prefixes (not principle-/language-/workflow-)
        # in catalog= text — otherwise the wrong-slice check in check_catalog_completeness will fire.
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
        for agent in agents:
            name = agent["name"]
            fm_lines = "\n".join(f"{k}: {v}" for k, v in agent.items())
            body = f"---\n{fm_lines}\n---\n\n> See @./shared/principles.md for the skill catalog.\n"
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
