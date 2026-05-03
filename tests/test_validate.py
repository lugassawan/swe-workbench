"""Tests for scripts/validate.py — every check_* function covered (issue #76)."""

import json
from pathlib import Path

import pytest

import validate
from helpers import make_plugin_tree


# ──────────────────────────────────────────────
# parse_frontmatter
# ──────────────────────────────────────────────

class TestParseFrontmatter:
    def test_valid_two_key_block(self, tmp_path):
        text = "---\nname: my-skill\ndescription: A skill\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm == {"name": "my-skill", "description": "A skill"}

    def test_missing_leading_dashes(self, tmp_path):
        text = "name: my-skill\ndescription: A skill\n---\nBody"
        assert validate.parse_frontmatter(tmp_path / "x.md", text=text) is None

    def test_missing_closing_dashes(self, tmp_path):
        text = "---\nname: my-skill\ndescription: A skill\nBody"
        assert validate.parse_frontmatter(tmp_path / "x.md", text=text) is None

    def test_lowercase_normalization(self, tmp_path):
        text = "---\nName: my-skill\nDescription: A skill\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm is not None
        assert "name" in fm
        assert "description" in fm

    def test_hyphenated_key(self, tmp_path):
        text = "---\nallowed-tools: Read, Write\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm is not None
        assert "allowed-tools" in fm

    def test_single_line_yaml_body_with_newline_dashes(self, tmp_path):
        text = "---\nname: x\n---\nContent here"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm == {"name": "x"}


# ──────────────────────────────────────────────
# check_plugin_json
# ──────────────────────────────────────────────

class TestCheckPluginJson:
    def test_valid_returns_dict(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        result = validate.check_plugin_json()
        assert isinstance(result, dict)
        assert len(validate.FAILURES) == 0

    def test_bad_json_triggers_failure(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        (root / ".claude-plugin" / "plugin.json").write_text("{bad json}", encoding="utf-8")
        validate.check_plugin_json()
        assert any("JSON parse error" in f for f in validate.FAILURES)

    def test_missing_version_triggers_failure(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, plugin_json={"name": "x", "description": "y"})
        validate.check_plugin_json()
        assert any("missing required field: 'version'" in f for f in validate.FAILURES)

    def test_missing_name_triggers_failure(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, plugin_json={"version": "1.0.0", "description": "y"})
        validate.check_plugin_json()
        assert any("missing required field: 'name'" in f for f in validate.FAILURES)

    def test_missing_description_triggers_failure(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, plugin_json={"name": "x", "version": "1.0.0"})
        validate.check_plugin_json()
        assert any("missing required field: 'description'" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_marketplace_json
# ──────────────────────────────────────────────

class TestCheckMarketplaceJson:
    def _plugin_data(self):
        return {"name": "test-plugin", "version": "1.0.0", "description": "d"}

    def test_matching_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        validate.check_marketplace_json(self._plugin_data())
        assert len(validate.FAILURES) == 0

    def test_empty_plugins_list(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, marketplace_json={"plugins": []})
        validate.check_marketplace_json(self._plugin_data())
        assert any("expected plugins[0]" in f for f in validate.FAILURES)

    def test_name_mismatch(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            marketplace_json={"plugins": [{"name": "wrong-name", "version": "1.0.0"}]},
        )
        validate.check_marketplace_json(self._plugin_data())
        assert any("name" in f for f in validate.FAILURES)

    def test_version_mismatch(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            marketplace_json={"plugins": [{"name": "test-plugin", "version": "9.9.9"}]},
        )
        validate.check_marketplace_json(self._plugin_data())
        assert any("version" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_hooks_json
# ──────────────────────────────────────────────

class TestCheckHooksJson:
    def test_valid_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        validate.check_hooks_json()
        assert len(validate.FAILURES) == 0

    def test_non_object_hooks_top_level(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, hooks_json={"hooks": ["not", "an", "object"]})
        validate.check_hooks_json()
        assert any("must be an object" in f for f in validate.FAILURES)

    def test_non_list_matchers(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, hooks_json={"hooks": {"PreToolUse": "not-a-list"}})
        validate.check_hooks_json()
        assert any("must be a list" in f for f in validate.FAILURES)

    def test_non_string_command(self, reset_validate):
        root = reset_validate
        bad = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": 42}]}
                ]
            }
        }
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("command" in f for f in validate.FAILURES)

    def test_non_string_matcher(self, reset_validate):
        root = reset_validate
        bad = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": 99, "hooks": [{"type": "command", "command": "exit 0"}]}
                ]
            }
        }
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("matcher" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_skills
# ──────────────────────────────────────────────

class TestCheckSkills:
    def _valid_skill(self, name="my-skill", extra_lines=0):
        body = f"---\nname: {name}\ndescription: A skill\n---\n"
        body += "x\n" * extra_lines
        return body

    def test_valid_skill_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._valid_skill("my-skill", extra_lines=5)})
        validate.check_skills()
        assert len(validate.FAILURES) == 0

    def test_missing_frontmatter_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": "No frontmatter here\n"})
        validate.check_skills()
        assert any("missing or malformed frontmatter" in f for f in validate.FAILURES)

    def test_missing_description_fails(self, reset_validate):
        root = reset_validate
        # Skill has name but no description
        make_plugin_tree(root, skills={"my-skill": "---\nname: my-skill\n---\n"})
        validate.check_skills()
        assert any("description" in f for f in validate.FAILURES)

    def test_frontmatter_name_mismatch_fails(self, reset_validate):
        root = reset_validate
        # dir name is "my-skill" but frontmatter name is "other-name"
        make_plugin_tree(root, skills={"my-skill": self._valid_skill("other-name")})
        validate.check_skills()
        assert any("does not match directory name" in f for f in validate.FAILURES)

    def test_non_orchestrator_over_150_lines_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._valid_skill("my-skill", extra_lines=200)})
        validate.check_skills()
        assert any("exceeds" in f for f in validate.FAILURES)

    def test_orchestrator_200_lines_passes(self, reset_validate):
        root = reset_validate
        body = "---\nname: my-skill\ndescription: A skill\norchestrator: true\n---\n"
        body += "x\n" * 195  # total ~200 lines
        make_plugin_tree(root, skills={"my-skill": body})
        validate.check_skills()
        assert len(validate.FAILURES) == 0

    def test_orchestrator_over_300_lines_fails(self, reset_validate):
        root = reset_validate
        body = "---\nname: my-skill\ndescription: A skill\norchestrator: true\n---\n"
        body += "x\n" * 296  # total ~301 lines
        make_plugin_tree(root, skills={"my-skill": body})
        validate.check_skills()
        assert any("exceeds" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_agents
# ──────────────────────────────────────────────

class TestCheckAgents:
    def test_valid_agent_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            agents=[{"name": "my-agent", "description": "An agent", "tools": "Read, Write"}],
        )
        validate.check_agents()
        assert len(validate.FAILURES) == 0

    def test_missing_description_fails(self, reset_validate):
        root = reset_validate
        # Write agent file manually without description
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "bad-agent.md").write_text(
            "---\nname: bad-agent\n---\n\n> See @./shared/skills.md\n", encoding="utf-8"
        )
        validate.check_agents()
        assert any("description" in f for f in validate.FAILURES)

    def test_skill_ref_without_skill_tool_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        # References swe-workbench skill but tools: lacks "Skill"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: An agent\ntools: Read, Write\n---\n"
            "\nUse `swe-workbench:foo` to do things.\n"
            "\n> See @./shared/skills.md\n",
            encoding="utf-8",
        )
        validate.check_agents()
        assert any("Skill" in f for f in validate.FAILURES)

    def test_skill_ref_with_skill_tool_passes(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: An agent\ntools: Read, Skill\n---\n"
            "\nUse `swe-workbench:foo` to do things.\n"
            "\n> See @./shared/skills.md\n",
            encoding="utf-8",
        )
        validate.check_agents()
        assert len(validate.FAILURES) == 0


# ──────────────────────────────────────────────
# check_commands
# ──────────────────────────────────────────────

class TestCheckCommands:
    def test_valid_command_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, commands=[{"name": "my-cmd", "description": "Does stuff"}])
        validate.check_commands()
        assert len(validate.FAILURES) == 0

    def test_missing_frontmatter_fails(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "bad.md").write_text("No frontmatter\n", encoding="utf-8")
        validate.check_commands()
        assert any("missing or malformed frontmatter" in f for f in validate.FAILURES)

    def test_missing_description_fails(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "bad.md").write_text("---\nname: bad\n---\n\nBody\n", encoding="utf-8")
        validate.check_commands()
        assert any("description" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_agent_skill_refs
# ──────────────────────────────────────────────

class TestCheckAgentSkillRefs:
    def test_ref_to_existing_skill_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Skill\n---\n"
            "\nUse `swe-workbench:foo` skill.\n"
            "\n> See @./shared/skills.md\n",
            encoding="utf-8",
        )
        validate.check_agent_skill_refs()
        assert len(validate.FAILURES) == 0

    def test_ref_to_absent_skill_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Skill\n---\n"
            "\nUse `swe-workbench:nonexistent` skill.\n"
            "\n> See @./shared/skills.md\n",
            encoding="utf-8",
        )
        validate.check_agent_skill_refs()
        assert any("does not exist" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_catalog_completeness
# ──────────────────────────────────────────────

class TestCheckCatalogCompleteness:
    def _agent_body(self, name="my-agent"):
        return (
            f"---\nname: {name}\ndescription: d\ntools: Read\n---\n"
            "\n> See @./shared/skills.md for the full skill catalog.\n"
        )

    def test_full_match_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"foo": "---\nname: foo\ndescription: d\n---\n"})
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(self._agent_body(), encoding="utf-8")
        validate.check_catalog_completeness()
        assert len(validate.FAILURES) == 0

    def test_catalog_missing_entry_fails(self, reset_validate):
        root = reset_validate
        # skill on disk but not in catalog
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
            catalog="# no entries\n",
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(self._agent_body(), encoding="utf-8")
        validate.check_catalog_completeness()
        assert any("missing entry" in f for f in validate.FAILURES)

    def test_stale_catalog_entry_fails(self, reset_validate):
        root = reset_validate
        # catalog references skill that doesn't exist on disk
        make_plugin_tree(
            root,
            skills={},
            catalog="- `swe-workbench:ghost` — phantom skill\n",
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(self._agent_body(), encoding="utf-8")
        validate.check_catalog_completeness()
        assert any("stale entry" in f for f in validate.FAILURES)

    def test_agent_missing_include_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"foo": "---\nname: foo\ndescription: d\n---\n"})
        agents_dir = root / "agents"
        # Agent without the @./shared/skills.md include
        (agents_dir / "bad-agent.md").write_text(
            "---\nname: bad-agent\ndescription: d\ntools: Read\n---\n\nNo include here.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any("@./shared/skills.md" in f for f in validate.FAILURES)

    def test_catalog_file_absent_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"foo": "---\nname: foo\ndescription: d\n---\n"})
        # Remove the catalog
        catalog_path = root / "agents" / "shared" / "skills.md"
        catalog_path.unlink()
        validate.check_catalog_completeness()
        assert any("missing" in f for f in validate.FAILURES)
