# Skills Plugin

Markdown-based skill discovery, loading, and CLI management for Cobot agents.

## Overview

Skills are instruction files (`SKILL.md`) that teach the agent how to perform specific tasks. The skills plugin discovers installed skills, injects them into the system prompt, and provides a `load_skill` tool for on-demand loading.

Compatible with the [AgentSkills](https://agentskills.io) spec (OpenClaw, Vercel agent-skills, Claude Code).

## Skill Format

A skill is a directory containing a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-skill
description: What this skill does and when to use it
author: npub1...  # Optional: Nostr npub for provenance
version: 1.0.0    # Optional
---

# Skill Instructions

Your instructions here. Reference sub-files with relative paths:
- See ./guidelines/setup.md for setup
- See ./references/api.md for API details
```

**Only `SKILL.md` at the root is required.** All other directory structure is up to the skill author.

## Configuration

```yaml
# cobot.yml
skills:
  paths:
    - ./skills              # Workspace skills (highest precedence)
    - ~/.cobot/skills       # User-wide skills
  disabled:
    - some-skill-name       # Skip loading this skill
```

## CLI Commands

```bash
cobot skill add <source> --skill <name>    # Install from git remote / local
cobot skill list                           # List installed skills
cobot skill show <name>                    # Show skill metadata
cobot skill remove <name>                  # Uninstall a skill
```

## How It Works

1. **Startup**: Scans configured paths for `*/SKILL.md`, parses frontmatter, builds in-memory registry
2. **System prompt**: Injects `<available_skills>` XML list with name, description, and file path
3. **Runtime**: LLM calls `load_skill(name)` to read full skill content with resolved paths
4. **Sub-files**: LLM uses `read_file` to load any files referenced in the skill
