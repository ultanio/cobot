"""Skill data structures and pure utility functions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64


@dataclass
class Skill:
    """A discovered skill with parsed metadata."""

    name: str
    description: str
    file_path: Path
    base_dir: Path
    source: str  # "workspace", "user", "path"
    author: str = ""
    version: str = ""
    verified: bool = False
    installed_from: str = ""


def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content.

    Splits on first two '---' delimiters and parses the middle section.
    Returns empty dict if no valid frontmatter found.
    """
    if not content.startswith("---"):
        return {}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    try:
        result = yaml.safe_load(parts[1])
        return result if isinstance(result, dict) else {}
    except yaml.YAMLError:
        return {}


def validate_skill_name(name: str) -> bool:
    """Validate skill name against [a-z0-9-]+ pattern."""
    if not name or len(name) > MAX_NAME_LENGTH:
        return False
    return NAME_PATTERN.match(name) is not None


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def resolve_relative_paths(content: str, base_dir: Path) -> str:
    """Replace relative paths in markdown content with absolute paths.

    Matches patterns like ./foo/bar.md, ./foo.md, etc. in markdown content
    and resolves them against the skill's base directory.
    """

    def replace_path(match: re.Match) -> str:
        rel_path = match.group(0)
        abs_path = (base_dir / rel_path).resolve()
        return str(abs_path)

    return re.sub(
        r"\./[a-zA-Z0-9_\-/]+\.(?:md|txt|json|yaml|yml)", replace_path, content
    )
