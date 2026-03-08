"""CLI commands for skill management (add, list, show, remove)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .models import parse_frontmatter, validate_skill_name

if TYPE_CHECKING:
    from .plugin import SkillsPlugin


def register_skill_commands(cli, plugin: SkillsPlugin) -> None:
    """Register all skill CLI commands on the given Click CLI group."""

    @cli.group()
    def skill():
        """Manage agent skills."""
        pass

    @skill.command("list")
    def skill_list():
        """List all installed skills."""
        skills = plugin._discover_and_list()
        if not skills:
            click.echo("No skills installed.")
            return

        for s in skills:
            verified_tag = (
                " (verified)" if s.verified else " (unverified)" if s.author else ""
            )
            author_str = f" by {s.author[:20]}...{verified_tag}" if s.author else ""
            source_str = f" [{s.source}]"
            click.echo(f"  {s.name} — {s.description}{author_str}{source_str}")

    @skill.command("show")
    @click.argument("name")
    def skill_show(name: str):
        """Show detailed metadata for a skill."""
        skills = plugin._discover_and_list()
        match = next((s for s in skills if s.name == name), None)

        if not match:
            raise click.ClickException(f"Skill '{name}' not found")

        click.echo(f"\nSkill: {match.name}")
        click.echo("-" * 40)
        click.echo(_format_skill_detail(match))

    @skill.command("remove")
    @click.argument("name")
    def skill_remove(name: str):
        """Remove an installed skill."""
        skills = plugin._discover_and_list()
        match = next((s for s in skills if s.name == name), None)

        if not match:
            raise click.ClickException(f"Skill '{name}' not found")

        try:
            shutil.rmtree(match.base_dir)
            click.echo(f"Removed skill: {name}")
        except Exception as e:
            raise click.ClickException(f"Failed to remove '{name}': {e}")

    @skill.command("add")
    @click.argument("source")
    @click.option(
        "--skill",
        "skill_names",
        multiple=True,
        help="Skill name(s) to install from the source",
    )
    def skill_add(source: str, skill_names: tuple[str, ...]):
        """Install skills from a local path or git repository.

        SOURCE can be:
          - Local path: ./path, /absolute/path, ~/path
          - Git URL: https://github.com/user/repo
          - GitHub shorthand: user/repo
        """
        if _is_local_path(source):
            _install_from_local(plugin, Path(source).expanduser(), skill_names)
        else:
            _install_from_git(plugin, source, skill_names)


# === Formatting ===


def _format_skill_detail(skill) -> str:
    """Format skill metadata for display."""
    lines = [f"  Description: {skill.description}"]
    if skill.version:
        lines.append(f"  Version:     {skill.version}")
    if skill.author:
        status = "verified" if skill.verified else "unverified"
        lines.append(f"  Author:      {skill.author} ({status})")
    lines.append(f"  Source:      {skill.source}")
    lines.append(f"  Path:        {skill.file_path}")
    if skill.installed_from:
        lines.append(f"  Installed:   {skill.installed_from}")
    return "\n".join(lines)


# === Helpers ===


def _is_local_path(source: str) -> bool:
    """Detect if source is a local path."""
    return source.startswith(("./", "/", "~", "../"))


def _get_install_dir() -> Path:
    """Get the user-level skill install directory."""
    install_dir = Path.home() / ".cobot" / "skills"
    install_dir.mkdir(parents=True, exist_ok=True)
    return install_dir


def _install_from_local(
    plugin: SkillsPlugin, source_path: Path, skill_names: tuple[str, ...]
):
    """Install skill(s) from a local path."""
    source_path = source_path.resolve()

    if not source_path.exists():
        raise click.ClickException(f"Path does not exist: {source_path}")

    # If source is a skill directory itself (has SKILL.md)
    if (source_path / "SKILL.md").exists():
        _install_single_skill(plugin, source_path, f"local:{source_path}")
        return

    # If source is a directory containing multiple skills
    if skill_names:
        for name in skill_names:
            skill_dir = source_path / name
            if not skill_dir.exists():
                skill_dir = source_path / "skills" / name
            if not skill_dir.exists() or not (skill_dir / "SKILL.md").exists():
                raise click.ClickException(f"Skill '{name}' not found in {source_path}")
            _install_single_skill(plugin, skill_dir, f"local:{source_path}")
    else:
        raise click.ClickException(
            "Specify --skill <name> when source contains multiple skills"
        )


def _install_from_git(plugin: SkillsPlugin, source: str, skill_names: tuple[str, ...]):
    """Install skill(s) from a git repository."""
    if not shutil.which("git"):
        raise click.ClickException(
            "git is required for remote skill installation. "
            "Use a local path instead: skill add ./path --skill name"
        )

    if not skill_names:
        raise click.ClickException("--skill <name> is required for remote sources")

    # Resolve GitHub shorthand to URL
    if not source.startswith("http"):
        git_url = f"https://github.com/{source}.git"
        source_label = f"github:{source}"
    else:
        git_url = source if source.endswith(".git") else f"{source}.git"
        source_label = f"url:{source}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", git_url, str(tmp_path / "repo")],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to clone {source}: {e.stderr.strip()}")
        except subprocess.TimeoutExpired:
            raise click.ClickException(f"Clone timed out for {source}")

        repo_path = tmp_path / "repo"

        for name in skill_names:
            # Search common locations
            skill_dir = None
            for candidate in [
                repo_path / "skills" / name,
                repo_path / name,
            ]:
                if candidate.exists() and (candidate / "SKILL.md").exists():
                    skill_dir = candidate
                    break

            if not skill_dir:
                raise click.ClickException(f"Skill '{name}' not found in {source}")

            _install_single_skill(plugin, skill_dir, source_label)


def _install_single_skill(plugin: SkillsPlugin, skill_dir: Path, source_label: str):
    """Validate and install a single skill directory."""
    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        raise click.ClickException(f"No SKILL.md found in {skill_dir}")

    content = skill_file.read_text()
    fm = parse_frontmatter(content)

    name = fm.get("name", "")
    description = fm.get("description", "")

    if not name or not description:
        raise click.ClickException(
            f"SKILL.md missing required fields (name, description) in {skill_dir}"
        )

    if not validate_skill_name(name):
        raise click.ClickException(f"Invalid skill name '{name}'")

    install_dir = _get_install_dir()
    target = install_dir / name

    if target.exists():
        shutil.rmtree(target)

    shutil.copytree(skill_dir, target)

    # Write install source metadata
    (target / ".installed_from").write_text(source_label)

    version = fm.get("version", "")
    author = fm.get("author", "")
    version_str = f" (v{version})" if version else ""

    click.echo(f"Installed {name}{version_str} from {source_label}")

    if author:
        verified = author in plugin._trusted_npubs
        status = "verified" if verified else "unverified — not in your trust network"
        click.echo(f"  Author: {author} ({status})")
    elif not author:
        click.echo("  Author: none specified")
