"""Tests for scripts/validate.py — every check_* function covered (issue #76)."""

import json
from pathlib import Path

import pytest

import validate
from helpers import make_plugin_tree, sentinel_block


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

    def test_empty_value_no_items_stays_empty_string(self, tmp_path):
        text = "---\nname: x\ntools:\ndescription: A skill\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm["tools"] == ""

    def test_block_sequence_becomes_list(self, tmp_path):
        text = "---\nname: x\nskills:\n  - swe-workbench:principle-code-review\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm["skills"] == ["swe-workbench:principle-code-review"]

    def test_scalar_then_orphan_dash_line_does_not_attach(self, tmp_path):
        text = "---\nname: x\ndescription: A skill\n- orphan\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm["name"] == "x"
        assert fm["description"] == "A skill"
        assert "- orphan" not in fm.values()

    def test_multiple_block_sequences_in_one_block(self, tmp_path):
        text = (
            "---\n"
            "name: x\n"
            "skills:\n"
            "  - swe-workbench:principle-code-review\n"
            "  - swe-workbench:principle-tdd\n"
            "tools:\n"
            "  - Read\n"
            "  - Write\n"
            "---\nBody"
        )
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm["skills"] == ["swe-workbench:principle-code-review", "swe-workbench:principle-tdd"]
        assert fm["tools"] == ["Read", "Write"]

    def test_block_sequence_survives_blank_line_before_items(self, tmp_path):
        text = "---\nname: x\nskills:\n\n  - swe-workbench:principle-code-review\n---\nBody"
        fm = validate.parse_frontmatter(tmp_path / "x.md", text=text)
        assert fm["skills"] == ["swe-workbench:principle-code-review"]

    def test_live_tree_agent_tools_still_str(self):
        agents_dir = validate.ROOT / "agents"
        for agent_md in sorted(agents_dir.glob("*.md")):
            fm = validate.parse_frontmatter(agent_md)
            assert fm is not None
            if "tools" in fm:
                assert isinstance(fm["tools"], str), (
                    f"{agent_md}: tools frontmatter unexpectedly parsed as {type(fm['tools'])}"
                )


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
# check_pi_package_json
# ──────────────────────────────────────────────

class TestCheckPiPackageJson:
    def _plugin_data(self):
        return {"name": "test-plugin", "version": "1.0.0", "description": "d"}

    def _valid_package_json(self):
        return {
            "name": "swe-workbench-pi",
            "version": "1.0.0",
            "private": True,
            "type": "module",
            "pi": {"extensions": ["./pi/extensions/index.ts"]},
        }

    def _write(self, root, data):
        (root / "package.json").write_text(json.dumps(data), encoding="utf-8")

    def test_matching_passes(self, reset_validate):
        root = reset_validate
        self._write(root, self._valid_package_json())
        validate.check_pi_package_json(self._plugin_data())
        assert len(validate.FAILURES) == 0

    def test_version_mismatch(self, reset_validate):
        root = reset_validate
        data = self._valid_package_json()
        data["version"] = "9.9.9"
        self._write(root, data)
        validate.check_pi_package_json(self._plugin_data())
        assert any("version" in f for f in validate.FAILURES)

    def test_not_private_fails(self, reset_validate):
        root = reset_validate
        data = self._valid_package_json()
        data["private"] = False
        self._write(root, data)
        validate.check_pi_package_json(self._plugin_data())
        assert any("private" in f for f in validate.FAILURES)

    def test_missing_pi_extensions_fails(self, reset_validate):
        root = reset_validate
        data = self._valid_package_json()
        data["pi"] = {}
        self._write(root, data)
        validate.check_pi_package_json(self._plugin_data())
        assert any("pi.extensions" in f for f in validate.FAILURES)

    @pytest.mark.parametrize("forbidden_key", ["skills", "prompts", "themes"])
    def test_forbidden_pi_key_fails(self, reset_validate, forbidden_key):
        root = reset_validate
        data = self._valid_package_json()
        data["pi"][forbidden_key] = ["whatever"]
        self._write(root, data)
        validate.check_pi_package_json(self._plugin_data())
        assert any(f"pi.{forbidden_key}" in f for f in validate.FAILURES)

    def test_json_parse_error(self, reset_validate):
        root = reset_validate
        (root / "package.json").write_text("{not valid json", encoding="utf-8")
        validate.check_pi_package_json(self._plugin_data())
        assert any("JSON parse error" in f for f in validate.FAILURES)


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

    def test_conforming_command_shape_passes(self, reset_validate):
        root = reset_validate
        good = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": 'bash "${CLAUDE_PLUGIN_ROOT}"/hooks/x.sh'}],
                }]
            }
        }
        make_plugin_tree(root, hooks_json=good)
        validate.check_hooks_json()
        assert len(validate.FAILURES) == 0

    def test_unquoted_command_fails_shape(self, reset_validate):
        root = reset_validate
        bad = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "$CLAUDE_PLUGIN_ROOT/hooks/x.sh"}],
                }]
            }
        }
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("does not match the required shape" in f for f in validate.FAILURES)

    def test_bare_path_command_fails_shape(self, reset_validate):
        root = reset_validate
        bad = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": '"${CLAUDE_PLUGIN_ROOT}"/hooks/x.sh'}],
                }]
            }
        }
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("does not match the required shape" in f for f in validate.FAILURES)

    def test_if_key_fails(self, reset_validate):
        root = reset_validate
        bad = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{
                        "type": "command",
                        "command": 'bash "${CLAUDE_PLUGIN_ROOT}"/hooks/x.sh',
                        "if": "Bash(git *)",
                    }],
                }]
            }
        }
        make_plugin_tree(root, hooks_json=bad)
        validate.check_hooks_json()
        assert any("carries an 'if' condition" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_hook_script_permissions
# ──────────────────────────────────────────────

class TestCheckHookScriptPermissions:
    def test_conforming_permissions_pass(self, reset_validate):
        root = reset_validate
        hooks_dir = root / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        script = hooks_dir / "example.sh"
        script.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        script.chmod(0o755)
        validate.check_hook_script_permissions()
        assert len(validate.FAILURES) == 0

    def test_umask_002_mode_0775_still_passes(self, reset_validate):
        """A checkout under umask 002 legitimately produces 0775 for a file
        git tracks as executable — must not be a spurious failure (only the
        exec bit matters, not the exact mode)."""
        root = reset_validate
        hooks_dir = root / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        script = hooks_dir / "example.sh"
        script.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        script.chmod(0o775)
        validate.check_hook_script_permissions()
        assert len(validate.FAILURES) == 0

    def test_not_executable_fails(self, reset_validate):
        root = reset_validate
        hooks_dir = root / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        script = hooks_dir / "example.sh"
        script.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        script.chmod(0o644)
        validate.check_hook_script_permissions()
        assert any("must be executable" in f for f in validate.FAILURES)

    def test_python_hook_checked_too(self, reset_validate):
        root = reset_validate
        hooks_dir = root / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        script = hooks_dir / "example.py"
        script.write_text("#!/usr/bin/env python3\nprint('hi')\n", encoding="utf-8")
        script.chmod(0o644)
        validate.check_hook_script_permissions()
        assert any("example.py" in f and "must be executable" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_bin_wrappers
# ──────────────────────────────────────────────

class TestCheckBinWrappers:
    def test_conforming_wrapper_passes(self, reset_validate):
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "swe-workbench-example"
        wrapper.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        wrapper.chmod(0o755)
        validate.check_bin_wrappers()
        assert len(validate.FAILURES) == 0

    def test_unprefixed_wrapper_fails(self, reset_validate):
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "example"
        wrapper.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        wrapper.chmod(0o755)
        validate.check_bin_wrappers()
        assert any("must be prefixed swe-workbench-" in f for f in validate.FAILURES)

    def test_non_executable_wrapper_fails(self, reset_validate):
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "swe-workbench-example"
        wrapper.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        wrapper.chmod(0o644)
        validate.check_bin_wrappers()
        assert any("not executable" in f for f in validate.FAILURES)

    def test_bad_shebang_fails(self, reset_validate):
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "swe-workbench-example"
        wrapper.write_text("echo hi\n", encoding="utf-8")
        wrapper.chmod(0o755)
        validate.check_bin_wrappers()
        assert any("must start with a #!/usr/bin/env" in f for f in validate.FAILURES)

    def test_readme_does_not_fail(self, reset_validate):
        """bin/README.md documents the wrapper convention and is not a wrapper itself —
        it must not be flagged for missing the swe-workbench- prefix or exec bit."""
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        readme = bin_dir / "README.md"
        readme.write_text("# bin/\n", encoding="utf-8")
        readme.chmod(0o644)
        validate.check_bin_wrappers()
        assert len(validate.FAILURES) == 0

    def test_umask_002_mode_0775_passes(self, reset_validate):
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "swe-workbench-example"
        wrapper.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        wrapper.chmod(0o775)
        validate.check_bin_wrappers()
        assert len(validate.FAILURES) == 0

    def test_sh_suffix_fails(self, reset_validate):
        """#571 collapsed runtime/ into bin/ — bin/ scripts are bare command names,
        never carrying a .sh/.py extension."""
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "swe-workbench-example.sh"
        wrapper.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        wrapper.chmod(0o755)
        validate.check_bin_wrappers()
        assert any("must be a bare command name" in f for f in validate.FAILURES)

    def test_runtime_dir_reappearing_fails(self, reset_validate):
        """A reappearing runtime/ means the wrapper/script split from before #571 is
        being silently reintroduced — this must fail loudly, not no-op."""
        root = reset_validate
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        runtime_dir = root / "runtime"
        runtime_dir.mkdir(exist_ok=True)
        (runtime_dir / "example.sh").write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
        validate.check_bin_wrappers()
        assert any("runtime/ must not exist" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# check_skills
# ──────────────────────────────────────────────

class TestCheckSkills:
    def _valid_skill(
        self,
        name: str = "my-skill",
        extra_lines: int = 0,
        description: str = "A skill",
    ) -> str:
        body = f"---\nname: {name}\ndescription: {description}\n---\n"
        body += "x\n" * extra_lines
        return body

    @pytest.mark.parametrize("description", ["x" * 1024, "😀" * 512])
    def test_description_at_pi_cap_passes(
        self, reset_validate, description: str
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert validate.FAILURES == []

    def test_double_quoted_description_at_pi_cap_passes(self, reset_validate) -> None:
        root = reset_validate
        description = f'"{"x" * 1024}"'
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert validate.FAILURES == []

    @pytest.mark.parametrize("description", ["", "   ", '"  "'])
    def test_empty_or_whitespace_description_fails(
        self, reset_validate, description: str
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert any("description is required" in failure for failure in validate.FAILURES)

    @pytest.mark.parametrize("description", ["-.nan", "+.nan"])
    def test_signed_nan_description_scalars_pass(
        self, reset_validate, description: str
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert validate.FAILURES == []

    @pytest.mark.parametrize("description", ["-", "?"])
    def test_lone_yaml_mapping_indicators_fail(
        self, reset_validate, description: str
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert any("description is required" in failure for failure in validate.FAILURES)

    @pytest.mark.parametrize(
        "description",
        [
            "Skill text # rationale",
            "Skill#tag",
            '"Skill #tag" # rationale',
            "'Skill ''text'' #tag' # rationale",
            '"A \\tquoted \\"value\\""',
            '"' + r"\U0001F600" * 512 + '"',
            "yes",
            "no",
            "on",
            "off",
            "0b101",
            "1_000",
            r'"\uD83D\uDE00"',
            r'"\uD800"',
            r'"\uDC00"',
            '"true"',
            "'0xFF'",
        ],
    )
    def test_yaml_string_description_scalars_pass(
        self, reset_validate, description: str
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert validate.FAILURES == []

    @pytest.mark.parametrize(
        "description",
        [
            " # rationale",
            "null",
            "~",
            "true",
            "false",
            "123",
            "1.5",
            "1e3",
            "0o755",
            "0xFF",
            ".inf",
            ".nan",
            "[]",
            "{}",
            "\n  - Skill text",
            "\n  text: Skill text",
            "Skill: text",
            '"Skill text',
            "'Skill text",
            '"Skill text" trailing',
        ],
    )
    def test_non_string_or_malformed_yaml_description_fails(
        self, reset_validate, description: str
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert any("description is required" in failure for failure in validate.FAILURES)

    @pytest.mark.parametrize(
        ("description", "expected_length"),
        [
            ("x" * 1025, 1025),
            ("😀" * 513, 1026),
            ('"' + r"\U0001F600" * 513 + '"', 1026),
        ],
    )
    def test_description_over_pi_cap_fails(
        self,
        reset_validate,
        description: str,
        expected_length: int,
    ) -> None:
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(description=description)},
        )
        validate.check_skills()
        assert any(
            f"description exceeds 1024 characters ({expected_length})" in failure
            for failure in validate.FAILURES
        ), validate.FAILURES

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
# check_skill_cap_headroom (#567)
# ──────────────────────────────────────────────

class TestCheckSkillCapHeadroom:
    def _valid_skill(self, name="my-skill", extra_lines=0, orchestrator=False):
        body = f"---\nname: {name}\ndescription: A skill\n"
        if orchestrator:
            body += "orchestrator: true\n"
        body += "---\n"
        body += "x\n" * extra_lines
        return body

    def test_below_threshold_no_warning(self, reset_validate):
        root = reset_validate
        # 150-line base cap; 90% threshold is 135 lines — stay comfortably under.
        make_plugin_tree(root, skills={"my-skill": self._valid_skill(extra_lines=50)})
        validate.check_skill_cap_headroom()
        assert len(validate.WARNINGS) == 0
        assert len(validate.FAILURES) == 0

    def test_above_90_percent_base_cap_warns(self, reset_validate):
        root = reset_validate
        # 4 frontmatter lines + 140 filler = 144 lines, > 135 (90% of 150).
        make_plugin_tree(root, skills={"my-skill": self._valid_skill(extra_lines=140)})
        validate.check_skill_cap_headroom()
        assert any("my-skill" in w and "150-line cap" in w for w in validate.WARNINGS)

    def test_above_90_percent_never_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._valid_skill(extra_lines=140)})
        validate.check_skill_cap_headroom()
        assert len(validate.FAILURES) == 0

    def test_orchestrator_cap_used_when_flagged(self, reset_validate):
        root = reset_validate
        # 145 lines total: over 90% of BASE_SKILL_CAP (135) but well under 90%
        # of ORCHESTRATOR_SKILL_CAP (270) — must NOT warn once flagged.
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(extra_lines=140, orchestrator=True)},
        )
        validate.check_skill_cap_headroom()
        assert len(validate.WARNINGS) == 0

    def test_orchestrator_above_90_percent_of_300_warns(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._valid_skill(extra_lines=268, orchestrator=True)},
        )
        validate.check_skill_cap_headroom()
        assert any("300-line cap" in w for w in validate.WARNINGS)

    def test_malformed_frontmatter_skipped_not_warned(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": "No frontmatter\n" + ("x\n" * 200)})
        validate.check_skill_cap_headroom()
        assert len(validate.WARNINGS) == 0


# ──────────────────────────────────────────────
# check_description_budget
# ──────────────────────────────────────────────

class TestCheckDescriptionBudget:
    def test_constants_exact_values(self):
        # Ratchet: assert the exact measured bound, not "a bound exists" —
        # a regex/inequality check here would let a defeating widening slip
        # through unnoticed. See scripts/validate.py's constant comments for
        # where these numbers come from.
        assert validate.SKILL_DESCRIPTION_BUDGET_CHARS == 20436
        assert validate.AGENT_DESCRIPTION_BUDGET_CHARS == 6087
        assert validate.PER_SKILL_DESCRIPTION_CAP_CHARS == 900

    def test_skills_under_budget_no_failure(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root, skills={"my-skill": "---\nname: my-skill\ndescription: A short skill description.\n---\n"}
        )
        validate.check_description_budget()
        assert len(validate.FAILURES) == 0

    def test_skills_over_budget_fails(self, reset_validate):
        root = reset_validate
        # "word " * 5000 minus the trailing space is 24999 chars, over the
        # 20332-char SKILL_DESCRIPTION_BUDGET_CHARS total.
        long_desc = ("word " * 5000).strip()
        make_plugin_tree(
            root, skills={"my-skill": f"---\nname: my-skill\ndescription: {long_desc}\n---\n"}
        )
        validate.check_description_budget()
        assert any("total skill description budget exceeded" in f for f in validate.FAILURES)

    def test_per_skill_over_cap_warns_but_never_fails(self, reset_validate):
        root = reset_validate
        # 849 chars: over 90% of PER_SKILL_DESCRIPTION_CAP_CHARS (810) but
        # under the cap itself (900) and nowhere near the 20332 total budget.
        desc = ("word " * 170).strip()
        make_plugin_tree(
            root, skills={"my-skill": f"---\nname: my-skill\ndescription: {desc}\n---\n"}
        )
        validate.check_description_budget()
        assert any("per-skill budget cap" in w for w in validate.WARNINGS)
        assert len(validate.FAILURES) == 0

    def test_agents_under_budget_no_failure(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: A short agent description.\n---\n",
            encoding="utf-8",
        )
        validate.check_description_budget()
        assert len(validate.FAILURES) == 0

    def test_agents_over_budget_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        # "word " * 2000 minus the trailing space is 9999 chars, over the
        # 6087-char AGENT_DESCRIPTION_BUDGET_CHARS total.
        long_desc = ("word " * 2000).strip()
        (agents_dir / "my-agent.md").write_text(
            f"---\nname: my-agent\ndescription: {long_desc}\n---\n",
            encoding="utf-8",
        )
        validate.check_description_budget()
        assert any("total agent description budget exceeded" in f for f in validate.FAILURES)

    def test_malformed_frontmatter_skipped(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": "No frontmatter\n"})
        validate.check_description_budget()
        assert len(validate.FAILURES) == 0
        assert len(validate.WARNINGS) == 0

    def test_cache_hit_path_matches_direct_read(self, reset_validate):
        """main()/validate.sh always call check_description_budget(cache=cache)
        with a real _build_cache() result — exercise that path explicitly,
        not just the cache=None direct-read fallback the other tests above use."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": "---\nname: my-skill\ndescription: A short skill description.\n---\n"},
        )
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: A short agent description.\n---\n",
            encoding="utf-8",
        )
        cache = validate._build_cache()
        validate.check_description_budget(cache=cache)
        assert len(validate.FAILURES) == 0

    def test_cache_none_sentinel_is_skipped_without_double_reporting(self, reset_validate):
        """A None cache entry (unreadable file) is check_skills's/check_agents's
        failure to report, not this check's — it must not raise and must not
        count toward either budget total."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": "---\nname: my-skill\ndescription: A short skill description.\n---\n"},
        )
        skill_md = root / "skills" / "my-skill" / "SKILL.md"
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent_md = agents_dir / "my-agent.md"
        agent_md.write_text(
            "---\nname: my-agent\ndescription: A short agent description.\n---\n", encoding="utf-8"
        )
        cache = ({agent_md: None}, {skill_md: None})
        validate.check_description_budget(cache=cache)
        assert len(validate.FAILURES) == 0


# ──────────────────────────────────────────────
# check_orchestrator_flag_earned (#568)
# ──────────────────────────────────────────────

class TestCheckOrchestratorFlagEarned:
    def _skill_body(self, extra_lines=95, orchestrator=True, extra_text=""):
        fm = "---\nname: my-skill\ndescription: A skill\n"
        if orchestrator:
            fm += "orchestrator: true\n"
        fm += "---\n"
        body = fm + extra_text + "\n" + ("x\n" * extra_lines)
        return body

    def test_flag_short_no_refs_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._skill_body()})
        validate.check_orchestrator_flag_earned()
        assert any("orchestrator" in f for f in validate.FAILURES)

    def test_flag_short_bare_agent_ref_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._skill_body(extra_text="Delegates to `some-agent`.\n")},
            agents=[{"name": "some-agent", "description": "d"}],
        )
        validate.check_orchestrator_flag_earned()
        assert len(validate.FAILURES) == 0

    def test_flag_short_namespaced_skill_ref_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "my-skill": self._skill_body(
                    extra_text="Composes `swe-workbench:other-skill`.\n"
                ),
                "other-skill": "---\nname: other-skill\ndescription: d\n---\n",
            },
        )
        validate.check_orchestrator_flag_earned()
        assert len(validate.FAILURES) == 0

    def test_flag_over_base_cap_no_refs_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._skill_body(extra_lines=196)})
        validate.check_orchestrator_flag_earned()
        assert len(validate.FAILURES) == 0

    def test_no_flag_short_no_refs_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._skill_body(orchestrator=False)})
        validate.check_orchestrator_flag_earned()
        assert len(validate.FAILURES) == 0

    def test_flag_short_self_reference_only_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._skill_body(extra_text="See `my-skill` for details.\n")},
        )
        validate.check_orchestrator_flag_earned()
        assert any("orchestrator" in f for f in validate.FAILURES)

    def test_flag_short_nonexistent_ref_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"my-skill": self._skill_body(extra_text="See `nonexistent-thing` for details.\n")},
        )
        validate.check_orchestrator_flag_earned()
        assert any("orchestrator" in f for f in validate.FAILURES)

    def test_flag_exactly_at_base_cap_no_refs_fails(self, reset_validate):
        """line_count == BASE_SKILL_CAP (150) is still 'at or under' and must fail —
        pins the boundary so a future '>' vs '>=' swap would be caught."""
        root = reset_validate
        fm = "---\nname: my-skill\ndescription: A skill\norchestrator: true\n---\n"
        body = fm + "x\n" * (validate.BASE_SKILL_CAP - fm.count("\n"))
        assert len(body.splitlines()) == validate.BASE_SKILL_CAP
        make_plugin_tree(root, skills={"my-skill": body})
        validate.check_orchestrator_flag_earned()
        assert any("orchestrator" in f for f in validate.FAILURES)

    def test_flag_one_over_base_cap_no_refs_passes(self, reset_validate):
        """line_count == BASE_SKILL_CAP + 1 already has the headroom and must pass."""
        root = reset_validate
        fm = "---\nname: my-skill\ndescription: A skill\norchestrator: true\n---\n"
        body = fm + "x\n" * (validate.BASE_SKILL_CAP + 1 - fm.count("\n"))
        assert len(body.splitlines()) == validate.BASE_SKILL_CAP + 1
        make_plugin_tree(root, skills={"my-skill": body})
        validate.check_orchestrator_flag_earned()
        assert len(validate.FAILURES) == 0

    def test_cache_none_sentinel_is_skipped_without_double_reporting(self, reset_validate):
        """A None cache entry (unreadable file) is check_skills's failure to report,
        not this check's — it must not raise and must not add its own failure."""
        root = reset_validate
        make_plugin_tree(root, skills={"my-skill": self._skill_body()})
        skill_md = root / "skills" / "my-skill" / "SKILL.md"
        cache = ({}, {skill_md: None})
        validate.check_orchestrator_flag_earned(cache=cache)
        assert len(validate.FAILURES) == 0

    def test_green_baseline_live_repo(self, reset_validate, monkeypatch):
        """Live repo must have zero unearned orchestrator: true flags (#568) —
        every current flag is earned by size or by composition."""
        real_root = Path(__file__).parent.parent
        monkeypatch.setattr(validate, "ROOT", real_root)
        cache = validate._build_cache()
        validate.check_orchestrator_flag_earned(cache=cache)
        assert validate.FAILURES == []


class TestOrchestratorFlagDocs:
    """Docs must name the literal frontmatter key and cap number where authors
    read them, not bury the rule in the validator's failure-path hint (#568)."""

    REAL_ROOT = Path(__file__).parent.parent

    def test_extending_md_names_flag_and_cap(self):
        text = (self.REAL_ROOT / "docs" / "extending.md").read_text(encoding="utf-8")
        assert "orchestrator: true" in text
        assert "300" in text

    def test_contributing_md_names_flag_and_cap(self):
        text = (self.REAL_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "orchestrator: true" in text
        assert "300" in text


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
            "---\nname: bad-agent\n---\n\n> See @../shared/agents/principles.md\n", encoding="utf-8"
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
            "\n> See @../shared/agents/principles.md\n",
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
            "\n> See @../shared/agents/principles.md\n",
            encoding="utf-8",
        )
        validate.check_agents()
        assert len(validate.FAILURES) == 0

    def test_skill_ref_without_tools_line_passes(self, reset_validate):
        """Omitting tools: entirely grants all tools (Skill implicitly available) — no failure."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: An agent\n---\n"
            "\nUse `swe-workbench:foo` to do things.\n"
            "\n> See @../shared/agents/principles.md\n",
            encoding="utf-8",
        )
        validate.check_agents()
        assert len(validate.FAILURES) == 0

    def test_name_mismatch_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: other-name\ndescription: An agent\n---\nBody\n",
            encoding="utf-8",
        )
        validate.check_agents()
        assert any("does not match" in f for f in validate.FAILURES)


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
        """performance-tuner is a normal code-touching agent — must carry both
        the skill-catalog-pointer and language-skill-required sentinel blocks,
        byte-identical to their sources (#619, was O3)."""
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        shared_dir = self.AGENT_PATH.parent.parent / "shared" / "agents"
        for fragment in ("skill-catalog-pointer.md", "language-skill-required.md"):
            block = sentinel_block(text, fragment)
            assert block is not None, (
                f"agent must carry the '<!-- BEGIN shared/agents/{fragment} -->' sentinel block (O3)"
            )
            source = (shared_dir / fragment).read_text(encoding="utf-8")
            assert block == source, (
                f"agent's {fragment} block has drifted from shared/agents/{fragment} — "
                "run python3 scripts/sync-shared-blocks.py --write"
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
            "`swe-workbench:reviewer`",
            "`swe-workbench:auditor`",
            "`swe-workbench:architect`",
            "`swe-workbench:debugger`",
            "`swe-workbench:dependency-auditor`",
            "`swe-workbench:refactorer`",
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

    def test_five_axis_section_present(self):
        text = self.SKILL_PATH.read_text(encoding="utf-8")
        assert "## Five-Axis Review Lens" in text

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
            "\n> See @../shared/agents/principles.md\n",
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
            "\n> See @../shared/agents/principles.md\n",
            encoding="utf-8",
        )
        validate.check_agent_skill_refs()
        assert any("no matching artifact found" in f for f in validate.FAILURES)

    def test_ref_to_existing_agent_file_passes(self, reset_validate):
        """An agent referencing another agent via swe-workbench: must pass
        when the target exists as agents/<id>.md (not just skills/<id>/)."""
        root = reset_validate
        make_plugin_tree(root)
        (root / "agents" / "bar.md").write_text(
            "---\nname: bar\ndescription: d\ntools: Read\n---\n",
            encoding="utf-8",
        )
        (root / "agents" / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Skill\n---\n"
            "\nUse `swe-workbench:bar` subagent.\n"
            "\n> See @../shared/agents/principles.md\n",
            encoding="utf-8",
        )
        validate.check_agent_skill_refs()
        assert len(validate.FAILURES) == 0


# ──────────────────────────────────────────────
# check_preloaded_skills
# ──────────────────────────────────────────────

class TestCheckPreloadedSkills:
    def _skill(self, skill_id, canary=True):
        canary_line = f"<!-- preload-canary: SWB-PRELOAD-{skill_id.upper()} -->\n" if canary else ""
        return f"---\nname: {skill_id}\ndescription: d\n---\n{canary_line}\nBody.\n"

    def _agent(self, root, name, skills_block, body_extra):
        (root / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: d\ntools: Read, Skill\n{skills_block}---\n"
            f"\n{body_extra}\n> See @../shared/agents/principles.md\n",
            encoding="utf-8",
        )

    def test_well_formed_preload_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": self._skill("principle-foo")})
        self._agent(
            root, "my-agent",
            "skills:\n  - swe-workbench:principle-foo\n",
            "- `swe-workbench:principle-foo` — rationale",
        )
        validate.check_preloaded_skills()
        assert len(validate.FAILURES) == 0

    def test_agent_without_skills_key_is_skipped(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._agent(root, "my-agent", "", "No preload here.")
        validate.check_preloaded_skills()
        assert len(validate.FAILURES) == 0

    def test_bare_unnamespaced_entry_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": self._skill("principle-foo")})
        self._agent(
            root, "my-agent",
            "skills:\n  - principle-foo\n",
            "- `swe-workbench:principle-foo` — rationale",
        )
        validate.check_preloaded_skills()
        assert any("not namespaced" in f for f in validate.FAILURES)

    def test_unresolvable_skill_id_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._agent(
            root, "my-agent",
            "skills:\n  - swe-workbench:principle-missing\n",
            "- `swe-workbench:principle-missing` — rationale",
        )
        validate.check_preloaded_skills()
        assert any(
            "does not resolve to skills/principle-missing/SKILL.md" in f
            for f in validate.FAILURES
        )

    def test_missing_body_backtick_does_not_fail(self, reset_validate):
        """Body-bullet retention is no longer required — check_unwired_principle_skills
        (not check_preloaded_skills) is what enforces wiring, and it accepts
        frontmatter-only wiring too."""
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": self._skill("principle-foo")})
        self._agent(
            root, "my-agent",
            "skills:\n  - swe-workbench:principle-foo\n",
            "No body reference here.",
        )
        validate.check_preloaded_skills()
        assert len(validate.FAILURES) == 0

    def test_missing_canary_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"principle-foo": self._skill("principle-foo", canary=False)},
        )
        self._agent(
            root, "my-agent",
            "skills:\n  - swe-workbench:principle-foo\n",
            "- `swe-workbench:principle-foo` — rationale",
        )
        validate.check_preloaded_skills()
        assert any("preload-canary" in f for f in validate.FAILURES)

    def test_scalar_skills_value_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": self._skill("principle-foo")})
        self._agent(
            root, "my-agent",
            "skills: swe-workbench:principle-foo\n",
            "- `swe-workbench:principle-foo` — rationale",
        )
        validate.check_preloaded_skills()
        assert any("block sequence" in f for f in validate.FAILURES)

    def test_empty_skills_value_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        self._agent(root, "my-agent", "skills:\n", "No preload here.")
        validate.check_preloaded_skills()
        assert any("block sequence" in f for f in validate.FAILURES)


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
        assert any("nonexistent" in f and "no matching artifact found" in f for f in validate.FAILURES)

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
        assert "fooo" in validate.FAILURES[0] and "no matching artifact found" in validate.FAILURES[0]
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

    def test_ref_to_existing_agent_file_passes(self, reset_validate):
        """A command referencing an agent via swe-workbench: must pass
        when the target exists as agents/<id>.md (not just skills/<id>/)."""
        root = reset_validate
        make_plugin_tree(root)
        (root / "agents" / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: d\ntools: Read\n---\n",
            encoding="utf-8",
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nDispatch `swe-workbench:reviewer` subagent.\n",
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
        fm = validate.parse_frontmatter(self.AGENT_PATH, text=text)
        fm_skills = fm.get("skills") if fm else None
        wired = "`swe-workbench:principle-testing`" in text or (
            isinstance(fm_skills, list) and "swe-workbench:principle-testing" in fm_skills
        )
        assert wired, "agent must reference swe-workbench:principle-testing (body or frontmatter)"

    def test_principle_code_review_wired(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        fm = validate.parse_frontmatter(self.AGENT_PATH, text=text)
        fm_skills = fm.get("skills") if fm else None
        wired = "`swe-workbench:principle-code-review`" in text or (
            isinstance(fm_skills, list) and "swe-workbench:principle-code-review" in fm_skills
        )
        assert wired, "agent must reference swe-workbench:principle-code-review (body or frontmatter)"

    def test_shared_skills_include(self):
        """test-reviewer is a normal code-touching agent — must carry both the
        skill-catalog-pointer and language-skill-required sentinel blocks,
        byte-identical to their sources (#619, was O3)."""
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        shared_dir = self.AGENT_PATH.parent.parent / "shared" / "agents"
        for fragment in ("skill-catalog-pointer.md", "language-skill-required.md"):
            block = sentinel_block(text, fragment)
            assert block is not None, (
                f"agent must carry the '<!-- BEGIN shared/agents/{fragment} -->' sentinel block (O3)"
            )
            source = (shared_dir / fragment).read_text(encoding="utf-8")
            assert block == source, (
                f"agent's {fragment} block has drifted from shared/agents/{fragment} — "
                "run python3 scripts/sync-shared-blocks.py --write"
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
        # Code-touching agents must carry both sentinel blocks (#619 — the
        # reworked check_catalog_completeness only checks marker *presence*,
        # not content-equality, so this fixture content need not byte-match
        # the real shared/agents/*.md sources; check_shared_blocks_in_sync
        # is the (separately-tested, in tests/test_shared_blocks.py) check
        # that cares about content drift).
        return (
            f"---\nname: {name}\ndescription: d\ntools: Read\n---\n\n"
            "<!-- BEGIN shared/agents/skill-catalog-pointer.md -->\n"
            "Skill catalog pointer.\n"
            "<!-- END shared/agents/skill-catalog-pointer.md -->\n\n"
            "<!-- BEGIN shared/agents/language-skill-required.md -->\n"
            "Language skill requirement.\n"
            "<!-- END shared/agents/language-skill-required.md -->\n"
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
        # Agent without any sentinel block at all
        (agents_dir / "bad-agent.md").write_text(
            "---\nname: bad-agent\ndescription: d\ntools: Read\n---\n\nNo include here.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any("skill-catalog-pointer" in f and "sentinel block" in f for f in validate.FAILURES)

    def test_catalog_file_absent_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"})
        # Remove the principles slice — validator must report it missing
        catalog_path = root / "shared" / "agents" / "principles.md"
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
# check_bare_actionable_refs (#586)
# ──────────────────────────────────────────────

class TestCheckBareActionableRefs:
    def test_bare_agent_id_in_command_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(root)
        (root / "agents" / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: d\ntools: Read\n---\n",
            encoding="utf-8",
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nDelegate to the `reviewer` subagent.\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert any("reviewer" in f and "swe-workbench:reviewer" in f for f in validate.FAILURES)

    def test_bare_skill_id_in_command_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nInvoke `foo` skill.\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert any("foo" in f for f in validate.FAILURES)

    def test_namespaced_ref_in_command_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nInvoke `swe-workbench:foo` skill.\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_bare_id_inside_fenced_block_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\n```\nDelegate to the `foo` skill.\n```\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_exemption_marker_suppresses_in_command(self, reset_validate):
        """Rule 1's marker escape hatch (used for real at report-issue.md's
        redaction allowlist), isolated from the live-tree test."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nNever redact `foo`. <!-- validate: prose-ref -->\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_command_id_in_command_passes(self, reset_validate):
        """report-issue.md:136 regression — a bare id that resolves only to a
        command (not a skill or agent) is never in the checked id set."""
        root = reset_validate
        make_plugin_tree(root)
        (root / "commands" / "capture.md").write_text(
            "---\ndescription: d\n---\n\nCommand body.\n", encoding="utf-8",
        )
        (root / "commands" / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\nNever redact `capture`.\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_bare_id_in_skill_prose_without_action_cue_fails(self, reset_validate):
        """The flat rule has no action-cue heuristic — any bare id fails, cued or not."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "my-skill": "---\nname: my-skill\ndescription: d\n---\n\nRelated: `target-skill` handles that.\n",
                "target-skill": "---\nname: target-skill\ndescription: d\n---\n",
            },
        )
        validate.check_bare_actionable_refs()
        assert any("target-skill" in f for f in validate.FAILURES)

    def test_bare_id_on_skill_dispatch_line_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "my-skill": "---\nname: my-skill\ndescription: d\n---\n\nInvoke `target-skill` now.\n",
                "target-skill": "---\nname: target-skill\ndescription: d\n---\n",
            },
        )
        validate.check_bare_actionable_refs()
        assert any("target-skill" in f for f in validate.FAILURES)

    def test_self_reference_fails(self, reset_validate):
        """#586's own-id exemption is dropped by #589 — self-refs must be namespaced too."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "my-skill": "---\nname: my-skill\ndescription: d\n---\n\nActivating `my-skill` now.\n",
            },
        )
        validate.check_bare_actionable_refs()
        assert any("my-skill" in f for f in validate.FAILURES)

    def test_bare_id_in_docs_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "notes.md").write_text(
            "See the `foo` skill for details.\n", encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert any("foo" in f for f in validate.FAILURES)

    @pytest.mark.parametrize(
        "relative_path",
        [
            Path(".superpowers/sdd/brief.md"),
            Path("docs/superpowers/plans/brief.md"),
        ],
    )
    def test_ignored_local_planning_roots_are_excluded(self, reset_validate, relative_path):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        planning_file = root / relative_path
        planning_file.parent.mkdir(parents=True)
        planning_file.write_text("Invoke `foo` skill.\n", encoding="utf-8")
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_bare_id_in_readme_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "README.md").write_text(
            "- `foo` — does the foo thing\n", encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert any("foo" in f for f in validate.FAILURES)

    def test_bare_id_in_agent_md_fails(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
            agents=[{"name": "my-agent", "description": "d", "tools": "Read"}],
        )
        (root / "agents" / "my-agent.md").write_text(
            (root / "agents" / "my-agent.md").read_text(encoding="utf-8")
            + "\nSee the `foo` skill.\n",
            encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert any("foo" in f for f in validate.FAILURES)

    def test_tests_dir_excluded_from_scan(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"foo": "---\nname: foo\ndescription: d\n---\n"},
        )
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "notes.md").write_text(
            "References the `foo` skill.\n", encoding="utf-8",
        )
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_exemption_marker_suppresses(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={
                "my-skill": (
                    "---\nname: my-skill\ndescription: d\n---\n\n"
                    "Invoke `target-skill` now. <!-- validate: prose-ref -->\n"
                ),
                "target-skill": "---\nname: target-skill\ndescription: d\n---\n",
            },
        )
        validate.check_bare_actionable_refs()
        assert validate.FAILURES == []

    def test_bare_actionable_refs_live_tree_passes(self, reset_validate, monkeypatch):
        """The real repo must already be fully normalized (#586)."""
        monkeypatch.setattr(validate, "ROOT", Path(__file__).parent.parent)
        validate.FAILURES.clear()
        cache = validate._build_cache()
        validate.check_bare_actionable_refs(cache=cache)
        assert validate.FAILURES == [], f"validate.py failures: {validate.FAILURES}"


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

    # #619: fixture bodies below build sentinel blocks directly rather than
    # via make_plugin_tree(..., agents=...), since each test needs a specific
    # marker combination (pointer-only, pointer-only for a code-touching
    # agent, both, or neither) that the helper's "normal agent" default
    # doesn't parametrize for. check_catalog_completeness only checks marker
    # *presence*, not content-equality, so the block content here is a stand-in.
    _POINTER_BLOCK = (
        "<!-- BEGIN shared/agents/skill-catalog-pointer.md -->\n"
        "Skill catalog pointer.\n"
        "<!-- END shared/agents/skill-catalog-pointer.md -->\n"
    )
    _LANGUAGE_BLOCK = (
        "<!-- BEGIN shared/agents/language-skill-required.md -->\n"
        "Language skill requirement.\n"
        "<!-- END shared/agents/language-skill-required.md -->\n"
    )

    def test_non_code_agent_with_principles_only_passes(self, reset_validate):
        # Non-code agents (product-manager) are whitelisted — pointer-block-only is valid.
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"})
        agents_dir = root / "agents"
        (agents_dir / "product-manager.md").write_text(
            "---\nname: product-manager\ndescription: d\ntools: Read\n---\n\n" + self._POINTER_BLOCK,
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert len(validate.FAILURES) == 0

    def test_code_touching_agent_with_principles_only_fails(self, reset_validate):
        # Code-touching agents must also carry the language-skill-required block.
        root = reset_validate
        make_plugin_tree(root, skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"})
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n\n" + self._POINTER_BLOCK,
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any("language-skill-required" in f for f in validate.FAILURES), (
            "Expected a failure about the missing language-skill-required sentinel block "
            "for a code-touching agent that only carries the skill-catalog-pointer block"
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
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n\n"
            + self._POINTER_BLOCK + "\n" + self._LANGUAGE_BLOCK,
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
        assert any("skill-catalog-pointer" in f and "sentinel block" in f for f in validate.FAILURES)

    def test_ticket_context_lands_in_workflows(self, reset_validate):
        """ticket-context is a member of the '*-context' family — must land in workflows.md, not principles.md."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"ticket-context": "---\nname: ticket-context\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n\n"
            + self._POINTER_BLOCK + "\n" + self._LANGUAGE_BLOCK,
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert len(validate.FAILURES) == 0
        principles_text = (root / "shared" / "agents" / "principles.md").read_text()
        assert "ticket-context" not in principles_text, (
            "ticket-context must not appear in principles.md (belongs in workflows.md)"
        )

    def test_context_family_routes_to_workflows_generically(self, reset_validate):
        """Any '*-context' skill id (not just the literal 'ticket-context') must be
        expected in workflows.md, not principles.md — the routing rule is generic."""
        root = reset_validate
        # catalog= gives full manual control: principles.md gets this text, and
        # languages.md/workflows.md become blank stubs (see helpers.make_plugin_tree),
        # so on-disk 'fixture-context' is deliberately absent from every catalog file.
        make_plugin_tree(
            root,
            skills={"fixture-context": "---\nname: fixture-context\ndescription: d\n---\n"},
            catalog="# no entries\n",
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\nSee @../shared/agents/principles.md and @../shared/agents/languages.md for the skill catalog.\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        assert any(
            "shared/agents/workflows.md" in f and "swe-workbench:fixture-context" in f
            for f in validate.FAILURES
        ), f"expected a workflows.md 'missing entry' failure for fixture-context, got: {validate.FAILURES}"
        assert not any(
            "principles.md" in f and "fixture-context" in f for f in validate.FAILURES
        ), f"fixture-context must not be routed to principles.md, got: {validate.FAILURES}"

    def test_stale_entry_in_wrong_slice_fails(self, reset_validate):
        """A language-* skill listed in principles.md (wrong slice) must fail."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"language-python": "---\nname: language-python\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        shared_dir = root / "shared" / "agents"
        # Manually override: put language-python in principles.md instead of languages.md
        (shared_dir / "principles.md").write_text(
            "- `swe-workbench:language-python` — python skill\n", encoding="utf-8"
        )
        (shared_dir / "languages.md").write_text("\n", encoding="utf-8")
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read\n---\n"
            "\nSee @../shared/agents/principles.md\n",
            encoding="utf-8",
        )
        validate.check_catalog_completeness()
        # principles.md has language-python (wrong slice) → "belongs in languages.md"
        assert any("belongs in" in f for f in validate.FAILURES)


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
# check_adapter_blocks
# ──────────────────────────────────────────────

def _adapter_block(provider="Foo", labels=("Trigger", "Fetch", "Extract → block fields", "Degrade")):
    """Build a well-formed '### Provider' adapter block with the 4 required
    bold-labeled fields, in the given order."""
    lines = [f"### {provider}"]
    for label in labels:
        lines.append(f"- **{label}:** does something for {label.lower()}")
    return "\n".join(lines) + "\n"


class TestCheckAdapterBlocks:
    def _skill_body(self, name, section):
        return f"---\nname: {name}\ndescription: A skill\n---\n\n{section}"

    def test_well_formed_block_passes(self, reset_validate):
        root = reset_validate
        section = "## Adapters\n\n" + _adapter_block("Foo") + "\n## Other Section\n\nMore prose.\n"
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert validate.FAILURES == []

    def test_multiple_well_formed_blocks_pass(self, reset_validate):
        root = reset_validate
        section = (
            "## Adapters\n\n"
            + _adapter_block("Foo")
            + "\n"
            + _adapter_block("Bar")
        )
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert validate.FAILURES == []

    def test_missing_adapters_heading_fails(self, reset_validate):
        root = reset_validate
        section = "## Other Section\n\nNo adapters heading anywhere in this file.\n"
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert len(validate.FAILURES) == 1
        assert any("missing required '## Adapters' section" in f for f in validate.FAILURES)

    def test_missing_label_fails_naming_it(self, reset_validate):
        root = reset_validate
        # Missing "Extract → block fields" entirely.
        block = "### Foo\n- **Trigger:** x\n- **Fetch:** y\n- **Degrade:** z\n"
        section = "## Adapters\n\n" + block
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert len(validate.FAILURES) == 1
        assert "'Extract → block fields'" in validate.FAILURES[0]
        assert "Foo" in validate.FAILURES[0]

    def test_out_of_order_labels_fail(self, reset_validate):
        root = reset_validate
        # Fetch appears before Trigger — violates the required order.
        block = (
            "### Foo\n"
            "- **Fetch:** y\n"
            "- **Trigger:** x\n"
            "- **Extract → block fields:** e\n"
            "- **Degrade:** z\n"
        )
        section = "## Adapters\n\n" + block
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert len(validate.FAILURES) == 1
        assert "missing or out-of-order" in validate.FAILURES[0]

    def test_non_context_skill_without_adapters_section_passes(self, reset_validate):
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n\nNo adapters here.\n"},
        )
        validate.check_adapter_blocks()
        assert validate.FAILURES == []

    def test_empty_adapters_section_fails(self, reset_validate):
        root = reset_validate
        # '## Adapters' heading present but zero '### <Provider>' blocks inside it.
        section = "## Adapters\n\nNothing here yet.\n\n## Other Section\n\nMore prose.\n"
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert len(validate.FAILURES) == 1
        assert "at least one" in validate.FAILURES[0]

    def test_malformed_h3_after_adapters_boundary_is_ignored(self, reset_validate):
        root = reset_validate
        # A '### <heading>' with none of the 4 required fields, placed AFTER the
        # '## Adapters' section ends — must NOT be scanned as an adapter block.
        section = (
            "## Adapters\n\n"
            + _adapter_block("Foo")
            + "\n## Other Section\n\n### Not An Adapter\nSome unrelated prose.\n"
        )
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert validate.FAILURES == []

    def test_fenced_heading_does_not_mask_a_real_malformed_block(self, reset_validate):
        root = reset_validate
        # A well-formed block, then a fenced illustrative example (as
        # docs/extending.md instructs authors to include) containing a bare
        # '## fake heading' — without fence-stripping, _H2_BOUNDARY_RE matches
        # that fenced heading as the '## Adapters' section boundary, silently
        # truncating the section BEFORE the real '### Bar' block that follows
        # the fence — so a genuinely malformed block (missing Trigger) escapes
        # detection entirely. Must still fail.
        section = (
            "## Adapters\n\n"
            + _adapter_block("Foo")
            + "\n"
            "Example adapter shape for authors:\n\n"
            "```\n"
            "## fake heading inside fence\n"
            "```\n\n"
            "### Bar\n"
            "- **Fetch:** y\n"
            "- **Extract → block fields:** e\n"
            "- **Degrade:** z\n"
        )
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert len(validate.FAILURES) == 1
        assert "'Trigger'" in validate.FAILURES[0]
        assert "Bar" in validate.FAILURES[0]

    def test_fenced_field_label_is_not_scanned_as_real(self, reset_validate):
        root = reset_validate
        # A block missing 'Degrade' for real, but with a fenced example
        # afterwards that happens to contain a '- **Degrade:** ...' line.
        # Without fence-stripping, the field-order scan (which searches the
        # whole rest of the block's raw text) would find that fenced label and
        # incorrectly consider the block complete.
        block = (
            "### Foo\n"
            "- **Trigger:** t\n"
            "- **Fetch:** f\n"
            "- **Extract → block fields:** e\n"
            "\n"
            "Example:\n\n"
            "```\n"
            "- **Degrade:** this is inside a fence and must not count\n"
            "```\n"
        )
        section = "## Adapters\n\n" + block
        make_plugin_tree(root, skills={"my-context": self._skill_body("my-context", section)})
        validate.check_adapter_blocks()
        assert len(validate.FAILURES) == 1
        assert "'Degrade'" in validate.FAILURES[0]


class TestStripFencedCodeBlocks:
    """Unit tests for _strip_fenced_code_blocks, isolated from the full
    check_adapter_blocks path (issue surfaced in PR #525 follow-up review)."""

    def test_closing_fence_longer_than_opening_is_stripped(self):
        # CommonMark allows the closing fence to be >= the opening length.
        text = "before\n```\n## fake\n````\nafter\n"
        stripped = validate._strip_fenced_code_blocks(text)
        assert "## fake" not in stripped
        assert "before" in stripped
        assert "after" in stripped

    def test_crlf_fenced_block_is_stripped(self):
        text = "before\r\n```\r\n## fake\r\n```\r\nafter\r\n"
        stripped = validate._strip_fenced_code_blocks(text)
        assert "## fake" not in stripped
        assert "before" in stripped
        assert "after" in stripped


# ──────────────────────────────────────────────
# check_unwired_principle_skills
# ──────────────────────────────────────────────

class TestCheckUnwiredPrincipleSkills:
    def _agent_body(self, extra=""):
        return (
            "---\nname: my-agent\ndescription: d\ntools: Read, Skill\n---\n"
            "\nSee @../shared/agents/principles.md for the skill catalog.\n"
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

    def test_frontmatter_only_wiring_passes(self, reset_validate):
        """A skill listed only in an agent's 'skills:' frontmatter (no
        backticked body mention) counts as wired on its own — retention of
        a body bullet is no longer required once a skill is preloaded."""
        root = reset_validate
        make_plugin_tree(
            root,
            skills={"principle-foo": "---\nname: principle-foo\ndescription: d\n---\n"},
        )
        agents_dir = root / "agents"
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Skill\n"
            "skills:\n  - swe-workbench:principle-foo\n---\n"
            "\nSee @../shared/agents/principles.md for the skill catalog.\n",
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
        """shared/agents/ lives outside agents_dir (issue #603) but is still
        walked into _build_cache()'s agents dict via its own rglob pass, so
        the read-once-per-run guarantee holds for these files too — every
        consumer (check_catalog_completeness, the hazard scanners,
        check_bare_actionable_refs) must hit the None sentinel from the
        cache build rather than re-reading and re-failing to read."""
        root = reset_validate
        _make_full_valid_tree(root)

        # O3: skills.md replaced by 3 slice files — test all three slices
        catalog = root / "shared" / "agents" / slice_name

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
            f"got {read_count['n']} — a consumer may bypass the None sentinel"
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
_SHARED_DIR = Path(__file__).parent.parent / "shared"

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
        shared = _SHARED_DIR / "agents" / "severity-output-contract.md"
        assert shared.exists(), "shared/agents/severity-output-contract.md must exist (O2 canonical source)"

    @pytest.mark.parametrize("agent", _O2_AGENTS)
    def test_agent_references_severity_contract(self, agent):
        path = _AGENTS_DIR / f"{agent}.md"
        assert path.exists(), f"agents/{agent}.md not found"
        text = path.read_text(encoding="utf-8")
        block = sentinel_block(text, "severity-output-contract.md")
        assert block is not None, (
            f"agents/{agent}.md is missing the "
            "'<!-- BEGIN shared/agents/severity-output-contract.md -->' sentinel block — "
            "add it in the severity/output-contract section (O2, issue #235)"
        )
        source = (_SHARED_DIR / "agents" / "severity-output-contract.md").read_text(encoding="utf-8")
        assert block == source, (
            f"agents/{agent}.md's severity-output-contract block has drifted from "
            "shared/agents/severity-output-contract.md — run python3 scripts/sync-shared-blocks.py --write"
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
        shared = _SHARED_DIR / "commands" / "ticket-context-prelude.md"
        assert shared.exists(), "shared/commands/ticket-context-prelude.md must exist (E3 canonical source)"

    def test_shared_prelude_file_contains_canonical_text(self):
        shared = _SHARED_DIR / "commands" / "ticket-context-prelude.md"
        assert shared.exists(), "canonical source file missing"
        assert _CANONICAL_PRELUDE in shared.read_text(encoding="utf-8"), (
            "shared/commands/ticket-context-prelude.md content does not match canonical prelude"
        )

    @pytest.mark.parametrize("cmd", _E3_COMMANDS)
    def test_command_contains_canonical_prelude(self, cmd):
        path = _COMMANDS_DIR / f"{cmd}.md"
        assert path.exists(), f"commands/{cmd}.md not found"
        text = path.read_text(encoding="utf-8")
        assert _CANONICAL_PRELUDE in text, (
            f"commands/{cmd}.md does not contain the canonical ticket-context prelude — "
            "sync from shared/commands/ticket-context-prelude.md (E3, issue #235)"
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
        shared = _SHARED_DIR / "commands" / "interrogation-prelude.md"
        assert shared.exists(), (
            "shared/commands/interrogation-prelude.md must exist (E312 canonical source)"
        )

    def test_shared_prelude_file_contains_canonical_text(self):
        shared = _SHARED_DIR / "commands" / "interrogation-prelude.md"
        assert shared.exists(), "canonical source file missing"
        assert _CANONICAL_INTERROGATION_PRELUDE in shared.read_text(encoding="utf-8"), (
            "shared/commands/interrogation-prelude.md content does not match canonical prelude"
        )

    @pytest.mark.parametrize("cmd", _E312_COMMANDS)
    def test_command_contains_canonical_interrogation_prelude(self, cmd):
        path = _COMMANDS_DIR / f"{cmd}.md"
        assert path.exists(), f"commands/{cmd}.md not found"
        text = path.read_text(encoding="utf-8")
        assert _CANONICAL_INTERROGATION_PRELUDE in text, (
            f"commands/{cmd}.md does not contain the canonical interrogation prelude — "
            "sync from shared/commands/interrogation-prelude.md (E312, issue #312)"
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
            if not (validate._NEVER_SCAN_DIRS & set(p.parts))
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
            if not (validate._NEVER_SCAN_DIRS & set(p.parts))
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
            if not any(f"shared/agents/{s}" in text for s in self.SLICE_FILES):
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

    def test_wf_ref_without_mode_a_no_failure(self, reset_validate):
        """A command that references workflow-development but contains no 'Mode A' token is not flagged."""
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


# ──────────────────────────────────────────────
# check_browser_tool_gate
# ──────────────────────────────────────────────

class TestCheckBrowserToolGate:
    """check_browser_tool_gate: agents/commands referencing browser MCP tools must carry
    a BLOCKED: sentinel and a per-backend install hint (#364)."""

    _REPO_ROOT = Path(__file__).parent.parent

    def test_browser_snapshot_without_blocked_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Use browser_snapshot to capture the page.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert any("BLOCKED:" in f for f in validate.FAILURES)

    def test_browser_snapshot_with_blocked_and_hint_passes(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Use browser_snapshot to capture the page.\n\n"
            "BLOCKED: Playwright MCP not connected — install with `npx @playwright/mcp@latest`.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert len(validate.FAILURES) == 0

    def test_playwright_mcp_ref_in_command_without_blocked_fails(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(exist_ok=True)
        (commands_dir / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\n"
            "Requires @playwright/mcp for E2E testing.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert any("BLOCKED:" in f for f in validate.FAILURES)

    def test_read_console_messages_without_blocked_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Call read_console_messages to get browser logs.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert any("BLOCKED:" in f for f in validate.FAILURES)

    def test_blocked_with_chrome_devtools_hint_passes(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Capture read_console_messages for diagnostics.\n\n"
            "BLOCKED: No Chrome backend connected — install with `npx chrome-devtools-mcp@latest`.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert len(validate.FAILURES) == 0

    def test_blocked_without_install_hint_fails(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(exist_ok=True)
        (commands_dir / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\n"
            "Use browser_snapshot to explore the UI.\n\n"
            "BLOCKED: Playwright MCP not connected.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert any("install hint" in f for f in validate.FAILURES)

    def test_read_network_requests_without_blocked_fails(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(exist_ok=True)
        (commands_dir / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\n"
            "Capture read_network_requests to inspect XHR calls.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert any("BLOCKED:" in f for f in validate.FAILURES)

    def test_no_browser_refs_passes(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "This agent does not reference any browser tools.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert len(validate.FAILURES) == 0

    def test_cache_none_sentinel_emits_failure(self, reset_validate):
        """None sentinel in the agent cache (unreadable file) must emit a failure, not silently skip."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        agent_path = agents_dir / "my-agent.md"
        # Write a file that would pass the gate if readable — but the cache marks it unreadable.
        agent_path.write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Use browser_snapshot.\nBLOCKED: ...\nnpx @playwright/mcp@latest\n",
            encoding="utf-8",
        )
        cache = ({agent_path: None}, {})
        validate.check_browser_tool_gate(cache=cache)
        assert any("could not read file" in f for f in validate.FAILURES), (
            f"Expected 'could not read file' failure for None sentinel; got: {validate.FAILURES}"
        )

    def test_cache_hit_with_valid_content_passes(self, reset_validate):
        """Valid-text cache hit (agent satisfies gate) must not emit any failure."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        agent_path = agents_dir / "my-agent.md"
        content = (
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Use browser_snapshot.\nBLOCKED: ...\n"
            "claude mcp add playwright npx @playwright/mcp@latest\n"
        )
        agent_path.write_text(content, encoding="utf-8")
        cache = ({agent_path: content}, {})
        validate.check_browser_tool_gate(cache=cache)
        assert len(validate.FAILURES) == 0, (
            f"Expected no failures for cached valid content; got: {validate.FAILURES}"
        )

    def test_live_tree_passes(self, reset_validate, monkeypatch):
        """All real agents/commands referencing browser MCP tools must carry BLOCKED: + install hint."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self._REPO_ROOT)
        val.check_browser_tool_gate()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"

    def test_claude_in_chrome_only_passes(self, reset_validate):
        """File referencing only mcp__claude-in-chrome__* is exempt from the install-hint requirement."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Call mcp__claude-in-chrome__read_console_messages to get logs.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert len(validate.FAILURES) == 0

    def test_claude_in_chrome_plus_browser_snapshot_requires_blocked(self, reset_validate):
        """File mixing mcp__claude-in-chrome__* with another browser signal must still carry BLOCKED:."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n"
            "Call mcp__claude-in-chrome__read_console_messages and also browser_snapshot.\n",
            encoding="utf-8",
        )
        validate.check_browser_tool_gate()
        assert any("BLOCKED:" in f for f in validate.FAILURES)


# ──────────────────────────────────────────────
# LSP tool gate (#559)
# ──────────────────────────────────────────────

class TestCheckLspToolGate:
    """check_lsp_tool_gate: any agent granting LSP in its tools: frontmatter must
    carry @../shared/agents/lsp.md, and the shared file must carry the LSP-unavailable
    fallback sentence. The gate must key on the tools: frontmatter scalar only —
    never on body-text "LSP", since shared/agents/principles.md uses "LSP" for the
    Liskov Substitution Principle and most agents preload principle-solid (#559)."""

    def test_grants_lsp_with_include_and_shared_file_passes(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        shared_dir = root / "shared" / "agents"
        shared_dir.mkdir(parents=True, exist_ok=True)
        (shared_dir / "lsp.md").write_text(
            "LSP unavailable — falling back to Grep\n", encoding="utf-8"
        )
        # #619: check_lsp_tool_gate keys on the '<!-- BEGIN shared/agents/lsp.md -->'
        # sentinel marker, not the dead '@../shared/agents/lsp.md' include text.
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Grep, LSP\n---\n\n"
            "<!-- BEGIN shared/agents/lsp.md -->\n"
            "LSP unavailable — falling back to Grep\n"
            "<!-- END shared/agents/lsp.md -->\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert validate.FAILURES == []

    def test_grants_lsp_missing_include_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        shared_dir = root / "shared" / "agents"
        shared_dir.mkdir(parents=True, exist_ok=True)
        (shared_dir / "lsp.md").write_text(
            "LSP unavailable — falling back to Grep\n", encoding="utf-8"
        )
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Grep, LSP\n---\n\n"
            "No shared include here.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert any("shared/agents/lsp.md" in f for f in validate.FAILURES)

    def test_grants_lsp_list_form_missing_include_fails(self, reset_validate):
        """List-form tools: (e.g. `tools:\\n  - Read\\n  - LSP`) must be treated
        as granting LSP just like the scalar comma-separated form — otherwise a
        contributor could silently bypass the gate by switching YAML encodings (#559)."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        shared_dir = root / "shared" / "agents"
        shared_dir.mkdir(parents=True, exist_ok=True)
        (shared_dir / "lsp.md").write_text(
            "LSP unavailable — falling back to Grep\n", encoding="utf-8"
        )
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools:\n  - Read\n  - LSP\n---\n\n"
            "No shared include here.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert any("shared/agents/lsp.md" in f for f in validate.FAILURES)

    def test_grants_lsp_shared_file_reworded_sentence_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        shared_dir = root / "shared" / "agents"
        shared_dir.mkdir(parents=True, exist_ok=True)
        (shared_dir / "lsp.md").write_text(
            "LSP is unavailable, fall back to Grep instead.\n", encoding="utf-8"
        )
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Grep, LSP\n---\n\n"
            "See @../shared/agents/lsp.md for LSP usage guidance.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert any("fallback sentence" in f for f in validate.FAILURES)

    def test_grants_lsp_shared_file_absent_fails(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Grep, LSP\n---\n\n"
            "See @../shared/agents/lsp.md for LSP usage guidance.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert any("shared/agents/lsp.md" in f for f in validate.FAILURES)

    def test_liskov_substitution_body_text_does_not_trigger_gate(self, reset_validate):
        """The Liskov regression guard: body prose mentioning LSP must never be
        mistaken for a tools: grant — this is the test that matters most."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Grep\n---\n\n"
            "LSP is about honoring contracts between base and derived types.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert validate.FAILURES == []

    def test_lspx_token_not_treated_as_granting(self, reset_validate):
        """Token-boundary guard: a substring test would match a hypothetical LSPX tool."""
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, LSPX\n---\n\n"
            "Body text without any LSP shared include.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert validate.FAILURES == []

    def test_no_agent_grants_lsp_no_shared_file_passes(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\ntools: Read, Grep\n---\n\n"
            "Nothing special here.\n",
            encoding="utf-8",
        )
        validate.check_lsp_tool_gate()
        assert validate.FAILURES == []


# ──────────────────────────────────────────────
# e2e-test-writer agent structural assertions
# ──────────────────────────────────────────────

class TestE2eTestWriterAgent:
    """Integration tests: assert agents/e2e-test-writer.md satisfies structural invariants (#364)."""

    AGENT_PATH = Path(__file__).parent.parent / "agents" / "e2e-test-writer.md"

    def test_file_exists(self):
        assert self.AGENT_PATH.exists(), "agents/e2e-test-writer.md must exist"

    def test_frontmatter_fields(self):
        import re
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "frontmatter block not found"
        fm_text = match.group(1)
        assert "name: e2e-test-writer" in fm_text
        assert "description:" in fm_text
        assert "model: sonnet" in fm_text
        assert re.search(r"tools:.*\bSkill\b", fm_text), "tools: must include Skill"

    def test_blocked_sentinel_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "BLOCKED:" in text, "agent must carry a BLOCKED: hard-gate sentinel"

    def test_playwright_mcp_install_hint_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "claude mcp add" in text and "@playwright/mcp" in text, (
            "agent must include the Playwright MCP install hint (claude mcp add ... @playwright/mcp)"
        )

    def test_principle_testing_wired(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        fm = validate.parse_frontmatter(self.AGENT_PATH, text=text)
        fm_skills = fm.get("skills") if fm else None
        wired = "`swe-workbench:principle-testing`" in text or (
            isinstance(fm_skills, list) and "swe-workbench:principle-testing" in fm_skills
        )
        assert wired, "agent must reference swe-workbench:principle-testing (body or frontmatter)"

    def test_shared_skills_include(self):
        """e2e-test-writer is a normal code-touching agent — must carry both
        the skill-catalog-pointer and language-skill-required sentinel blocks,
        byte-identical to their sources (#619)."""
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        shared_dir = self.AGENT_PATH.parent.parent / "shared" / "agents"
        for fragment in ("skill-catalog-pointer.md", "language-skill-required.md"):
            block = sentinel_block(text, fragment)
            assert block is not None, (
                f"agent must carry the '<!-- BEGIN shared/agents/{fragment} -->' sentinel block"
            )
            source = (shared_dir / fragment).read_text(encoding="utf-8")
            assert block == source, (
                f"agent's {fragment} block has drifted from shared/agents/{fragment} — "
                "run python3 scripts/sync-shared-blocks.py --write"
            )

    def test_agent_and_skill_ref_checks_pass(self, reset_validate, monkeypatch):
        """The real file must pass check_agents() and check_agent_skill_refs() against the live tree."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self.AGENT_PATH.parent.parent)
        val.FAILURES.clear()
        cache = val._build_cache()
        val.check_agents(cache=cache)
        val.check_agent_skill_refs(cache=cache)
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"


# ──────────────────────────────────────────────
# e2e-test-verifier agent structural assertions
# ──────────────────────────────────────────────

class TestE2eTestVerifierAgent:
    """Integration tests: assert agents/e2e-test-verifier.md satisfies structural invariants (#364)."""

    AGENT_PATH = Path(__file__).parent.parent / "agents" / "e2e-test-verifier.md"

    def test_file_exists(self):
        assert self.AGENT_PATH.exists(), "agents/e2e-test-verifier.md must exist"

    def test_frontmatter_fields(self):
        import re
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "frontmatter block not found"
        fm_text = match.group(1)
        assert "name: e2e-test-verifier" in fm_text
        assert "description:" in fm_text
        assert "model: haiku" in fm_text
        assert re.search(r"tools:.*\bRead\b", fm_text)
        assert re.search(r"tools:.*\bBash\b", fm_text), "tools: must include Bash (runs specs)"
        assert re.search(r"tools:.*\bSkill\b", fm_text)

    def test_no_browser_mcp_tools_in_frontmatter(self):
        """Verifier uses the CLI runner, not browser MCP — tools: must not list MCP browser tools."""
        import re
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "frontmatter block not found"
        fm_text = match.group(1)
        tools_line = next(
            (line for line in fm_text.splitlines() if line.startswith("tools:")), ""
        )
        assert "browser_snapshot" not in tools_line
        assert "mcp__" not in tools_line

    def test_blocked_sentinel_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "BLOCKED:" in text, (
            "agent must include a BLOCKED: sentinel for the missing-runner case"
        )

    def test_boundary_section_present(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        assert "Boundary vs. `swe-workbench:test-reviewer`" in text, (
            "agent must have a Boundary vs. test-reviewer section"
        )

    def test_principle_testing_wired(self):
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        fm = validate.parse_frontmatter(self.AGENT_PATH, text=text)
        fm_skills = fm.get("skills") if fm else None
        wired = "`swe-workbench:principle-testing`" in text or (
            isinstance(fm_skills, list) and "swe-workbench:principle-testing" in fm_skills
        )
        assert wired, "agent must reference swe-workbench:principle-testing (body or frontmatter)"

    def test_shared_skills_include(self):
        """e2e-test-verifier is a normal code-touching agent — must carry both
        the skill-catalog-pointer and language-skill-required sentinel blocks,
        byte-identical to their sources (#619)."""
        text = self.AGENT_PATH.read_text(encoding="utf-8")
        shared_dir = self.AGENT_PATH.parent.parent / "shared" / "agents"
        for fragment in ("skill-catalog-pointer.md", "language-skill-required.md"):
            block = sentinel_block(text, fragment)
            assert block is not None, (
                f"agent must carry the '<!-- BEGIN shared/agents/{fragment} -->' sentinel block"
            )
            source = (shared_dir / fragment).read_text(encoding="utf-8")
            assert block == source, (
                f"agent's {fragment} block has drifted from shared/agents/{fragment} — "
                "run python3 scripts/sync-shared-blocks.py --write"
            )

    def test_agent_and_skill_ref_checks_pass(self, reset_validate, monkeypatch):
        """The real file must pass check_agents() and check_agent_skill_refs() against the live tree."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", self.AGENT_PATH.parent.parent)
        val.FAILURES.clear()
        cache = val._build_cache()
        val.check_agents(cache=cache)
        val.check_agent_skill_refs(cache=cache)
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"


# ──────────────────────────────────────────────
# check_workflow_full_fidelity_mandate
# ──────────────────────────────────────────────

class TestCheckWorkflowFullFidelityMandate:
    """Guards the Mode A full-fidelity mandate in SKILL.md and the template header (#455)."""

    def _write_skill(self, root, mode_a_body):
        skill_dir = root / "skills" / "workflow-development"
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "## Plan-Time Behavior (Mode A)\n"
            + mode_a_body
            + "\n## Implementation-Time Behavior (Mode B)\n"
        )
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    def _write_template(self, root, header):
        tmpl_dir = root / "skills" / "workflow-development" / "templates"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        content = header + "\n\n````markdown\n## Workflow\n````\n"
        (tmpl_dir / "plan-workflow-section.md").write_text(content, encoding="utf-8")

    def test_both_files_correct_passes(self, reset_validate):
        root = reset_validate
        self._write_skill(root, "Reproduce in full and verbatim — substitute [[detect:KEY]] markers.\n")
        self._write_template(root, "Copy this section — do not abridge.")
        validate.check_workflow_full_fidelity_mandate()
        assert validate.FAILURES == [], f"Expected no failures but got: {validate.FAILURES}"

    def test_skill_md_file_absent_fails(self, reset_validate):
        root = reset_validate
        # Neither SKILL.md nor the template exists — the missing-file branch fires.
        validate.check_workflow_full_fidelity_mandate()
        assert any("missing" in f for f in validate.FAILURES), (
            "Expected a failure containing 'missing' when SKILL.md does not exist"
        )

    def test_skill_md_missing_in_full_and_verbatim_fails(self, reset_validate):
        root = reset_validate
        self._write_skill(root, "Substitute [[detect:KEY]] markers only.\n")
        self._write_template(root, "Copy this section — do not abridge.")
        validate.check_workflow_full_fidelity_mandate()
        assert any("full-fidelity mandate" in f for f in validate.FAILURES), (
            "Expected a failure containing 'full-fidelity mandate' when Mode A mandate tokens are absent"
        )

    def test_skill_md_missing_verbatim_fails(self, reset_validate):
        root = reset_validate
        # Has "in full" but NOT "verbatim"
        self._write_skill(root, "Reproduce the template in full — substitute [[detect:KEY]] markers.\n")
        self._write_template(root, "Copy this section — do not abridge.")
        validate.check_workflow_full_fidelity_mandate()
        assert any("full-fidelity mandate" in f for f in validate.FAILURES), (
            "Expected a failure containing 'full-fidelity mandate' when 'verbatim' token is absent"
        )

    def test_skill_md_missing_in_full_fails(self, reset_validate):
        root = reset_validate
        # Has "verbatim" but NOT "in full" — mirrors test_skill_md_missing_verbatim_fails
        # to guard both halves of the `or` in the guard condition independently.
        self._write_skill(root, "Reproduce verbatim — substitute [[detect:KEY]] markers.\n")
        self._write_template(root, "Copy this section — do not abridge.")
        validate.check_workflow_full_fidelity_mandate()
        assert any("full-fidelity mandate" in f for f in validate.FAILURES), (
            "Expected a failure when 'in full' is absent from Mode A paragraph"
        )

    def test_template_missing_no_abridge_fails(self, reset_validate):
        root = reset_validate
        self._write_skill(root, "Reproduce in full and verbatim — substitute [[detect:KEY]] markers.\n")
        self._write_template(root, "Copy this section into your plan.")
        validate.check_workflow_full_fidelity_mandate()
        assert any("do not abridge" in f for f in validate.FAILURES), (
            "Expected a failure naming 'do not abridge' when that phrase is missing from template header"
        )

    def test_real_repo_passes(self, reset_validate, monkeypatch):
        """After applying changes #1 and #2, the real files must pass cleanly."""
        import validate as val
        real_root = Path(__file__).parent.parent
        monkeypatch.setattr(val, "ROOT", real_root)
        val.check_workflow_full_fidelity_mandate()
        assert val.FAILURES == [], f"validate.py failures on real repo: {val.FAILURES}"


# ──────────────────────────────────────────────────────────────
# Phase 4 dispatches BOTH reviewers in parallel (#458)
# ──────────────────────────────────────────────────────────────


class TestPhase4DispatchesBothReviewers:
    """Every Phase 4 dispatch site must name both reviewers AND the word
    'parallel', ensuring neither can be omitted and they run concurrently.

    Regression guard for issue #458.
    """

    REAL_ROOT = Path(__file__).parent.parent

    # (file_path_relative, phase4_start_marker, terminator_prefix)
    SITES = [
        (
            "skills/workflow-development/SKILL.md",
            "### Phase 4: Review",
            "### Phase 5",
        ),
        (
            "commands/implement.md",
            "**Phase 4 — Review**",
            "**Phase 5",
        ),
        (
            "skills/workflow-development/templates/plan-workflow-section.md",
            "### Phase 4: Review",
            "### Phase 5",
        ),
        (
            "skills/workflow-extend/SKILL.md",
            "**Phase 4 (Review):**",
            "## Phase D",
        ),
        (
            "commands/extend.md",
            "**Phase 4 — Review**",
            "**Phase 5",
        ),
    ]

    REQUIRED_TOKENS = [
        "superpowers:requesting-code-review",
        "swe-workbench:reviewer",
        "parallel",
    ]

    def _extract_phase4_section(self, text: str, start_marker: str, terminator: str) -> str:
        """Return the text from start_marker up to (but not including) terminator."""
        start = text.find(start_marker)
        if start == -1:
            return ""  # all required tokens register as missing → clear assertion failure
        end = text.find(terminator, start + len(start_marker))
        if end == -1:
            return text[start:]
        return text[start:end]

    def test_all_dispatch_sites_name_both_reviewers_and_parallel(self):
        """Each Phase 4 section must contain both reviewer identifiers and 'parallel'."""
        failures = []
        for rel_path, start_marker, terminator in self.SITES:
            full_path = self.REAL_ROOT / rel_path
            text = full_path.read_text(encoding="utf-8")
            section = self._extract_phase4_section(text, start_marker, terminator)
            section_lower = section.lower()
            missing = [
                token
                for token in self.REQUIRED_TOKENS
                if token.lower() not in section_lower
            ]
            if missing:
                failures.append(
                    f"{rel_path}: missing {missing} in Phase 4 section"
                )
        assert not failures, (
            "Phase 4 dispatch sites are missing required tokens (#458):\n"
            + "\n".join(f"  {f}" for f in failures)
        )


# ──────────────────────────────────────────────
# check_no_echo_var_hazard
# ──────────────────────────────────────────────

class TestCheckNoEchoVarHazard:
    """zsh (the user's likely login shell) expands backslash escapes in echo's
    argument, corrupting embedded JSON piped or redirected through it (#549).
    See shared/docs/shell-echo-vs-printf.md."""

    def _skill_with_block(self, root, name, block_lines):
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = (
            f"---\nname: {name}\ndescription: d\n---\n\n"
            "```bash\n" + "\n".join(block_lines) + "\n```\n"
        )
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    # ── must flag ──

    def test_echo_redirect_to_file_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" > /tmp/payload.json'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f and "printf" in f for f in validate.FAILURES)

    def test_echo_append_redirect_to_file_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" >> /tmp/payload.json'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_piped_into_python_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(
            root, "my-skill",
            ["PR_STATE=$(echo \"$PR_JSON\" | python3 -c 'import sys; print(sys.stdin.read())')"],
        )
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_piped_into_grep_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ["echo \"$RESP\" | grep -q '422'"])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    # ── must not flag ──

    def test_echo_literal_string_no_variable_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "literal status message"'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_echo_to_stderr_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "warn: $x" >&2'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_non_echo_redirect_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['gh api foo > "$STATE_FILE"'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_non_echo_devnull_redirect_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ["cmd 2>/dev/null"])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_echo_with_logical_or_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$x" || true'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_printf_correct_form_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ["printf '%s' \"$JSON\" > /tmp/payload.json"])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_echo_with_ampersand_bounded_command_passes(self, reset_validate):
        """A benign echo followed by an unrelated '&&'-joined piped command
        must not be misattributed as the echo's own hazard."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$a" && ls | wc -l'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_echo_quoted_devnull_redirect_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$VAR" > "/dev/null"'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    # ── quote-aware / command-position hardening ──

    def test_echo_json_with_embedded_semicolon_flags(self, reset_validate):
        """A literal ';' inside the quoted argument must not truncate the
        scan before the real pipe that follows it on the same line."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON; extra" | grep -q x'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_in_brace_group_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['{ echo "$JSON" | tee out; }'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_in_case_arm_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['  a) echo "$JSON" > out ;;'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    # ── structural coverage ──

    def test_reference_subdir_file_is_scanned(self, reset_validate):
        root = reset_validate
        ref_dir = root / "skills" / "my-skill" / "reference"
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "notes.md").write_text(
            "# Notes\n\n```bash\necho \"$JSON\" > /tmp/payload.json\n```\n",
            encoding="utf-8",
        )
        validate.check_no_echo_var_hazard()
        assert any("reference/notes.md" in f for f in validate.FAILURES)

    def test_prose_mention_outside_fence_is_ignored(self, reset_validate):
        root = reset_validate
        skill_dir = root / "skills" / "my-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: d\n---\n\n"
            "Don't echo $JSON straight to a file — pipe it through printf instead.\n",
            encoding="utf-8",
        )
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_commands_dir_is_scanned(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\n```bash\necho \"$JSON\" > /tmp/x.json\n```\n",
            encoding="utf-8",
        )
        validate.check_no_echo_var_hazard()
        assert any("my-cmd.md" in f for f in validate.FAILURES)

    def test_agents_dir_is_scanned(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n```bash\necho \"$JSON\" > /tmp/x.json\n```\n",
            encoding="utf-8",
        )
        validate.check_no_echo_var_hazard()
        assert any("my-agent.md" in f for f in validate.FAILURES)

    def test_live_tree_has_zero_violations(self, reset_validate, monkeypatch):
        """After the existing-site normalization (issue #549), the real tree is clean."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", Path(__file__).parent.parent)
        val.FAILURES.clear()
        val.check_no_echo_var_hazard()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"

    # ── PR #564 review follow-ups ──

    def test_echo_ampersand_greater_redirect_flags(self, reset_validate):
        """'&>'/'&>>' (combined stdout+stderr redirect) must not be misread as
        a bare '&'/'&&' command separator — it's a real file redirect."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" &> /tmp/out.json'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_ampersand_greater_append_redirect_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" &>> /tmp/out.json'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_ampersand_greater_devnull_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" &> /dev/null'])
        validate.check_no_echo_var_hazard()
        assert validate.FAILURES == []

    def test_echo_command_substitution_flags(self, reset_validate):
        """The escape-expansion risk applies to whatever string is echoed,
        not just bare variables — $(...) carries the same risk."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$(cat file.json)" > out.txt'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_backtick_substitution_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "`cat file.json`" > out.txt'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_echo_line_continuation_flags(self, reset_validate):
        """A hazard split across a backslash line-continuation is one logical
        bash command and must not evade per-physical-line scanning."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" \\', '  > /tmp/payload.json'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_odd_triple_trailing_backslash_is_a_continuation(self, reset_validate):
        """3 trailing backslashes: the last is unescaped (odd parity), so this
        IS still a continuation — a fixed 1-vs-2 suffix check would miss it."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['echo "$JSON" \\\\\\', '  > /tmp/payload.json'])
        validate.check_no_echo_var_hazard()
        assert any("echo" in f for f in validate.FAILURES)

    def test_escaped_trailing_backslash_is_not_a_continuation(self, reset_validate):
        """A line ending in an escaped '\\\\' (literal backslash) is NOT a
        bash line-continuation — must not be joined with the next line."""
        root = reset_validate
        self._skill_with_block(
            root, "my-skill",
            ['echo "literal ending in backslash \\\\"', 'echo "$OTHER" | grep x'],
        )
        validate.check_no_echo_var_hazard()
        # The second line is its own independent hazard — still flagged, and
        # exactly once — a wrongful join would either merge it into a single
        # (differently-worded) violation or mask it entirely.
        assert len(validate.FAILURES) == 1
        assert "echo" in validate.FAILURES[0]


# ──────────────────────────────────────────────
# check_no_printf_var_format
# ──────────────────────────────────────────────

class TestCheckNoPrintfVarFormat:
    """`printf "$VAR"` uses $VAR as the FORMAT string, not an argument — a
    literal %s inside it reads a nonexistent argument, and %n is a
    memory-write primitive in some printf(1) implementations (#549 PR #564
    review follow-up). Must always be printf '%s' "$VAR"."""

    def _skill_with_block(self, root, name, block_lines):
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = (
            f"---\nname: {name}\ndescription: d\n---\n\n"
            "```bash\n" + "\n".join(block_lines) + "\n```\n"
        )
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    def test_bare_double_quoted_var_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf "$VAR"'])
        validate.check_no_printf_var_format()
        assert any("printf" in f for f in validate.FAILURES)

    def test_bare_braced_var_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf "${VAR}"'])
        validate.check_no_printf_var_format()
        assert any("printf" in f for f in validate.FAILURES)

    def test_bare_unquoted_var_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf $VAR'])
        validate.check_no_printf_var_format()
        assert any("printf" in f for f in validate.FAILURES)

    def test_dash_v_bare_var_flags(self, reset_validate):
        """printf -v NAME "$VAR" — the format-string position is still the
        first token after the -v NAME pair, not NAME itself."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf -v out "$VAR"'])
        validate.check_no_printf_var_format()
        assert any("printf" in f for f in validate.FAILURES)

    def test_literal_format_with_var_argument_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ["printf '%s' \"$VAR\""])
        validate.check_no_printf_var_format()
        assert validate.FAILURES == []

    def test_literal_format_with_newline_and_var_argument_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ["printf '%s\\n' \"$VAR\""])
        validate.check_no_printf_var_format()
        assert validate.FAILURES == []

    def test_literal_format_no_variable_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ["printf 'literal only'"])
        validate.check_no_printf_var_format()
        assert validate.FAILURES == []

    def test_live_tree_has_zero_violations(self, reset_validate, monkeypatch):
        import validate as val
        monkeypatch.setattr(val, "ROOT", Path(__file__).parent.parent)
        val.FAILURES.clear()
        val.check_no_printf_var_format()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"


# ──────────────────────────────────────────────
# check_no_unenumerated_tmp_write
# ──────────────────────────────────────────────

class TestCheckNoUnenumeratedTmpWrite:
    """A literal /tmp/... write outside $RUN_DIR and outside
    clean-state-files.sh's sanctioned PR-keyed prefixes is un-enumerable by
    construction — nothing can ever reap it by name, and nothing bounds two
    concurrent flows from clobbering it (#552). Regression gate for the old
    global, never-reaped /tmp/payload.json."""

    def _skill_with_block(self, root, name, block_lines):
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = (
            f"---\nname: {name}\ndescription: d\n---\n\n"
            "```bash\n" + "\n".join(block_lines) + "\n```\n"
        )
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    # ── must flag ──

    def test_unsanctioned_redirect_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf \'%s\' "$X" > /tmp/payload.json'])
        validate.check_no_unenumerated_tmp_write()
        assert any("RUN_DIR" in f for f in validate.FAILURES)

    def test_unsanctioned_append_redirect_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf \'%s\' "$X" >> /tmp/scratch.txt'])
        validate.check_no_unenumerated_tmp_write()
        assert any("RUN_DIR" in f for f in validate.FAILURES)

    def test_unsanctioned_body_file_flag_flags(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['gh pr edit "$N" --body-file /tmp/scratch.txt'])
        validate.check_no_unenumerated_tmp_write()
        assert any("RUN_DIR" in f for f in validate.FAILURES)

    def test_unsanctioned_wrong_prefix_flags(self, reset_validate):
        """A /tmp/ basename that doesn't match any sanctioned prefix (e.g. a
        plausible-looking but unlisted name) must still be flagged."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['cmd > /tmp/some-other-flow-42.json'])
        validate.check_no_unenumerated_tmp_write()
        assert any("RUN_DIR" in f for f in validate.FAILURES)

    # ── must not flag ──

    def test_run_dir_rooted_redirect_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['printf \'%s\' "$X" > "$RUN_DIR/payload.json"'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_run_dir_rooted_body_file_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['gh pr edit "$N" --body-file "$RUN_DIR/body.md"'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_run_dir_root_dir_prefix_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['cmd > /tmp/swe-workbench-run/foo'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_pr_review_dir_prefix_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['cmd > "/tmp/swe-workbench-pr-review/${PR}.json"'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_address_feedback_dir_prefix_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['cmd > "/tmp/swe-workbench-address-feedback/${PR}.json"'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    @pytest.mark.parametrize("prefix", [
        "capture", "report-issue", "audit-emit", "extend", "hotfix", "cleanup-followup", "bug-triage",
    ])
    def test_sanctioned_basename_prefixes_pass(self, reset_validate, prefix):
        root = reset_validate
        self._skill_with_block(root, "my-skill", [f'cmd > /tmp/{prefix}-repo-42.md'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_variable_rooted_target_passes(self, reset_validate):
        """A target that isn't a literal /tmp/... path at all (e.g. a plain
        variable) is outside this gate's scope entirely."""
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['gh api foo > "$STATE_FILE"'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_devnull_redirect_passes(self, reset_validate):
        root = reset_validate
        self._skill_with_block(root, "my-skill", ['cmd 2>/dev/null'])
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    def test_prose_mention_outside_fence_is_ignored(self, reset_validate):
        root = reset_validate
        skill_dir = root / "skills" / "my-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: d\n---\n\n"
            "Write the payload to /tmp/payload.json for inspection.\n",
            encoding="utf-8",
        )
        validate.check_no_unenumerated_tmp_write()
        assert validate.FAILURES == []

    # ── structural coverage ──

    def test_reference_subdir_file_is_scanned(self, reset_validate):
        root = reset_validate
        ref_dir = root / "skills" / "my-skill" / "reference"
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "notes.md").write_text(
            "# Notes\n\n```bash\ncmd > /tmp/unsanctioned.json\n```\n",
            encoding="utf-8",
        )
        validate.check_no_unenumerated_tmp_write()
        assert any("reference/notes.md" in f for f in validate.FAILURES)

    def test_commands_dir_is_scanned(self, reset_validate):
        root = reset_validate
        commands_dir = root / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "my-cmd.md").write_text(
            "---\ndescription: d\n---\n\n```bash\ncmd > /tmp/unsanctioned.json\n```\n",
            encoding="utf-8",
        )
        validate.check_no_unenumerated_tmp_write()
        assert any("my-cmd.md" in f for f in validate.FAILURES)

    def test_agents_dir_is_scanned(self, reset_validate):
        root = reset_validate
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "my-agent.md").write_text(
            "---\nname: my-agent\ndescription: d\n---\n\n```bash\ncmd > /tmp/unsanctioned.json\n```\n",
            encoding="utf-8",
        )
        validate.check_no_unenumerated_tmp_write()
        assert any("my-agent.md" in f for f in validate.FAILURES)

    def test_live_tree_has_zero_violations(self, reset_validate, monkeypatch):
        """After #552's allowlist extension + RUN_DIR wiring, the real tree is clean."""
        import validate as val
        monkeypatch.setattr(val, "ROOT", Path(__file__).parent.parent)
        val.FAILURES.clear()
        val.check_no_unenumerated_tmp_write()
        assert val.FAILURES == [], f"validate.py failures: {val.FAILURES}"
