"""Skills plugin - markdown-based skill discovery, loading, and CLI management.

Discovers SKILL.md files from configured directories, injects available skills
into the system prompt, and provides a load_skill tool for on-demand loading.

Compatible with the AgentSkills spec (OpenClaw, Vercel agent-skills, Claude Code).

Priority: 19 (after soul, trust, context; before service plugins)
Capabilities: tools (provides load_skill)
Implements: context.system_prompt, cli.commands
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta
from ..interfaces import ToolProvider
from .models import (
    Skill,
    escape_xml,
    parse_frontmatter,
    resolve_relative_paths,
    validate_skill_name,
)

# === Tool Definition ===

LOAD_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Load a skill's full instructions by name. Use when a task matches "
            "a skill listed in the available_skills section of the system prompt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The skill name from the available_skills list",
                },
            },
            "required": ["name"],
        },
    },
}


class SkillsPlugin(Plugin, ToolProvider):
    """Skills discovery, prompt injection, and CLI management."""

    meta = PluginMeta(
        id="skills",
        version="1.0.0",
        capabilities=["tools"],
        dependencies=["config"],
        optional_dependencies=["workspace"],
        implements={
            "loop.transform_system_prompt": "transform_system_prompt",
            "cli.commands": "register_commands",
        },
        priority=19,
    )

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._paths: list[Path] = [Path("./skills"), Path.home() / ".cobot" / "skills"]
        self._disabled: list[str] = []
        self._trusted_npubs: set[str] = set()
        self._workspace_path: Path = Path(".")

    def configure(self, config: dict) -> None:
        skills_config = config.get("skills", {})
        paths_config = skills_config.get("paths", config.get("paths", {}).get("skills"))

        if isinstance(paths_config, list):
            self._paths = [Path(p).expanduser() for p in paths_config]
        elif isinstance(paths_config, str):
            self._paths = [Path(paths_config).expanduser()]
        else:
            self._paths = [Path("./skills"), Path.home() / ".cobot" / "skills"]

        self._disabled = skills_config.get("disabled", [])

        trusted = config.get("trusted", [])
        self._trusted_npubs = {
            t.get("npub", "") for t in trusted if isinstance(t, dict) and t.get("npub")
        }

        if "_workspace_path" in config:
            self._workspace_path = Path(config["_workspace_path"])

    async def start(self) -> None:
        if self._registry:
            try:
                workspace = self._registry.get_plugin("workspace")
                if workspace:
                    self._workspace_path = workspace.get_path()
            except Exception:
                pass

        self._discover_skills()

        count = len(self._skills)
        if count:
            self.log_info(f"Discovered {count} skill(s)")
        else:
            self.log_info("No skills found")

    async def stop(self) -> None:
        pass

    # === Discovery ===

    def _discover_skills(self) -> None:
        """Scan configured paths for SKILL.md files and build registry."""
        self._skills.clear()

        for skill in self._scan_all_paths():
            if skill.name in self._disabled:
                self.log_debug(f"Skipping disabled skill: {skill.name}")
                continue

            if skill.name not in self._skills:
                self._skills[skill.name] = skill
            else:
                self.log_debug(
                    f"Skipping duplicate skill '{skill.name}' from {skill.base_dir} "
                    f"(already loaded from {self._skills[skill.name].base_dir})"
                )

    def _classify_source(self, path: Path) -> str:
        """Classify a skill path as workspace, user, or path."""
        resolved = path.resolve()
        home_skills = (Path.home() / ".cobot" / "skills").resolve()
        workspace_skills = (self._workspace_path / "skills").resolve()

        if str(resolved).startswith(str(workspace_skills)):
            return "workspace"
        elif str(resolved).startswith(str(home_skills)):
            return "user"
        return "path"

    def _load_skill_from_file(self, skill_file: Path, source: str) -> Optional[Skill]:
        """Parse a SKILL.md file and return a Skill object, or None if invalid."""
        try:
            content = skill_file.read_text()
        except Exception as e:
            self.log_warn(f"Failed to read {skill_file}: {e}")
            return None

        fm = parse_frontmatter(content)
        if not fm:
            self.log_warn(f"No valid frontmatter in {skill_file}")
            return None

        name = fm.get("name", "")
        description = fm.get("description", "")

        if not name or not description:
            self.log_warn(
                f"Missing required fields (name, description) in {skill_file}"
            )
            return None

        if not validate_skill_name(name):
            self.log_warn(f"Invalid skill name '{name}' in {skill_file}")
            return None

        parent_dir_name = skill_file.parent.name
        if name != parent_dir_name:
            self.log_warn(
                f"Skill name '{name}' does not match directory "
                f"'{parent_dir_name}' in {skill_file}"
            )
            return None

        author = fm.get("author", "")
        verified = author in self._trusted_npubs if author else False

        installed_from_file = skill_file.parent / ".installed_from"
        installed_from = ""
        if installed_from_file.exists():
            try:
                installed_from = installed_from_file.read_text().strip()
            except Exception:
                pass

        return Skill(
            name=name,
            description=description,
            file_path=skill_file.resolve(),
            base_dir=skill_file.parent.resolve(),
            source=source,
            author=author,
            version=fm.get("version", ""),
            verified=verified,
            installed_from=installed_from,
        )

    def _discover_and_list(self) -> list[Skill]:
        """Discover skills fresh for CLI commands (don't require start())."""
        skills: dict[str, Skill] = {}
        for skill in self._scan_all_paths():
            if skill.name not in skills:
                skills[skill.name] = skill
        return list(skills.values())

    def _scan_all_paths(self) -> list[Skill]:
        """Scan all configured paths and return valid skills found."""
        results = []
        for skill_path in self._paths:
            if not skill_path.exists() or not skill_path.is_dir():
                continue

            source = self._classify_source(skill_path)

            for entry in sorted(skill_path.iterdir()):
                if not entry.is_dir() or entry.name.startswith((".", "_")):
                    continue

                skill_file = entry / "SKILL.md"
                if not skill_file.exists():
                    continue

                skill = self._load_skill_from_file(skill_file, source)
                if skill:
                    results.append(skill)

        return results

    # === System Prompt (loop.transform_system_prompt) ===

    async def transform_system_prompt(self, ctx: dict) -> dict:
        """Append available skills list to the system prompt.

        Hooks into loop.transform_system_prompt chain — same pattern as
        the trust plugin. The skills list becomes part of the role: system
        message, so the LLM treats it as authoritative.
        """
        skills_section = self._format_skills_prompt()
        if skills_section:
            ctx["prompt"] = ctx.get("prompt", "") + skills_section
        return ctx

    def _format_skills_prompt(self) -> str:
        """Format available skills as compact XML for system prompt."""
        if not self._skills:
            return ""

        lines = [
            "\n\nThe following skills provide specialized instructions for specific tasks.",
            "Use the load_skill tool to load a skill when the task matches its description.",
            "",
            "<available_skills>",
        ]

        for skill in self._skills.values():
            lines.append("  <skill>")
            lines.append(f"    <name>{escape_xml(skill.name)}</name>")
            lines.append(
                f"    <description>{escape_xml(skill.description)}</description>"
            )
            lines.append(f"    <location>{escape_xml(str(skill.file_path))}</location>")
            lines.append("  </skill>")

        lines.append("</available_skills>")

        return "\n".join(lines)

    # === Tool (ToolProvider) ===

    def get_definitions(self) -> list[dict]:
        return [LOAD_SKILL_TOOL]

    def execute(self, tool_name: str, args: dict) -> str:
        if tool_name == "load_skill":
            return self._execute_load_skill(args)
        return f"Error: Unknown tool '{tool_name}'"

    def _execute_load_skill(self, args: dict) -> str:
        """Load a skill by name and return its content with resolved paths."""
        name = args.get("name", "")
        if not name:
            return "Error: 'name' parameter is required"

        skill = self._skills.get(name)
        if not skill:
            return f"Error: Skill '{name}' not found"

        try:
            content = skill.file_path.read_text()
        except Exception as e:
            return f"Error: Failed to read skill '{name}': {e}"

        resolved_content = resolve_relative_paths(content, skill.base_dir)

        header = f"## Skill: {skill.name} (loaded from {skill.base_dir})\n\n"
        return header + resolved_content

    @property
    def restart_requested(self) -> bool:
        return False

    # === CLI (cli.commands) ===

    def register_commands(self, cli) -> None:
        from .cli import register_skill_commands

        register_skill_commands(cli, self)


def create_plugin() -> SkillsPlugin:
    """Factory function for plugin discovery."""
    return SkillsPlugin()
