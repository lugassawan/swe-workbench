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

    def test_string_matcher_entry(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, hooks_json={"hooks": {"PreToolUse": ["bad"]}})
        validate.check_hooks_json()
        assert any("PreToolUse[0] must be an object" in f for f in validate.FAILURES)

    def test_int_matcher_entry(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, hooks_json={"hooks": {"PreToolUse": [42]}})
        validate.check_hooks_json()
        assert any("PreToolUse[0] must be an object" in f for f in validate.FAILURES)

    def test_null_matcher_entry(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, hooks_json={"hooks": {"PreToolUse": [None]}})
        validate.check_hooks_json()
        assert any("PreToolUse[0] must be an object" in f for f in validate.FAILURES)

    def test_string_sub_hook(self, reset_validate):
        root = reset_validate
        bad = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": ["bad"]}]}}
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("PreToolUse[0].hooks[0] must be an object" in f for f in validate.FAILURES)

    def test_int_sub_hook(self, reset_validate):
        root = reset_validate
        bad = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [42]}]}}
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("PreToolUse[0].hooks[0] must be an object" in f for f in validate.FAILURES)

    def test_null_sub_hook(self, reset_validate):
        root = reset_validate
        bad = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [None]}]}}
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("PreToolUse[0].hooks[0] must be an object" in f for f in validate.FAILURES)


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
# performance-tuner agent structural assertions
# ──────────────────────────────────────────────

class TestPerformanceTunerAgent:
    """Integration tests: assert the real agents/performance-tuner.md satisfies all
    acceptance criteria from issue #102 without relying on a synthetic fixture."""

    AGENT_PATH = Path(__file__).parent.parent / "agents" / "performance-tuner.md"

    def test_file_exists(self):
        assert self.AGENT_PATH.exists(), "agents/performance-tuner.md must exist"

    def test_frontmatter_fields(self):
        import re
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        # Extract YAML block between the first pair of ---
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "frontmatter block not found"
        fm_text = match.group(1)
        assert "name: performance-tuner" in fm_text
        assert "model: sonnet" in fm_text
        assert re.search(r"tools:.*\bRead\b", fm_text)
        assert re.search(r"tools:.*\bSkill\b", fm_text)

    def test_principle_performance_wired(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "`swe-workbench:principle-performance`" in text, (
            "agent must reference swe-workbench:principle-performance"
        )

    def test_shared_skills_include(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "@./shared/skills.md" in text, (
            "agent must include @./shared/skills.md catalog reference"
        )

    def test_profile_first_rule_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "## Refusal protocol" in text, "Refusal protocol section must be present"
        assert "without a profile" in text.lower(), (
            "refusal protocol must explicitly refuse optimization without a profile"
        )

    def test_agent_and_skill_ref_checks_pass(self, reset_validate, monkeypatch):
        """The real file must pass check_agents() and check_agent_skill_refs() against the live tree."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self.AGENT_PATH.parent.parent)
        val.FAILURES.clear()
        val.check_agents()
        val.check_agent_skill_refs()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"


# ──────────────────────────────────────────────
# principle-code-review skill structural assertions
# ──────────────────────────────────────────────

class TestPrincipleCodeReviewSkill:
    """Integration tests: assert the real skills/principle-code-review/SKILL.md satisfies
    all acceptance criteria from issue #180 without relying on a synthetic fixture."""

    SKILL_PATH = Path(__file__).parent.parent / "skills" / "principle-code-review" / "SKILL.md"

    def test_file_exists(self):
        assert self.SKILL_PATH.exists(), "skills/principle-code-review/SKILL.md must exist"

    def test_frontmatter_name(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "name: principle-code-review" in text

    def test_four_axis_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Four-Axis Review Lens" in text

    def test_confidence_filtering_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Confidence-Based Filtering" in text

    def test_skill_passes_validate(self, reset_validate, monkeypatch):
        """The real skill must pass check_skills() and check_unwired_principle_skills()
        against the live tree."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self.SKILL_PATH.parent.parent.parent)
        val.FAILURES.clear()
        val.check_skills()
        val.check_unwired_principle_skills()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"


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
# check_command_skill_refs
# ──────────────────────────────────────────────

class TestCheckCommandSkillRefs:
    def test_ref_to_existing_skill_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nRun `swe-workbench:foo` skill.\n",
            encoding="utf-8",
        )
        validate.check_command_skill_refs()
        assert len(validate.FAILURES) == 0

    def test_ref_to_absent_skill_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nRun `swe-workbench:nonexistent` skill.\n",
            encoding="utf-8",
        )
        validate.check_command_skill_refs()
        assert any("nonexistent" in f and "does not exist" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# test-reviewer agent structural assertions
# ──────────────────────────────────────────────

class TestTestReviewerAgent:
    """Integration tests: assert the real agents/test-reviewer.md satisfies all
    acceptance criteria from issue #179 without relying on a synthetic fixture."""

    AGENT_PATH = Path(__file__).parent.parent / "agents" / "test-reviewer.md"

    def test_file_exists(self):
        assert self.AGENT_PATH.exists(), "agents/test-reviewer.md must exist"

    def test_frontmatter_fields(self):
        import re
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "frontmatter block not found"
        fm_text = match.group(1)
        assert "name: test-reviewer" in fm_text
        assert "model: sonnet" in fm_text
        assert re.search(r"tools:.*\bRead\b", fm_text)
        assert re.search(r"tools:.*\bSkill\b", fm_text)

    def test_principle_testing_wired(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "`swe-workbench:principle-testing`" in text, (
            "agent must reference swe-workbench:principle-testing"
        )

    def test_principle_code_review_wired(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "`swe-workbench:principle-code-review`" in text, (
            "agent must reference swe-workbench:principle-code-review"
        )

    def test_shared_skills_include(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "@./shared/skills.md" in text, (
            "agent must include @./shared/skills.md catalog reference"
        )

    def test_boundary_sections_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "## Boundary vs. test-writer" in text, (
            "## Boundary vs. test-writer section must be present"
        )
        assert "## Boundary vs. reviewer" in text, (
            "## Boundary vs. reviewer section must be present"
        )

    def test_no_edit_tool(self):
        import re
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "frontmatter block not found"
        fm_text = match.group(1)
        tools_line = next(
            (line for line in fm_text.splitlines() if line.startswith("tools:")),
            None,
        )
        assert tools_line is not None, "tools: line not found in frontmatter"
        assert "Edit" not in tools_line, "Edit must NOT be in tools (read-only auditor)"

    def test_agent_and_skill_ref_checks_pass(self, reset_validate, monkeypatch):
        """The real file must pass check_agents() and check_agent_skill_refs() against the live tree."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self.AGENT_PATH.parent.parent)
        val.FAILURES.clear()
        val.check_agents()
        val.check_agent_skill_refs()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"

    def test_typoed_skill_id_among_valid_refs_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nUse `swe-workbench:foo` and `swe-workbench:fooo`.\n",
            encoding="utf-8",
        )
        validate.check_command_skill_refs()
        assert len(validate.FAILURES) == 1
        assert "fooo" in validate.FAILURES[0] and "does not exist" in validate.FAILURES[0]
        assert "swe-workbench:foo'" not in validate.FAILURES[0]

    def test_command_with_no_skill_refs_passes_silently(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nNo plugin references here.\n",
            encoding="utf-8",
        )
        validate.check_command_skill_refs()
        assert len(validate.FAILURES) == 0


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


# ──────────────────────────────────────────────
# check_template_placeholders
# ──────────────────────────────────────────────

def _make_template(root, skill_name, template_content, skill_extra=""):
    """Write a SKILL.md + templates/plan-workflow-section.md under skills/<skill_name>/."""
    skill_dir = root / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = skill_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    skill_text = (
        f"---\nname: {skill_name}\ndescription: d\n---\n\n"
        f"## Project Detection\n\n{skill_extra}"
    )
    (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
    (templates_dir / "plan-workflow-section.md").write_text(template_content, encoding="utf-8")


class TestCheckTemplatePlaceholders:
    def test_documented_marker_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        _make_template(
            root, "my-skill",
            template_content="Use `[[detect:format-command]]` here.",
            skill_extra="**Detection markers:** `format-command`\n",
        )
        validate.check_template_placeholders()
        assert validate.FAILURES == []

    def test_orphan_marker_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        _make_template(
            root, "my-skill",
            template_content="Use `[[detect:lint-command]]` here.",
            skill_extra="No mention of the key here.\n",
        )
        validate.check_template_placeholders()
        assert any("undocumented marker '[[detect:lint-command]]'" in f for f in validate.FAILURES)

    def test_no_markers_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        _make_template(
            root, "my-skill",
            template_content="No detect markers here at all.",
        )
        validate.check_template_placeholders()
        assert validate.FAILURES == []

    def test_multiple_orphans_aggregate(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        _make_template(
            root, "my-skill",
            template_content="`[[detect:foo]]` and `[[detect:bar]]`",
            skill_extra="No documented keys.\n",
        )
        validate.check_template_placeholders()
        assert len([f for f in validate.FAILURES if "undocumented marker" in f]) == 2

    def test_marker_in_code_fence_still_counts(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        _make_template(
            root, "my-skill",
            template_content="```\n[[detect:test-command]]\n```",
            skill_extra="No documented keys.\n",
        )
        validate.check_template_placeholders()
        assert any("undocumented marker '[[detect:test-command]]'" in f for f in validate.FAILURES)

    def test_key_in_later_section_fails(self, reset_validate):
        """Key appearing only after ## Project Detection must not pass validation."""
        root = reset_validate
        make_plugin_tree(root)
        skill_dir = root / "skills" / "my-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "templates").mkdir()
        (skill_dir / "templates" / "plan-workflow-section.md").write_text(
            "`[[detect:hidden-key]]`", encoding="utf-8"
        )
        # Key is documented AFTER Project Detection, not within it
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: d\n---\n\n"
            "## Project Detection\n\nNothing here.\n\n"
            "## The 5 Phases\n\n`hidden-key` documented only here.\n",
            encoding="utf-8",
        )
        validate.check_template_placeholders()
        assert any("undocumented marker '[[detect:hidden-key]]'" in f for f in validate.FAILURES)

    def test_template_without_skill_md_skipped(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        # Write a template without a sibling SKILL.md
        orphan_dir = root / "skills" / "orphan-skill" / "templates"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        (orphan_dir / "plan-workflow-section.md").write_text(
            "`[[detect:foo]]`", encoding="utf-8"
        )
        validate.check_template_placeholders()
        assert validate.FAILURES == []


# ──────────────────────────────────────────────
# check_skill_trigger_fixtures
# ──────────────────────────────────────────────

def _skill_with_triggers(root, skill_name, triggers_content=None):
    """Write skills/<skill_name>/SKILL.md and optionally triggers.txt."""
    make_plugin_tree(root, skills={skill_name: f"---\nname: {skill_name}\ndescription: A skill\n---\n"})
    if triggers_content is not None:
        (root / "skills" / skill_name / "triggers.txt").write_text(
            triggers_content, encoding="utf-8"
        )


class TestCheckSkillTriggerFixtures:
    def test_two_fixtures_passes(self, reset_validate):
        root = reset_validate
        _skill_with_triggers(root, "my-skill", "prompt one\nprompt two\n")
        validate.check_skill_trigger_fixtures()
        assert validate.FAILURES == []

    def test_missing_triggers_file_fails(self, reset_validate):
        root = reset_validate
        _skill_with_triggers(root, "my-skill")  # no triggers.txt
        validate.check_skill_trigger_fixtures()
        assert any("missing" in f for f in validate.FAILURES)

    def test_one_fixture_fails(self, reset_validate):
        root = reset_validate
        _skill_with_triggers(root, "my-skill", "only one prompt\n")
        validate.check_skill_trigger_fixtures()
        assert any("minimum is 2" in f for f in validate.FAILURES)

    def test_comments_and_blanks_dont_count(self, reset_validate):
        root = reset_validate
        _skill_with_triggers(
            root, "my-skill",
            "# this is a comment\n\n# another comment\n\nreal prompt\n",
        )
        validate.check_skill_trigger_fixtures()
        assert any("minimum is 2" in f for f in validate.FAILURES)

    def test_all_comments_and_blanks_fails(self, reset_validate):
        root = reset_validate
        _skill_with_triggers(root, "my-skill", "# only comments\n\n# another\n")
        validate.check_skill_trigger_fixtures()
        assert any("minimum is 2" in f for f in validate.FAILURES)

    def test_overlong_line_fails(self, reset_validate):
        root = reset_validate
        long_line = "x" * 201
        _skill_with_triggers(root, "my-skill", f"short prompt\n{long_line}\n")
        validate.check_skill_trigger_fixtures()
        assert any("line exceeds 200 chars" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_unwired_principle_skills
# ──────────────────────────────────────────────

class TestCheckUnwiredPrincipleSkills:
    def _agent_body(self, extra=""):
        return (
            "---\nname: my-agent\ndescription: d\ntools: Read, Skill\n---\n"
            "\n> See @./shared/skills.md for the full skill catalog.\n"
            + extra
        )

    def test_wired_principle_skill_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            self._agent_body("\n- `swe-workbench:principle-foo` — rationale\n"),
            encoding="utf-8",
        )
        validate.check_unwired_principle_skills()
        assert len(validate.FAILURES) == 0

    def test_unwired_principle_skill_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            self._agent_body(),  # no reference to principle-foo
            encoding="utf-8",
        )
        validate.check_unwired_principle_skills()
        assert any("principle-foo" in f and "not referenced" in f for f in validate.FAILURES)

    def test_non_principle_skill_unwired_does_not_fail(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"language-foo": "---\nname: language-foo\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            self._agent_body(),  # no reference to language-foo — check should ignore it
            encoding="utf-8",
        )
        validate.check_unwired_principle_skills()
        assert len(validate.FAILURES) == 0

    def test_catalog_reference_alone_does_not_satisfy_wiring(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"},
            # No agents written — the auto-generated catalog at agents/shared/skills.md
            # will contain the skill id, but that must not count as a wiring reference.
        )
        validate.check_unwired_principle_skills()
        assert any("principle-foo" in f for f in validate.FAILURES)

    def test_principle_dir_without_skill_md_is_ignored(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        # principle-bare/ exists on disk but has no SKILL.md — must not register
        (root / "skills" / "principle-bare").mkdir(parents=True, exist_ok=True)
        validate.check_unwired_principle_skills()
        assert len(validate.FAILURES) == 0
