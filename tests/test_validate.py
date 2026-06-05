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
            "---\nname: bad-agent\n---\n\n> See @./shared/principles.md\n", encoding="utf-8"
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
            "\n> See @./shared/principles.md\n",
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
            "\n> See @./shared/principles.md\n",
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
        assert "@./shared/principles.md" in text, (
            "agent must include @./shared/principles.md catalog reference (O3)"
        )

    # O7 — boundary matrix dedup (issue #235)
    def test_no_individual_boundary_vs_headers(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        import re
        count = len(re.findall(r"^## Boundary vs\.", text, re.MULTILINE))
        assert count == 0, (
            f"Found {count} '## Boundary vs.' headers — should be 0 after O7 dedup. "
            "Use the consolidated '## Boundaries vs. other agents' table instead."
        )

    def test_boundaries_table_section_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "## Boundaries vs. other agents" in text, (
            "agents/performance-tuner.md must have a '## Boundaries vs. other agents' table section (O7)"
        )

    def test_shared_agent_boundaries_file_absent(self):
        shared = self.AGENT_PATH.parent / "shared" / "agent-boundaries.md"
        assert not shared.exists(), (
            "agents/shared/agent-boundaries.md was an orphan with 0 consumers and has been removed. "
            "The inline table in performance-tuner.md is the sole source of truth (issue #337)."
        )

    def test_boundaries_table_completeness(self):
        """The inline '## Boundaries vs. other agents' table is the sole source of truth.

        agents/shared/agent-boundaries.md was removed in issue #337 (0 @-include consumers).
        This test asserts the expected boundary agents are present in the table section so
        drift is still caught — without needing a second copy of the data.
        """
        import re
        perf_text = self.AGENT_PATH.read_text(encoding="utf-8")
        section_match = re.search(
            r"## Boundaries vs\. other agents\n(.*?)(?=\n+## |\Z)",
            perf_text,
            re.DOTALL,
        )
        assert section_match, (
            "## Boundaries vs. other agents section not found in performance-tuner.md"
        )
        section_text = section_match.group(1)
        expected_agents = [
            "`reviewer`",
            "`auditor`",
            "`architect`",
            "`debugger`",
            "`dependency-auditor`",
            "`refactorer`",
        ]
        missing = [agent for agent in expected_agents if agent not in section_text]
        assert not missing, (
            f"performance-tuner.md is missing boundary rows for: {missing}. "
            "The inline '## Boundaries vs. other agents' table is the sole source of truth."
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
# principle-release-engineering skill structural assertions
# ──────────────────────────────────────────────

class TestPrincipleReleaseEngineeringSkill:
    """Integration tests: assert the real skills/principle-release-engineering/SKILL.md satisfies
    all acceptance criteria from issue #175 without relying on a synthetic fixture."""

    SKILL_PATH = Path(__file__).parent.parent / "skills" / "principle-release-engineering" / "SKILL.md"
    TRIGGERS_PATH = Path(__file__).parent.parent / "skills" / "principle-release-engineering" / "triggers.txt"

    def test_file_exists(self):
        assert self.SKILL_PATH.exists(), "skills/principle-release-engineering/SKILL.md must exist"

    def test_frontmatter_name(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "name: principle-release-engineering" in text

    def test_semver_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Semver" in text

    def test_expand_contract_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Expand-contract" in text or "## Expand-Contract" in text

    def test_idempotent_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Idempotent" in text

    def test_post_release_verification_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Post-release verification" in text or "## Post-Release Verification" in text

    def test_rollback_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Rollback" in text

    def test_triggers_has_two_or_more_non_empty_lines(self):
        assert self.TRIGGERS_PATH.exists(), "triggers.txt must exist"
        lines = [
            ln for ln in self.TRIGGERS_PATH.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert len(lines) >= 2, f"triggers.txt must have ≥2 non-empty lines, got {len(lines)}"

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
# principle-postmortem skill structural assertions
# ──────────────────────────────────────────────

class TestPrinciplePostmortemSkill:
    """Integration tests: assert the real skills/principle-postmortem/SKILL.md satisfies
    all acceptance criteria from issue #178 without relying on a synthetic fixture."""

    SKILL_PATH = Path(__file__).parent.parent / "skills" / "principle-postmortem" / "SKILL.md"
    TRIGGERS_PATH = Path(__file__).parent.parent / "skills" / "principle-postmortem" / "triggers.txt"

    def test_file_exists(self):
        assert self.SKILL_PATH.exists(), "skills/principle-postmortem/SKILL.md must exist"

    def test_frontmatter_name(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "name: principle-postmortem" in text

    def test_blameless_culture_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Blameless Culture" in text

    def test_root_cause_analysis_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Root Cause Analysis" in text

    def test_postmortem_document_structure_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Postmortem Document Structure" in text

    def test_action_item_discipline_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Action-Item Discipline" in text

    def test_two_rca_frameworks_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "5 Whys" in text, "RCA section must cover the 5 Whys framework"
        assert "Fishbone" in text or "Ishikawa" in text, (
            "RCA section must cover the Fishbone/Ishikawa framework"
        )

    def test_triggers_has_two_or_more_non_empty_lines(self):
        assert self.TRIGGERS_PATH.exists(), "triggers.txt must exist"
        lines = [
            ln for ln in self.TRIGGERS_PATH.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert len(lines) >= 2, f"triggers.txt must have ≥2 non-empty lines, got {len(lines)}"

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
            "\n> See @./shared/principles.md\n",
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
            "\n> See @./shared/principles.md\n",
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
        assert "description:" in fm_text
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
        assert "@./shared/principles.md" in text, (
            "agent must include @./shared/principles.md catalog reference (O3)"
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


# ──────────────────────────────────────────────
# check_catalog_completeness
# ──────────────────────────────────────────────

class TestCheckCatalogCompleteness:
    def _agent_body(self, name="my-agent"):
        # Code-touching agents must reference both catalogs (new invariant).
        return (
            f"---\nname: {name}\ndescription: d\ntools: Read\n---\n"
            "\nSee @./shared/principles.md and @./shared/languages.md for the skill catalog.\n"
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
        # Agent without any slice catalog reference
        (agents_dir / "bad-agent.md").write_text(
            "---\nname: bad-agent\ndescription: d\ntools: Read\n---\n\nNo include here.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any("slice" in f.lower() for f in validate.FAILURES)

    def test_catalog_file_absent_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"})
        # Remove the principles slice — validator must report it missing
        catalog_path = root / "agents" / "shared" / "principles.md"
        catalog_path.unlink()
        validate.check_catalog_completeness()
        assert any("missing" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_skill_skill_refs
# ──────────────────────────────────────────────

class TestCheckSkillSkillRefs:
    def test_ref_to_existing_skill_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "my-skill": "---\nname: my-skill\ndescription: d\n---\n\nUse `swe-workbench:target-skill`.\n",
                "target-skill": "---\nname: target-skill\ndescription: d\n---\n",
            },
        )
        validate.check_skill_skill_refs()
        assert len(validate.FAILURES) == 0

    def test_ref_to_existing_agent_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": "---\nname: my-skill\ndescription: d\n---\n\nUse `swe-workbench:some-agent`.\n"},
        )
        (root / "agents" / "some-agent.md").write_text(
            "---\nname: some-agent\ndescription: d\ntools: Read\n---\n\nBody.\n",
            encoding="utf-8",
        )
        validate.check_skill_skill_refs()
        assert len(validate.FAILURES) == 0

    def test_ref_to_existing_command_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": "---\nname: my-skill\ndescription: d\n---\n\nUse `swe-workbench:some-cmd`.\n"},
        )
        (root / "commands" / "some-cmd.md").write_text(
            "---\ndescription: d\n---\n\nCommand body.\n",
            encoding="utf-8",
        )
        validate.check_skill_skill_refs()
        assert len(validate.FAILURES) == 0

    def test_ref_to_nonexistent_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": "---\nname: my-skill\ndescription: d\n---\n\nUse `swe-workbench:ghost`.\n"},
        )
        validate.check_skill_skill_refs()
        assert any("ghost" in f and "does not exist" in f for f in validate.FAILURES)

    def test_skill_with_no_refs_passes_silently(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": "---\nname: my-skill\ndescription: d\n---\n\nNo plugin refs here.\n"},
        )
        validate.check_skill_skill_refs()
        assert len(validate.FAILURES) == 0

    def test_skill_skill_refs_live_tree_passes(self, reset_validate, monkeypatch):
        """All swe-workbench refs in real skills must resolve to skill dirs, agents, or commands."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", Path(__file__).parent.parent)
        val.FAILURES.clear()
        val.check_skill_skill_refs()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"


# ──────────────────────────────────────────────
# check_workflow_development_activation_contract
# ──────────────────────────────────────────────

class TestCheckWorkflowDevelopmentActivationContract:
    _REPO_ROOT = Path(__file__).parent.parent

    def _make_wf_dev_skill(self, root, activators):
        """Write a minimal workflow-development SKILL.md listing given activators."""
        skill_dir = root / "skills" / "workflow-development"
        skill_dir.mkdir(parents=True, exist_ok=True)
        listed = ", ".join(f"/swe-workbench:{a}" for a in activators)
        desc = f"Activated by {listed} when the plan modifies the codebase."
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: workflow-development\ndescription: {desc}\n---\n\nBody.\n",
            encoding="utf-8",
        )

    def test_listed_and_activating_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._make_wf_dev_skill(root, ["mycmd"])
        (root / "commands" / "mycmd.md").write_text(
            "---\ndescription: d\n---\n\nActivate `swe-workbench:workflow-development`.\n",
            encoding="utf-8",
        )
        validate.check_workflow_development_activation_contract()
        assert len(validate.FAILURES) == 0

    def test_listed_but_not_activating_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._make_wf_dev_skill(root, ["mycmd"])
        (root / "commands" / "mycmd.md").write_text(
            "---\ndescription: d\n---\n\nNo workflow-development mention here.\n",
            encoding="utf-8",
        )
        validate.check_workflow_development_activation_contract()
        assert any("mycmd" in f for f in validate.FAILURES)

    def test_activating_but_not_listed_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._make_wf_dev_skill(root, [])
        (root / "commands" / "mycmd.md").write_text(
            "---\ndescription: d\n---\n\nActivate `swe-workbench:workflow-development`.\n",
            encoding="utf-8",
        )
        validate.check_workflow_development_activation_contract()
        assert any("mycmd" in f for f in validate.FAILURES)

    def test_unknown_command_in_description_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._make_wf_dev_skill(root, ["typoedcmd"])
        validate.check_workflow_development_activation_contract()
        assert any("typoedcmd" in f and "unknown" in f for f in validate.FAILURES)

    def test_live_tree_passes(self, reset_validate, monkeypatch):
        """workflow-development SKILL.md 'Activated by' list must match actual activators in commands/."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self._REPO_ROOT)
        val.FAILURES.clear()
        val.check_workflow_development_activation_contract()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"

    # O3 — slice-specific tests (issue #235)

    def test_non_code_agent_with_principles_only_passes(self, reset_validate):
        # Non-code agents (product-manager) are whitelisted — principles-only is valid.
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"})
        agents_dir = root / "agents"
        (agents_dir / "product-manager.md").write_text(
            "---\nname: product-manager\ndescription: d\ntools: Read\n---\n"
            "\nSee @./shared/principles.md for the skill catalog.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert len(validate.FAILURES) == 0

    def test_code_touching_agent_with_principles_only_fails(self, reset_validate):
        # Code-touching agents must reference @./shared/languages.md alongside principles.md.
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"})
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\nSee @./shared/principles.md for the skill catalog.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any("languages.md" in f for f in validate.FAILURES), (
            "Expected a failure about missing @./shared/languages.md "
            "for a code-touching agent that only includes principles.md"
        )

    def test_agent_with_principles_and_languages_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "principle-foo": "---\nname: principle-foo\ndescription: d\n---\n",
                "language-bar": "---\nname: language-bar\ndescription: d\n---\n",
            },
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\nSee @./shared/principles.md and @./shared/languages.md for the skill catalog.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert len(validate.FAILURES) == 0

    def test_agent_with_no_slice_reference_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n\nNo catalog ref at all.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any("slice" in f.lower() for f in validate.FAILURES)

    def test_ticket_context_lands_in_workflows(self, reset_validate):
        """ticket-context is a _WORKFLOW_EXTRAS member — must land in workflows.md, not principles.md."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"ticket-context": "---\nname: ticket-context\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\nSee @./shared/workflows.md for the skill catalog.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert len(validate.FAILURES) == 0
        principles_text = (root / "agents" / "shared" / "principles.md").read_text()
        assert "ticket-context" not in principles_text, (
            "ticket-context must not appear in principles.md (belongs in workflows.md)"
        )

    def test_stale_entry_in_wrong_slice_fails(self, reset_validate):
        """A language-* skill listed in principles.md (wrong slice) must fail."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"language-python": "---\nname: language-python\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        shared_dir = agents_dir / "shared"
        # Manually override: put language-python in principles.md instead of languages.md
        (shared_dir / "principles.md").write_text(
            "- `swe-workbench:language-python` — python skill\n", encoding="utf-8"
        )
        (shared_dir / "languages.md").write_text("\n", encoding="utf-8")
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\nSee @./shared/principles.md\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        # principles.md has language-python (wrong slice) → "belongs in languages.md"
        assert any("belongs in" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_shared_includes_not_blockquoted
# ──────────────────────────────────────────────

class TestCheckSharedIncludesNotBlockquoted:
    def test_blockquoted_principles_include_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        (root / "agents" / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\n> See @./shared/principles.md for the skill catalog.\n",
            encoding="utf-8",
        )
        validate.check_shared_includes_not_blockquoted()
        assert any("my-agent.md" in f and "blockquoted" in f for f in validate.FAILURES)

    def test_blockquoted_severity_contract_include_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        (root / "agents" / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\n> Base format, sort order, and silence rule: @./shared/severity-output-contract.md\n",
            encoding="utf-8",
        )
        validate.check_shared_includes_not_blockquoted()
        assert any("my-agent.md" in f and "blockquoted" in f for f in validate.FAILURES)

    def test_plain_include_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, agents=[{"name": "my-agent", "description": "d"}])
        validate.check_shared_includes_not_blockquoted()
        assert len(validate.FAILURES) == 0

    def test_shared_catalog_files_not_scanned(self, reset_validate):
        """agents/shared/*.md catalog slices use glob("*.md") — not rglob — so they are excluded."""
        root = reset_validate
        # An agent with a plain include ensures the check actually runs (non-vacuous).
        make_plugin_tree(root, agents=[{"name": "my-agent", "description": "d"}])
        # Overwrite principles.md with a hypothetical blockquoted line; check must not flag it.
        (root / "agents" / "shared" / "principles.md").write_text(
            "- `swe-workbench:foo` — foo skill\n"
            "> Hypothetical blockquoted @./shared/principles.md reference\n",
            encoding="utf-8",
        )
        validate.check_shared_includes_not_blockquoted()
        assert len(validate.FAILURES) == 0


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
            "\nSee @./shared/principles.md for the skill catalog.\n"
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
            # No agents written — the auto-generated slices (principles.md, languages.md,
            # workflows.md) will contain the skill id, but that must not count as a wiring reference.
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


# ──────────────────────────────────────────────
# File-read caching
# ──────────────────────────────────────────────

def _make_full_valid_tree(root: Path) -> None:
    """Build a minimal plugin tree that passes all validate.main() checks."""
    skills = {
        "skill-a": "---\nname: skill-a\ndescription: Skill A\n---\n",
        "skill-b": "---\nname: skill-b\ndescription: Skill B\n---\n",
    }
    agents = [
        {"name": "agent-a", "description": "Agent A"},
        {"name": "agent-b", "description": "Agent B"},
        {"name": "agent-c", "description": "Agent C"},
    ]
    make_plugin_tree(root, skills=skills, agents=agents)
    for skill_name in ("skill-a", "skill-b"):
        (root / "skills" / skill_name / "triggers.txt").write_text(
            "trigger phrase one\ntrigger phrase two\n", encoding="utf-8"
        )


class TestFileReadCaching:
    """After the cache refactor, main() reads each agent and skill file exactly once."""

    def _count_reads(self, root: Path, monkeypatch):
        """Patch Path.read_text, run main(), return per-path read counts."""
        read_counts: dict[str, int] = {}
        original = Path.read_text

        def counting_read_text(self_path, *args, **kwargs):
            key = str(self_path.resolve())
            if str(root) in key:  # only count reads under the test tree
                read_counts[key] = read_counts.get(key, 0) + 1
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read_text)

        try:
            validate.main()
        except SystemExit:
            pass  # we care about read counts, not pass/fail

        return read_counts

    def test_each_agent_md_read_at_most_once(self, reset_validate, monkeypatch):
        root = reset_validate
        _make_full_valid_tree(root)
        read_counts = self._count_reads(root, monkeypatch)

        agents_dir = root / "agents"
        agent_files = [p for p in agents_dir.rglob("*.md")]
        assert agent_files, "Expected at least one agent .md file"

        for agent_path in agent_files:
            count = read_counts.get(str(agent_path.resolve()), 0)
            assert count <= 1, (
                f"{agent_path.name} was read {count} times; expected ≤1 "
                "(check_agents, check_agent_skill_refs, check_catalog_completeness, "
                "and check_unwired_principle_skills share the same cache)"
            )

    def test_each_skill_md_read_at_most_once(self, reset_validate, monkeypatch):
        root = reset_validate
        _make_full_valid_tree(root)
        read_counts = self._count_reads(root, monkeypatch)

        skills_dir = root / "skills"
        skill_files = list(skills_dir.glob("*/SKILL.md"))
        assert skill_files, "Expected at least one SKILL.md"

        for skill_path in skill_files:
            count = read_counts.get(str(skill_path.resolve()), 0)
            assert count <= 1, (
                f"{skill_path.parent.name}/SKILL.md was read {count} times; expected ≤1 "
                "(check_skills and check_template_placeholders share the same cache)"
            )

    def test_unreadable_agent_cached_as_failure(self, reset_validate, monkeypatch):
        root = reset_validate
        _make_full_valid_tree(root)

        agents_dir = root / "agents"
        unreadable = sorted(agents_dir.glob("*.md"))[0]

        original = Path.read_text
        read_count = {"n": 0}

        def patched_read_text(self_path, *args, **kwargs):
            if self_path.resolve() == unreadable.resolve():
                read_count["n"] += 1
                raise OSError("simulated read failure")
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", patched_read_text)
        try:
            validate.main()
        except SystemExit:
            pass

        assert read_count["n"] == 1, (
            f"Expected unreadable file to be attempted exactly once (cache build only), "
            f"got {read_count['n']} — None sentinel may not be preventing consumer re-reads"
        )
        rel = str(unreadable.relative_to(root))
        assert any(rel in entry for entry in validate.FAILURES), (
            f"Expected a failure entry for unreadable {rel!r}, got: {validate.FAILURES}"
        )

    @pytest.mark.parametrize("slice_name", ["principles.md", "languages.md", "workflows.md"])
    def test_unreadable_catalog_cached_as_failure(self, reset_validate, monkeypatch, slice_name):
        root = reset_validate
        _make_full_valid_tree(root)

        # O3: skills.md replaced by 3 slice files — test all three slices
        catalog = root / "agents" / "shared" / slice_name

        original = Path.read_text
        read_count = {"n": 0}

        def patched_read_text(self_path, *args, **kwargs):
            if self_path.resolve() == catalog.resolve():
                read_count["n"] += 1
                raise OSError("simulated catalog read failure")
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", patched_read_text)
        try:
            validate.main()
        except SystemExit:
            pass

        assert read_count["n"] == 1, (
            f"Catalog slice '{slice_name}' should be attempted exactly once (cache build only), "
            f"got {read_count['n']} — check_catalog_completeness may bypass the None sentinel"
        )
        rel = str(catalog.relative_to(root))
        assert any(rel in entry for entry in validate.FAILURES), (
            f"Expected a failure entry for unreadable catalog slice {rel!r}, got: {validate.FAILURES}"
        )


# ──────────────────────────────────────────────
# O6: workflow-commit-and-pr SKILL.md trim (issue #235)
# ──────────────────────────────────────────────

_WORKFLOW_COMMIT_SKILL = (
    Path(__file__).parent.parent
    / "skills" / "workflow-commit-and-pr" / "SKILL.md"
)


class TestWorkflowCommitAndPrTrim:
    """Integration tests: SKILL.md must stay ≤260 lines and the reference/ sub-doc
    must exist (O6 dedup — issue #235)."""

    def test_skill_md_within_line_cap(self):
        lines = len(self._skill_text().splitlines())
        assert lines <= 260, (
            f"skills/workflow-commit-and-pr/SKILL.md is {lines} lines; cap is 260 (O6, issue #235). "
            "Move extracted sections to reference/gh-pr-create.md."
        )

    def test_reference_gh_pr_create_exists(self):
        ref = _WORKFLOW_COMMIT_SKILL.parent / "reference" / "gh-pr-create.md"
        assert ref.exists(), (
            "skills/workflow-commit-and-pr/reference/gh-pr-create.md must exist (O6 canonical source)"
        )

    def test_reference_contains_pre_check_section(self):
        ref = _WORKFLOW_COMMIT_SKILL.parent / "reference" / "gh-pr-create.md"
        assert ref.exists()
        text = ref.read_text(encoding="utf-8")
        assert "## Pre-check: existing PR for this branch" in text, (
            "reference/gh-pr-create.md must contain the Pre-check section"
        )

    def test_reference_contains_draft_prompt_section(self):
        ref = _WORKFLOW_COMMIT_SKILL.parent / "reference" / "gh-pr-create.md"
        assert ref.exists()
        text = ref.read_text(encoding="utf-8")
        assert "## Draft vs ready prompt" in text, (
            "reference/gh-pr-create.md must contain the Draft vs ready prompt section"
        )

    def _skill_text(self):
        assert _WORKFLOW_COMMIT_SKILL.exists(), "SKILL.md not found"
        return _WORKFLOW_COMMIT_SKILL.read_text(encoding="utf-8")


# ──────────────────────────────────────────────
# O2: severity-output contract dedup (issue #235)
# ──────────────────────────────────────────────

_AGENTS_DIR = Path(__file__).parent.parent / "agents"

_O2_AGENTS = [
    "reviewer",
    "security-auditor",
    "accessibility-auditor",
    "performance-tuner",
    "test-reviewer",
]


class TestSeverityOutputContract:
    """Integration tests: every auditor agent in _O2_AGENTS must reference the shared
    severity-output-contract.md (O2 dedup — issue #235)."""

    def test_shared_contract_file_exists(self):
        shared = _AGENTS_DIR / "shared" / "severity-output-contract.md"
        assert shared.exists(), "agents/shared/severity-output-contract.md must exist (O2 canonical source)"

    @pytest.mark.parametrize("agent", _O2_AGENTS)
    def test_agent_references_severity_contract(self, agent):
        path = _AGENTS_DIR / f"{agent}.md"
        assert path.exists(), f"agents/{agent}.md not found"
        text = path.read_text(encoding="utf-8")
        assert "@./shared/severity-output-contract.md" in text, (
            f"agents/{agent}.md does not reference @./shared/severity-output-contract.md — "
            "add a reference in the severity/output-contract section (O2, issue #235)"
        )


# ──────────────────────────────────────────────
# E3: ticket-context prelude uniformity (issue #235)
# ──────────────────────────────────────────────

_CANONICAL_PRELUDE = (
    "If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first "
    "and prepend its structured summary to the delegation context below. "
    "Skip if $ARGUMENTS is free-text with no recognizable ref. "
    "(Trigger patterns are defined in that skill's \"When to invoke\" section.)"
)

_COMMANDS_DIR = Path(__file__).parent.parent / "commands"

_E3_COMMANDS = [
    "implement", "debug", "design", "refactor", "test",
    "migrate", "extend", "architect", "document",
]


class TestTicketContextPreludeUniformity:
    """Integration tests: every command in _E3_COMMANDS must carry the canonical
    ticket-context prelude paragraph (E3 dedup — issue #235, Path B)."""

    def test_shared_prelude_file_exists(self):
        shared = _COMMANDS_DIR / "shared" / "ticket-context-prelude.md"
        assert shared.exists(), "commands/shared/ticket-context-prelude.md must exist (E3 canonical source)"

    def test_shared_prelude_file_contains_canonical_text(self):
        shared = _COMMANDS_DIR / "shared" / "ticket-context-prelude.md"
        assert shared.exists(), "canonical source file missing"
        assert _CANONICAL_PRELUDE in shared.read_text(encoding="utf-8"), (
            "commands/shared/ticket-context-prelude.md content does not match canonical prelude"
        )

    @pytest.mark.parametrize("cmd", _E3_COMMANDS)
    def test_command_contains_canonical_prelude(self, cmd):
        path = _COMMANDS_DIR / f"{cmd}.md"
        assert path.exists(), f"commands/{cmd}.md not found"
        text = path.read_text(encoding="utf-8")
        assert _CANONICAL_PRELUDE in text, (
            f"commands/{cmd}.md does not contain the canonical ticket-context prelude — "
            "sync from commands/shared/ticket-context-prelude.md (E3, issue #235)"
        )


# ──────────────────────────────────────────────
# E312: interrogation-prelude uniformity (issue #312)
# ──────────────────────────────────────────────

_CANONICAL_INTERROGATION_PRELUDE = (
    "**Interrogation mode.** Before producing anything, resolve the mode:\n"
    "\n"
    "- **Explicit signal in the invocation is honored without asking.** "
    "grill-me = `--grill`, \"grill me\", or \"grill-me mode\". "
    "standard = `--standard`, \"standard\", or \"quick\". "
    "Strip the signal from $ARGUMENTS and record the resolved mode.\n"
    "- **No explicit signal:** ask via `AskUserQuestion` — one question, header \"Mode\", "
    "options **Standard** (recommended, listed first) and **Grill me**. "
    "Standard description: \"Lightweight clarify — a restatement and at most one question, then proceed.\" "
    "Grill-me description: \"Relentlessly walk the decision tree one question at a time, each with a "
    "recommended answer, self-answering from the codebase where possible.\" Use the user's choice.\n"
    "\n"
    "**Standard mode:** proceed with the command's existing lightweight clarify "
    "(a restatement and at most one clarifying question) — do not ask the mode question again.\n"
    "\n"
    "**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to "
    "completion (exit on shared understanding or when the user says \"proceed\"). Then thread the emitted "
    "`## Resolved decisions` block into the command's normal artifact/delegation step below — the same way "
    "a ticket-context summary is prepended — and continue as in standard mode."
)

_E312_COMMANDS = ["capture", "design", "implement", "architect", "extend", "debug"]


class TestInterrogationPreludeUniformity:
    """Integration tests: every command in _E312_COMMANDS must carry the canonical
    interrogation prelude block (E312 — issue #312)."""

    def test_shared_prelude_file_exists(self):
        shared = _COMMANDS_DIR / "shared" / "interrogation-prelude.md"
        assert shared.exists(), (
            "commands/shared/interrogation-prelude.md must exist (E312 canonical source)"
        )

    def test_shared_prelude_file_contains_canonical_text(self):
        shared = _COMMANDS_DIR / "shared" / "interrogation-prelude.md"
        assert shared.exists(), "canonical source file missing"
        assert _CANONICAL_INTERROGATION_PRELUDE in shared.read_text(encoding="utf-8"), (
            "commands/shared/interrogation-prelude.md content does not match canonical prelude"
        )

    @pytest.mark.parametrize("cmd", _E312_COMMANDS)
    def test_command_contains_canonical_interrogation_prelude(self, cmd):
        path = _COMMANDS_DIR / f"{cmd}.md"
        assert path.exists(), f"commands/{cmd}.md not found"
        text = path.read_text(encoding="utf-8")
        assert _CANONICAL_INTERROGATION_PRELUDE in text, (
            f"commands/{cmd}.md does not contain the canonical interrogation prelude — "
            "sync from commands/shared/interrogation-prelude.md (E312, issue #312)"
        )


# ──────────────────────────────────────────────
# check_test_subprocess_env
# ──────────────────────────────────────────────

class TestCheckTestSubprocessEnv:
    """validate.check_test_subprocess_env() must flag env=os.environ / env={**os.environ
    in tests/*.py (excluding conftest.py) and must NOT flag clean usages or
    non-subprocess os.environ references."""

    def _make_tests_dir(self, root):
        d = root / "tests"
        d.mkdir(exist_ok=True)
        return d

    def test_env_os_environ_flagged(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_bad.py").write_text(
            'subprocess.run(["git", "status"], env=os.environ)\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 1
        assert "_CLEAN_ENV" in validate.FAILURES[0]
        assert "test_bad.py" in validate.FAILURES[0]

    def test_env_splat_os_environ_flagged(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_bad2.py").write_text(
            'subprocess.run(["git", "log"], env={**os.environ, "K": "v"})\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 1
        assert "_CLEAN_ENV" in validate.FAILURES[0]

    def test_env_dict_os_environ_flagged(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_bad3.py").write_text(
            'subprocess.run(["git", "status"], env=dict(os.environ))\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 1
        assert "_CLEAN_ENV" in validate.FAILURES[0]

    def test_clean_env_not_flagged(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_good.py").write_text(
            'subprocess.run(["git", "status"], env=dict(_CLEAN_ENV))\n'
            'subprocess.run(["git", "log"], env={**_CLEAN_ENV, "K": "v"})\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 0

    def test_env_method_call_not_flagged(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_method_calls.py").write_text(
            'subprocess.run(["x"], env=os.environ.copy())\n'
            'for k, v in os.environ.items(): pass\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 0

    def test_string_literal_not_false_positive(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_secret_guard.py").write_text(
            'SECRET = os.environ["S"]\n'
            'VALUE = os.environ.get("KEY", "default")\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 0

    def test_conftest_excluded(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "conftest.py").write_text(
            "_CLEAN_ENV = {k: v for k, v in os.environ.items()}\n"
            'subprocess.run(["x"], env=os.environ)\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 0

    def test_test_validate_excluded(self, reset_validate):
        root = reset_validate
        d = self._make_tests_dir(root)
        (d / "test_validate.py").write_text(
            '(d / "bad.py").write_text(\'subprocess.run([], env=os.environ)\')\n',
            encoding="utf-8",
        )
        validate.check_test_subprocess_env()
        assert len(validate.FAILURES) == 0


# ──────────────────────────────────────────────
# check_no_cycles
# ──────────────────────────────────────────────

def _make_cycle_tree(root):
    """Create the minimum required directories for check_no_cycles tests."""
    (root / "agents" / "shared").mkdir(parents=True, exist_ok=True)
    (root / "commands").mkdir(exist_ok=True)
    (root / "skills").mkdir(exist_ok=True)


class TestCheckNoCycles:
    """Dependency-flow cycle detection (issue #371)."""

    REAL_ROOT = Path(__file__).parent.parent

    def test_green_baseline_live_repo(self, reset_validate, monkeypatch):
        """Live repo activation graph must have zero cycles."""
        monkeypatch.setattr(validate, "ROOT", self.REAL_ROOT)
        cache = validate._build_cache()
        validate.check_no_cycles(cache=cache)
        assert validate.FAILURES == []

    def test_skill_to_skill_cycle_detected(self, reset_validate):
        """skill A action-invokes skill B and B action-invokes A → cycle reported."""
        root = reset_validate
        _make_cycle_tree(root)
        (root / "skills" / "a").mkdir()
        (root / "skills" / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\ninvoke `swe-workbench:b`\n",
            encoding="utf-8",
        )
        (root / "skills" / "b").mkdir()
        (root / "skills" / "b" / "SKILL.md").write_text(
            "---\nname: b\ndescription: d\n---\ninvoke `swe-workbench:a`\n",
            encoding="utf-8",
        )
        cache = validate._build_cache()
        validate.check_no_cycles(cache=cache)
        assert len(validate.FAILURES) >= 1
        combined = " ".join(validate.FAILURES)
        assert "a" in combined and "b" in combined

    def test_prose_cross_ref_no_cycle(self, reset_validate):
        """See `swe-workbench:X` lines are pointer cues, not activations — no edge emitted."""
        root = reset_validate
        _make_cycle_tree(root)
        (root / "skills" / "a").mkdir()
        (root / "skills" / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\nSee `swe-workbench:b` for details.\n",
            encoding="utf-8",
        )
        (root / "skills" / "b").mkdir()
        (root / "skills" / "b" / "SKILL.md").write_text(
            "---\nname: b\ndescription: d\n---\nSee `swe-workbench:a` for details.\n",
            encoding="utf-8",
        )
        cache = validate._build_cache()
        validate.check_no_cycles(cache=cache)
        assert validate.FAILURES == []

    def test_slash_handoff_no_cycle(self, reset_validate):
        """Slash-command handoffs in skills are excluded; command→skill edge alone is not a cycle."""
        root = reset_validate
        _make_cycle_tree(root)
        (root / "skills" / "a").mkdir()
        (root / "skills" / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\nWhen done, run `/review` next.\n",
            encoding="utf-8",
        )
        (root / "commands" / "review.md").write_text(
            "---\ndescription: review\n---\ninvoke `swe-workbench:a`\n",
            encoding="utf-8",
        )
        cache = validate._build_cache()
        validate.check_no_cycles(cache=cache)
        assert validate.FAILURES == []

    def test_self_mention_no_edge(self, reset_validate):
        """A skill action-invoking its own id must not produce a self-edge or cycle."""
        root = reset_validate
        _make_cycle_tree(root)
        (root / "skills" / "a").mkdir()
        (root / "skills" / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\ninvoke `swe-workbench:a` directly.\n",
            encoding="utf-8",
        )
        cache = validate._build_cache()
        validate.check_no_cycles(cache=cache)
        assert validate.FAILURES == []

    def test_agent_mediated_cycle_detected(self, reset_validate):
        """skill A → agent X → skill A is a cycle and must be reported."""
        root = reset_validate
        _make_cycle_tree(root)
        (root / "skills" / "a").mkdir()
        (root / "skills" / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: d\n---\ninvoke `swe-workbench:x`\n",
            encoding="utf-8",
        )
        (root / "agents" / "x.md").write_text(
            "---\nname: x\ndescription: d\n---\ninvoke `swe-workbench:a`\n",
            encoding="utf-8",
        )
        cache = validate._build_cache()
        validate.check_no_cycles(cache=cache)
        assert len(validate.FAILURES) >= 1
        combined = " ".join(validate.FAILURES)
        assert "a" in combined and "x" in combined


# ──────────────────────────────────────────────
# No dead superpowers:code-reviewer references
# ──────────────────────────────────────────────


class TestNoDeadCodeReviewerRef:
    """superpowers:code-reviewer does not exist; all sites must use
    superpowers:requesting-code-review (issue #333)."""

    REAL_ROOT = Path(__file__).parent.parent
    DEAD_REF = "superpowers:code-reviewer"

    def test_dead_ref_absent_from_md_files(self):
        """No *.md file in the repo may reference the non-existent skill name.

        Scope: *.md files only (where all current skill references live).
        Skill refs in *.py fixture strings are covered by isolation tests.
        """
        hits = [
            str(p.relative_to(self.REAL_ROOT))
            for p in self.REAL_ROOT.rglob("*.md")
            if ".git" not in p.parts
            and self.DEAD_REF in p.read_text(encoding="utf-8", errors="replace")
        ]
        assert hits == [], (
            f"Found dead skill ref '{self.DEAD_REF}' in {len(hits)} file(s):\n"
            + "\n".join(f"  {h}" for h in sorted(hits))
        )


class TestNoPhantomSkillsCatalogRef:
    """agents/shared/skills.md never existed after the catalog was split into
    principles.md / languages.md / workflows.md (issue #334). No doc may send
    contributors to it, and the onboarding docs must point at a real slice."""

    REAL_ROOT = Path(__file__).parent.parent
    PHANTOM_REF = "shared/skills.md"
    ONBOARDING_DOCS = ("CONTRIBUTING.md", "docs/extending.md")
    SLICE_FILES = ("principles.md", "languages.md", "workflows.md")

    def test_phantom_ref_absent_from_md_files(self):
        hits = [
            str(p.relative_to(self.REAL_ROOT))
            for p in self.REAL_ROOT.rglob("*.md")
            if ".git" not in p.parts
            and self.PHANTOM_REF in p.read_text(encoding="utf-8", errors="replace")
        ]
        assert hits == [], (
            f"Found phantom catalog ref '{self.PHANTOM_REF}' in {len(hits)} file(s):\n"
            + "\n".join(f"  {h}" for h in sorted(hits))
        )

    def test_onboarding_docs_point_at_real_slice(self):
        failures = []
        for rel in self.ONBOARDING_DOCS:
            text = (self.REAL_ROOT / rel).read_text(encoding="utf-8")
            if not any(f"shared/{s}" in text for s in self.SLICE_FILES):
                failures.append(rel)
        assert not failures, (
            f"Missing real catalog slice reference in: {', '.join(failures)}. "
            f"Expected one of: {', '.join(self.SLICE_FILES)}"
        )


# ──────────────────────────────────────────────
# check_plan_mode_workflow_embedding (#423)
# ──────────────────────────────────────────────

class TestCheckPlanModeWorkflowEmbedding:
    _REPO_ROOT = Path(__file__).parent.parent

    def test_missing_exit_plan_mode_clause_fails(self, reset_validate):
        """A command that activates workflow-development Mode A without the
        ExitPlanMode robustness clause must be flagged (#423)."""
        root = reset_validate
        make_plugin_tree(root)
        # Command references workflow-development + Mode A but lacks the clause
        (root / "commands" / "badcmd.md").write_text(
            "---\ndescription: d\n---\n\n"
            "Activate `swe-workbench:workflow-development` in **Mode A** "
            "before finalizing the plan.\n",
            encoding="utf-8",
        )
        validate.check_plan_mode_workflow_embedding()
        assert any("#423" in f for f in validate.FAILURES), (
            f"Expected a failure mentioning #423 but got: {validate.FAILURES}"
        )

    def test_with_exit_plan_mode_clause_passes(self, reset_validate):
        """A command that includes the ExitPlanMode robustness clause must pass."""
        root = reset_validate
        make_plugin_tree(root)
        (root / "commands" / "goodcmd.md").write_text(
            "---\ndescription: d\n---\n\n"
            "Activate `swe-workbench:workflow-development` in **Mode A** "
            "whether saved to a plan file or passed to `ExitPlanMode`.\n",
            encoding="utf-8",
        )
        validate.check_plan_mode_workflow_embedding()
        assert len(validate.FAILURES) == 0

    def test_no_mode_a_no_failure(self, reset_validate):
        """A command referencing workflow-development without Mode A is not flagged."""
        root = reset_validate
        make_plugin_tree(root)
        (root / "commands" / "modebtoo.md").write_text(
            "---\ndescription: d\n---\n\n"
            "Activate `swe-workbench:workflow-development` in Mode B.\n",
            encoding="utf-8",
        )
        validate.check_plan_mode_workflow_embedding()
        assert len(validate.FAILURES) == 0

    def test_live_tree_passes(self, reset_validate, monkeypatch):
        """All real Mode-A activators must carry the ExitPlanMode robustness clause."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self._REPO_ROOT)
        val.check_plan_mode_workflow_embedding()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"
