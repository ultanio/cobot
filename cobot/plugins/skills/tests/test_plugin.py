"""Tests for SkillsPlugin."""

import pytest
from pathlib import Path

from ..models import (
    escape_xml,
    parse_frontmatter,
    resolve_relative_paths,
    validate_skill_name,
)
from ..cli import _is_local_path
from ..plugin import SkillsPlugin, create_plugin


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_skills_plugin(self):
        assert isinstance(create_plugin(), SkillsPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "skills"

    def test_capabilities(self):
        assert "tools" in create_plugin().meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 19

    def test_implements_system_prompt(self):
        assert "loop.transform_system_prompt" in create_plugin().meta.implements

    def test_implements_cli_commands(self):
        assert "cli.commands" in create_plugin().meta.implements

    def test_dependencies(self):
        assert "config" in create_plugin().meta.dependencies

    def test_optional_dependencies(self):
        assert "workspace" in create_plugin().meta.optional_dependencies


# === Configuration ===


class TestConfigure:
    def test_default_paths(self):
        plugin = create_plugin()
        plugin.configure({})
        assert len(plugin._paths) == 2
        assert plugin._paths[0] == Path("./skills")

    def test_custom_paths_list(self):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": ["/tmp/skills", "~/my-skills"]}})
        assert len(plugin._paths) == 2
        assert plugin._paths[0] == Path("/tmp/skills")

    def test_custom_paths_string(self):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": "/tmp/skills"}})
        assert len(plugin._paths) == 1

    def test_paths_from_paths_section(self):
        plugin = create_plugin()
        plugin.configure({"paths": {"skills": "./my-skills"}})
        assert plugin._paths[0] == Path("./my-skills")

    def test_disabled_skills(self):
        plugin = create_plugin()
        plugin.configure({"skills": {"disabled": ["bad-skill"]}})
        assert "bad-skill" in plugin._disabled

    def test_trusted_npubs(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "trusted": [
                    {"npub": "npub1abc", "name": "Alice"},
                    {"npub": "npub1def", "name": "Bob"},
                ]
            }
        )
        assert "npub1abc" in plugin._trusted_npubs
        assert "npub1def" in plugin._trusted_npubs

    def test_trusted_empty(self):
        plugin = create_plugin()
        plugin.configure({})
        assert len(plugin._trusted_npubs) == 0


# === Frontmatter Parsing ===


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\nname: test-skill\ndescription: A test\n---\n# Body"
        result = parse_frontmatter(content)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test"

    def test_full_frontmatter(self):
        content = (
            "---\nname: test-skill\ndescription: A test\n"
            "author: npub1abc\nversion: 1.0.0\n---\n# Body"
        )
        result = parse_frontmatter(content)
        assert result["name"] == "test-skill"
        assert result["author"] == "npub1abc"
        assert result["version"] == "1.0.0"

    def test_no_frontmatter(self):
        content = "# Just a markdown file\nNo frontmatter here."
        assert parse_frontmatter(content) == {}

    def test_malformed_yaml(self):
        content = "---\n: invalid: yaml: [\n---\n# Body"
        assert parse_frontmatter(content) == {}

    def test_empty_frontmatter(self):
        content = "---\n---\n# Body"
        assert parse_frontmatter(content) == {}

    def test_non_dict_frontmatter(self):
        content = "---\n- item1\n- item2\n---\n# Body"
        assert parse_frontmatter(content) == {}

    def test_minimal_fields(self):
        content = "---\nname: my-skill\ndescription: Does things\n---\n"
        result = parse_frontmatter(content)
        assert result["name"] == "my-skill"
        assert "author" not in result


# === Name Validation ===


class TestValidateSkillName:
    def test_valid_simple(self):
        assert validate_skill_name("my-skill") is True

    def test_valid_numbers(self):
        assert validate_skill_name("skill-123") is True

    def test_valid_no_hyphens(self):
        assert validate_skill_name("skill") is True

    def test_invalid_uppercase(self):
        assert validate_skill_name("My-Skill") is False

    def test_invalid_underscore(self):
        assert validate_skill_name("my_skill") is False

    def test_invalid_leading_hyphen(self):
        assert validate_skill_name("-skill") is False

    def test_invalid_trailing_hyphen(self):
        assert validate_skill_name("skill-") is False

    def test_invalid_consecutive_hyphens(self):
        assert validate_skill_name("my--skill") is False

    def test_invalid_empty(self):
        assert validate_skill_name("") is False

    def test_invalid_too_long(self):
        assert validate_skill_name("a" * 65) is False

    def test_valid_max_length(self):
        assert validate_skill_name("a" * 64) is True


# === XML Escaping ===


class TestEscapeXml:
    def test_no_escaping(self):
        assert escape_xml("hello world") == "hello world"

    def test_ampersand(self):
        assert escape_xml("A & B") == "A &amp; B"

    def test_angle_brackets(self):
        assert escape_xml("<tag>") == "&lt;tag&gt;"

    def test_quotes(self):
        assert escape_xml('"hello"') == "&quot;hello&quot;"


# === Relative Path Resolution ===


class TestResolveRelativePaths:
    def test_resolves_md_path(self):
        content = "See ./rules/components.md for details"
        base = Path("/home/user/skills/react")
        result = resolve_relative_paths(content, base)
        assert "/home/user/skills/react/rules/components.md" in result
        assert "./" not in result

    def test_resolves_multiple_paths(self):
        content = "Check ./a.md and ./b/c.md"
        base = Path("/skills/test")
        result = resolve_relative_paths(content, base)
        assert "/skills/test/a.md" in result
        assert "/skills/test/b/c.md" in result

    def test_no_relative_paths(self):
        content = "No paths here, just text."
        base = Path("/skills/test")
        assert resolve_relative_paths(content, base) == content

    def test_preserves_non_path_text(self):
        content = "Read ./guide.md then do something else"
        base = Path("/skills/test")
        result = resolve_relative_paths(content, base)
        assert "then do something else" in result


# === Discovery ===


class TestDiscovery:
    def _make_skill_dir(self, tmp_path: Path, name: str, **kwargs) -> Path:
        """Create a skill directory with SKILL.md."""
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        fm_fields = {
            "name": name,
            "description": f"Test skill {name}",
            **kwargs,
        }
        fm_lines = ["---"]
        for k, v in fm_fields.items():
            fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        fm_lines.append(f"# {name}")

        (skill_dir / "SKILL.md").write_text("\n".join(fm_lines))
        return skill_dir

    def test_discovers_single_skill(self, tmp_path):
        self._make_skill_dir(tmp_path, "my-skill")

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path

        plugin._discover_skills()

        assert "my-skill" in plugin._skills
        assert plugin._skills["my-skill"].description == "Test skill my-skill"

    def test_discovers_multiple_skills(self, tmp_path):
        self._make_skill_dir(tmp_path, "skill-a")
        self._make_skill_dir(tmp_path, "skill-b")

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert len(plugin._skills) == 2

    def test_skips_disabled_skills(self, tmp_path):
        self._make_skill_dir(tmp_path, "good-skill")
        self._make_skill_dir(tmp_path, "bad-skill")

        plugin = create_plugin()
        plugin.configure(
            {"skills": {"paths": [str(tmp_path)], "disabled": ["bad-skill"]}}
        )
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert "good-skill" in plugin._skills
        assert "bad-skill" not in plugin._skills

    def test_skips_invalid_name(self, tmp_path):
        skill_dir = tmp_path / "Invalid_Name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Invalid_Name\ndescription: Bad\n---\n"
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert len(plugin._skills) == 0

    def test_skips_missing_frontmatter(self, tmp_path):
        skill_dir = tmp_path / "no-fm"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Just markdown\nNo frontmatter.")

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert len(plugin._skills) == 0

    def test_skips_name_mismatch(self, tmp_path):
        skill_dir = tmp_path / "dir-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: different-name\ndescription: Mismatch\n---\n"
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert len(plugin._skills) == 0

    def test_precedence_first_path_wins(self, tmp_path):
        path_a = tmp_path / "workspace"
        path_b = tmp_path / "user"
        self._make_skill_dir(path_a, "my-skill", description="workspace version")
        self._make_skill_dir(path_b, "my-skill", description="user version")

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(path_a), str(path_b)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert plugin._skills["my-skill"].description == "workspace version"

    def test_empty_directory(self, tmp_path):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert len(plugin._skills) == 0

    def test_nonexistent_path(self, tmp_path):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path / "does-not-exist")]}})
        plugin._discover_skills()

        assert len(plugin._skills) == 0


# === System Prompt ===


class TestSystemPrompt:
    def _make_plugin_with_skills(self, tmp_path, *skill_names) -> SkillsPlugin:
        for name in skill_names:
            skill_dir = tmp_path / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Skill {name}\n---\n# {name}"
            )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()
        return plugin

    def test_no_skills_returns_empty(self, tmp_path):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert plugin._format_skills_prompt() == ""

    @pytest.mark.asyncio
    async def test_no_skills_ctx_unchanged(self, tmp_path):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        ctx = {"prompt": "You are Cobot."}
        result = await plugin.transform_system_prompt(ctx)
        assert result["prompt"] == "You are Cobot."

    def test_single_skill_xml(self, tmp_path):
        plugin = self._make_plugin_with_skills(tmp_path, "test-skill")
        prompt = plugin._format_skills_prompt()

        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt
        assert "<name>test-skill</name>" in prompt
        assert "<description>Skill test-skill</description>" in prompt
        assert "<location>" in prompt
        assert "load_skill" in prompt

    @pytest.mark.asyncio
    async def test_transform_appends_to_prompt(self, tmp_path):
        plugin = self._make_plugin_with_skills(tmp_path, "test-skill")

        ctx = {"prompt": "You are Cobot."}
        result = await plugin.transform_system_prompt(ctx)

        assert result["prompt"].startswith("You are Cobot.")
        assert "<available_skills>" in result["prompt"]
        assert "<name>test-skill</name>" in result["prompt"]

    def test_multiple_skills(self, tmp_path):
        plugin = self._make_plugin_with_skills(tmp_path, "skill-a", "skill-b")
        prompt = plugin._format_skills_prompt()

        assert prompt.count("<skill>") == 2
        assert "<name>skill-a</name>" in prompt
        assert "<name>skill-b</name>" in prompt

    def test_xml_escaping_in_description(self, tmp_path):
        skill_dir = tmp_path / "esc-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: esc-skill\ndescription: "Use <tags> & stuff"\n---\n'
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        prompt = plugin._format_skills_prompt()
        assert "&lt;tags&gt;" in prompt
        assert "&amp;" in prompt


# === Load Skill Tool ===


class TestLoadSkillTool:
    def test_tool_definition(self):
        plugin = create_plugin()
        defs = plugin.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "load_skill"

    def test_load_valid_skill(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test\n---\n# Instructions\nDo things."
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        result = plugin.execute("load_skill", {"name": "my-skill"})

        assert "## Skill: my-skill" in result
        assert "# Instructions" in result
        assert "Do things." in result

    def test_load_unknown_skill(self):
        plugin = create_plugin()
        plugin.configure({})

        result = plugin.execute("load_skill", {"name": "nonexistent"})
        assert "Error" in result
        assert "not found" in result

    def test_load_missing_name(self):
        plugin = create_plugin()
        plugin.configure({})

        result = plugin.execute("load_skill", {})
        assert "Error" in result
        assert "required" in result

    def test_unknown_tool(self):
        plugin = create_plugin()
        result = plugin.execute("nonexistent", {})
        assert "Unknown tool" in result

    def test_resolves_relative_paths(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        rules_dir = skill_dir / "rules"
        skill_dir.mkdir()
        rules_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test\n---\nSee ./rules/guide.md"
        )
        (rules_dir / "guide.md").write_text("# Guide content")

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        result = plugin.execute("load_skill", {"name": "my-skill"})

        assert "./" not in result
        assert str(skill_dir.resolve() / "rules" / "guide.md") in result


# === Provenance & Trust ===


class TestProvenance:
    def test_verified_author(self, tmp_path):
        skill_dir = tmp_path / "trusted-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: trusted-skill\ndescription: Test\nauthor: npub1abc\n---\n"
        )

        plugin = create_plugin()
        plugin.configure(
            {
                "skills": {"paths": [str(tmp_path)]},
                "trusted": [{"npub": "npub1abc", "name": "Alice"}],
            }
        )
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert plugin._skills["trusted-skill"].verified is True

    def test_unverified_author(self, tmp_path):
        skill_dir = tmp_path / "untrusted-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: untrusted-skill\ndescription: Test\nauthor: npub1xyz\n---\n"
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert plugin._skills["untrusted-skill"].verified is False

    def test_no_author(self, tmp_path):
        skill_dir = tmp_path / "no-author"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: no-author\ndescription: Test\n---\n"
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert plugin._skills["no-author"].verified is False
        assert plugin._skills["no-author"].author == ""

    def test_installed_from_file(self, tmp_path):
        skill_dir = tmp_path / "remote-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: remote-skill\ndescription: Test\n---\n"
        )
        (skill_dir / ".installed_from").write_text("github:user/repo")

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        plugin._discover_skills()

        assert plugin._skills["remote-skill"].installed_from == "github:user/repo"


# === Lifecycle ===


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_with_skills(self, tmp_path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n"
        )

        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        await plugin.start()

        assert len(plugin._skills) == 1

    @pytest.mark.asyncio
    async def test_start_empty(self, tmp_path):
        plugin = create_plugin()
        plugin.configure({"skills": {"paths": [str(tmp_path)]}})
        plugin._workspace_path = tmp_path
        await plugin.start()

        assert len(plugin._skills) == 0

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()

    def test_restart_requested(self):
        assert create_plugin().restart_requested is False


# === Local Path Detection ===


class TestIsLocalPath:
    def test_relative_dot_slash(self):
        assert _is_local_path("./skills") is True

    def test_absolute(self):
        assert _is_local_path("/tmp/skills") is True

    def test_home(self):
        assert _is_local_path("~/skills") is True

    def test_parent(self):
        assert _is_local_path("../skills") is True

    def test_github_shorthand(self):
        assert _is_local_path("user/repo") is False

    def test_url(self):
        assert _is_local_path("https://github.com/user/repo") is False
